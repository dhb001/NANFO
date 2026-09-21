"""Acceptance harness boundaries with private provider fixtures; no live claims."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.modules.autonomy.schemas import Qualification
from scripts import verify_fresh_live_provider as verifier
from tests.live_provider_support import provision


async def test_failed_campaign_never_attempts_live_inference(tmp_path, monkeypatch):
    registry, network, workspace, _ = provision(tmp_path)
    provider = SimpleNamespace(qualify=AsyncMock(return_value=Qualification(qualified=False,
        reasons=["live_qualification_validation_failed"])), infer=AsyncMock())
    monkeypatch.setattr(verifier, "FrozenModelProvider", lambda *_: provider)
    result = await verifier.verify_fresh(registry, None, network, workspace)
    assert result["status"] == "blocked"
    provider.infer.assert_not_awaited()


async def test_only_measurements_after_verifier_start_are_accepted(tmp_path, monkeypatch):
    registry, network, workspace, _ = provision(tmp_path)
    observation = SimpleNamespace(compatible=True, fresh=True, observed_at=datetime.now(UTC) - timedelta(seconds=1))
    provider = SimpleNamespace(qualify=AsyncMock(return_value=Qualification(qualified=True)), infer=AsyncMock())
    observer = SimpleNamespace(observe=AsyncMock(return_value=observation))
    monkeypatch.setattr(verifier, "FrozenModelProvider", lambda *_: provider)
    monkeypatch.setattr(verifier, "LiveObserver", lambda *_: observer)
    import pytest
    with pytest.raises(TimeoutError):
        await verifier.verify_fresh(registry, None, network, workspace, timeout_seconds=1)
    provider.infer.assert_not_awaited()
