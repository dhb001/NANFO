"""Small CPU categorical PPO with explicit episode and bootstrap masks."""

from typing import Annotated

import numpy as np
import torch
from pydantic import Field
from torch import nn
from torch.distributions import Categorical

from .contracts import STATE_DIM, StrictModel


class PPOConfig(StrictModel):
    hidden: Annotated[int, Field(ge=8, le=256)] = 32
    learning_rate: Annotated[float, Field(gt=0, le=0.01)] = 0.0003
    gamma: Annotated[float, Field(ge=0, le=1)] = 0.99
    gae_lambda: Annotated[float, Field(ge=0, le=1)] = 0.95
    clip: Annotated[float, Field(gt=0, le=0.5)] = 0.2
    entropy: Annotated[float, Field(ge=0, le=0.1)] = 0.01
    value_weight: Annotated[float, Field(gt=0, le=2)] = 0.5
    max_grad_norm: Annotated[float, Field(gt=0, le=10)] = 0.5
    epochs: Annotated[int, Field(ge=1, le=20)] = 4
    minibatch: Annotated[int, Field(ge=2, le=512)] = 32
    rollout: Annotated[int, Field(ge=2, le=4096)] = 16
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 42


def seedRuntime(seed: int):
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("runtime seed outside bounds")
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)


class ActorCritic(nn.Module):
    def __init__(self, hidden=32):
        super().__init__()
        self.actorBody = nn.Sequential(nn.Linear(STATE_DIM, hidden), nn.Tanh())
        self.criticBody = nn.Sequential(nn.Linear(STATE_DIM, hidden), nn.Tanh())
        self.actor = nn.Linear(hidden, 2)
        self.critic = nn.Linear(hidden, 1)
        for body in (self.actorBody, self.criticBody):
            nn.init.orthogonal_(body[0].weight, gain=2**0.5)
            nn.init.zeros_(body[0].bias)
        nn.init.orthogonal_(self.actor.weight, gain=0.01)
        nn.init.orthogonal_(self.critic.weight, gain=1.0)
        nn.init.zeros_(self.actor.bias)
        nn.init.zeros_(self.critic.bias)

    def forward(self, states):
        return self.actor(self.actorBody(states)), self.critic(self.criticBody(states)).squeeze(-1)

    @torch.no_grad()
    def decide(self, state, *, deterministic=False):
        state = torch.as_tensor(state, dtype=torch.float32)
        if state.shape != (STATE_DIM,) or not torch.isfinite(state).all():
            raise ValueError("inference requires one finite state vector")
        logits, value = self(state)
        if not torch.isfinite(logits).all() or not torch.isfinite(value):
            raise ValueError("nonfinite policy output")
        distribution = Categorical(logits=logits)
        action = logits.argmax(-1) if deterministic else distribution.sample()
        return (
            int(action),
            float(distribution.log_prob(action)),
            float(value),
            distribution.probs.tolist(),
        )


def generalizedAdvantage(
    rewards, values, nextValues, terminated, truncated, gamma=0.99, gaeLambda=0.95
):
    """Time limits bootstrap V(final_obs) but stop recursion across reset boundaries."""
    rewards, values, nextValues = [
        torch.as_tensor(x, dtype=torch.float32) for x in (rewards, values, nextValues)
    ]
    terminated, truncated = [torch.as_tensor(x, dtype=torch.bool) for x in (terminated, truncated)]
    if (
        rewards.ndim != 1
        or any(x.shape != rewards.shape for x in (values, nextValues, terminated, truncated))
        or not all(torch.isfinite(x).all() for x in (rewards, values, nextValues))
    ):
        raise ValueError("GAE requires aligned finite valid transitions")
    advantage = torch.zeros_like(rewards)
    carry = 0.0
    for index in reversed(range(len(rewards))):
        delta = rewards[index] + gamma * nextValues[index] * (~terminated[index]) - values[index]
        carry = delta + gamma * gaeLambda * (~(terminated[index] | truncated[index])) * carry
        advantage[index] = carry
    return advantage, advantage + values


def clippedObjective(newLogProb, oldLogProb, advantage, clip):
    ratio = (newLogProb - oldLogProb).exp()
    return torch.minimum(ratio * advantage, ratio.clamp(1 - clip, 1 + clip) * advantage)


class PPO:
    def __init__(self, config=None):
        config = config if config is not None else PPOConfig()
        self.config = config
        seedRuntime(config.seed)
        self.model = ActorCritic(config.hidden)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=config.learning_rate)
        self.updates = 0
        self.transitions = 0

    def update(self, rollout: list[dict]) -> dict:
        if not 2 <= len(rollout) <= self.config.rollout:
            raise ValueError("rollout size outside bounds")
        if any(row.get("valid_transition") is not True for row in rollout):
            raise ValueError("invalid windows cannot enter PPO")
        if any(
            type(row["action"]) is not int
            or row["action"] not in (0, 1)
            or type(row["terminated"]) is not bool
            or type(row["truncated"]) is not bool
            for row in rollout
        ):
            raise ValueError("invalid PPO action or boundary flags")
        states = torch.as_tensor(np.stack([row["state"] for row in rollout]), dtype=torch.float32)
        actions = torch.tensor([row["action"] for row in rollout], dtype=torch.int64)
        oldLogProb = torch.tensor([row["log_prob"] for row in rollout], dtype=torch.float32)
        if (
            states.shape != (len(rollout), STATE_DIM)
            or not torch.isfinite(states).all()
            or not torch.isfinite(oldLogProb).all()
            or not ((actions >= 0) & (actions < 2)).all()
        ):
            raise ValueError("invalid PPO batch")
        advantage, returns = generalizedAdvantage(
            *[
                [row[key] for row in rollout]
                for key in ("reward", "value", "next_value", "terminated", "truncated")
            ],
            gamma=self.config.gamma,
            gaeLambda=self.config.gae_lambda,
        )
        advantage = (advantage - advantage.mean()) / (advantage.std(unbiased=False) + 1e-8)
        metrics = []
        self.model.train()
        for _ in range(self.config.epochs):
            indices = torch.randperm(len(rollout))
            for batch in indices.split(self.config.minibatch):
                logits, values = self.model(states[batch])
                distribution = Categorical(logits=logits)
                logProb = distribution.log_prob(actions[batch])
                policyLoss = -clippedObjective(
                    logProb, oldLogProb[batch], advantage[batch], self.config.clip
                ).mean()
                valueLoss = (returns[batch] - values).square().mean()
                entropy = distribution.entropy().mean()
                loss = (
                    policyLoss
                    + self.config.value_weight * valueLoss
                    - self.config.entropy * entropy
                )
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite PPO loss")
                self.optimizer.zero_grad(set_to_none=True)
                loss.backward()
                gradNorm = nn.utils.clip_grad_norm_(
                    self.model.parameters(), self.config.max_grad_norm, error_if_nonfinite=True
                )
                self.optimizer.step()
                metrics.append(
                    [
                        float(policyLoss.detach()),
                        float(valueLoss.detach()),
                        float(entropy.detach()),
                        float(gradNorm),
                    ]
                )
        self.updates += 1
        self.transitions += len(rollout)
        result = dict(
            zip(
                ("policy_loss", "value_loss", "entropy", "preclip_grad_norm"),
                np.mean(metrics, axis=0).tolist(),
                strict=True,
            )
        )
        with torch.no_grad():
            logits, predicted = self.model(states)
            logRatio = Categorical(logits=logits).log_prob(actions) - oldLogProb
            ratio = logRatio.exp()
            variance = returns.var(unbiased=False)
            result.update(
                approximate_kl=float(((ratio - 1) - logRatio).mean()),
                clip_fraction=float(((ratio - 1).abs() > self.config.clip).float().mean()),
                explained_variance=(
                    float(1 - (returns - predicted).var(unbiased=False) / variance)
                    if variance > 1e-12
                    else None
                ),
            )
        return result
