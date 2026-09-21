"""Independent offline probes; no Docker, lab, DB or external Redis."""
import asyncio
import copy
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import tests.conftest  # isolated test environment, no service startup

ROOT = Path('/home/DHB/Documents/NANFO')
PLAN = Path('/tmp/opencode/nanfo-experimental-campaign-001')


def test_plan_current_source_pins():
    from scripts.verify_experimental_lab import source_pins, read
    declared = read(PLAN / 'plan.json')['source_sha256']
    current = source_pins()
    changed = [name for name in sorted(set(declared) | set(current)) if declared.get(name) != current.get(name)]
    print('SOURCE_DRIFT', json.dumps(changed))
    assert not changed, changed


def test_campaign_authority_receipt_unique_for_one_pending_mutation(tmp_path, monkeypatch):
    from scripts.verify_experimental_lab import campaign_receiver_class
    from emulation.experimental_lab_receiver import Receiver
    from emulation.experimental_lab_contract import atomic_write, digest
    monkeypatch.setattr(Receiver, 'authority', lambda self: None)
    cls = campaign_receiver_class()
    receiver = cls.__new__(cls)
    entry = dict(node='r', argv=['ip','route','add','10.0.0.1/32'], began=1.0,
                 completed=None, restoring=False)
    receiver.runtime = SimpleNamespace(restoring=False, transcript=[entry])
    receiver.current = SimpleNamespace(request_id='actual-request')
    receiver.directory, receiver.checkpoint_events = tmp_path, []
    identity = digest({'entry':entry, 'request_id':'actual-request'})
    atomic_write(tmp_path/'checkpoint-response.json', {'id':identity,'authorized':True})
    # Watchdog and writer both invoke self.authority while this add is pending.
    receiver.authority()
    receiver.authority()
    assert len(receiver.checkpoint_events) == 1, receiver.checkpoint_events


@pytest.mark.asyncio
async def test_preregistered_numeric_policy_same_for_all_baselines():
    from tests.unit.test_experimental_simulation_raw import durable_case
    from app.modules.autonomy.experimental.comparators import ComparatorAdapter
    from app.modules.autonomy.experimental.simulation import ConfiguredSimulator, evaluator_sha256
    plan = json.loads((PLAN/'plan.json').read_bytes())
    summaries = []
    for scenario in ('path0','path1'):
        frame, policy, now, _ = durable_case(scenario)
        policy = policy.model_copy(update={'assumptions':plan['simulation']['assumptions'],
            'objectives':plan['simulation']['objectives'], 'evaluator_sha256':evaluator_sha256()})
        lanes = []
        for kind in ('fixed0','fixed1','heuristic'):
            active = policy.model_copy(update={'policy_kind':kind})
            inferred = await ComparatorAdapter(active).infer(frame)
            record = await ConfiguredSimulator(clock=lambda:now).simulate(frame,inferred,active)
            lanes.append(record)
        assert len({r.result['admission_policy_sha256'] for r in lanes})==1
        for i in (0,1):
            metrics = [r.result['per_action'][i]['result']['flows'] for r in lanes]
            assert metrics[0]==metrics[1]==metrics[2]
            admission = lanes[0].result['per_action'][i]
            assert admission['scenario_config']['limits']==plan['simulation']['objectives']
            summaries.append({'scenario':scenario,'action':i,'gate':admission['risk_gate'],
                'foreground':admission['result']['flows']['foreground']})
    print('PREREGISTERED_NUMERICAL_REPLAY',json.dumps(summaries,sort_keys=True))


@pytest.mark.asyncio
async def test_stop_during_final_current_authority_read_is_not_admitted():
    from app.modules.autonomy.experimental.controller import ExperimentalController
    from tests.experimental_lab_support import case
    fixture = case()
    ctl = ExperimentalController(lambda: None, fixture.authority, None, fixture.policy)
    stopped = False
    calls = 0

    async def state(**kwargs):
        if stopped:
            raise ValueError('experimental_stop_latched')
        return datetime.now(UTC) + timedelta(seconds=30)

    async def authority(policy):
        nonlocal calls, stopped
        calls += 1
        if calls == 2:
            # Models a committed STOP during the last blocking Identity call.
            stopped = True

    ctl._checkpoint_state = state
    ctl.authority = SimpleNamespace(check=authority)
    with pytest.raises(ValueError, match='stop'):
        await ctl.checkpoint()


def test_bootstrap_stop_during_admission_read_is_not_admitted(tmp_path, monkeypatch):
    import emulation.experimental_lab_receiver as module
    from emulation.tests.test_experimental_lab import ContractTests
    from emulation.experimental_lab_contract import atomic_write, Request, canonical
    tmp_path.chmod(0o700)
    receiver, *_ = ContractTests().receiver(tmp_path)
    req = ContractTests().wire(receiver, 'bootstrap')
    receiver.current = Request.parse(canonical(req))
    atomic_write(tmp_path / 'bootstrap-admission.json', {
        'policy_sha256': receiver.policy_hash, 'request_id': req['request_id'],
        'expires_at': time.time()+30, 'authorized': True})
    original = module.protected_read

    def reading(path, *args):
        raw = original(path, *args)
        if Path(path).name == 'bootstrap-admission.json':
            receiver.latch_stop('independent-test', 'stop-1')
        return raw

    monkeypatch.setattr(module, 'protected_read', reading)
    try:
        with pytest.raises(ValueError, match='stop|authority'):
            receiver.authority()
    finally:
        os.close(receiver.claim)


@pytest.mark.asyncio
async def test_real_confined_model_on_preserved_raw_wrapped_observation(tmp_path):
    """Historical raw frame with explicit offline clock envelope; not fresh lab evidence."""
    from fakeredis.aioredis import FakeRedis
    from app.modules.autonomy.experimental import live_adapters
    from app.modules.autonomy.experimental.schemas import MeasuredFrame, contract_digest
    from app.modules.autonomy.experimental.authority import inference_allowed
    from app.modules.autonomy.live_settings import LiveSettings
    from app.modules.autonomy.registry import LiveRegistry
    from app.modules.autonomy.live_schemas import PassiveSnapshot
    from app.modules.autonomy.schemas import Observation
    from emulation.experimental_lab_contract import IMAGE, SOURCE, MODEL, wrapper_digest
    from scripts.verify_experimental_lab import write
    from tests.experimental_lab_support import case

    tmp_path.chmod(0o700)
    root = ROOT / 'ai-engine/artifacts/adr024-qualified-001/model'
    template = json.loads((root / 'live-registry.template.json').read_bytes())
    now = datetime.now(UTC)
    fixture = case()
    observations = tmp_path / 'observations'
    observations.mkdir(mode=0o700)
    template.update(installed_at=(now-timedelta(seconds=5)).isoformat(),
        expires_at=(now+timedelta(minutes=10)).isoformat(), scopes=[dict(
        network_id=str(fixture.policy.network_id), workspace_id=str(fixture.policy.workspace_id), snapshot_path='snapshot.json')])
    registry_pin = write(tmp_path / 'registry.json', template)
    registry = LiveRegistry(LiveSettings(str(tmp_path/'registry.json'), registry_pin, str(root),
        str(ROOT/'ai-engine/.venv/bin/python'), str(observations)))
    runtime = fixture.policy.runtime.model_copy(update={'container_id':'c'*64,
        'image_sha256':IMAGE.removeprefix('sha256:'), 'source_sha256':SOURCE, 'wrapper_sha256':wrapper_digest()})
    adapter_pin = hashlib.sha256(Path(live_adapters.__file__).read_bytes()).hexdigest()
    model_source = contract_digest(template['source_sha256'])
    weights = json.loads((root/'lineage.json').read_bytes())['tensor_payload_sha256']
    equivalence = live_adapters.WrapperEquivalence(runtime=runtime, registry_sha256=registry_pin,
        checkpoint_sha256=MODEL, weights_sha256=weights, model_source_sha256=model_source,
        model_adapter_sha256=adapter_pin, evidence_sha256=(hashlib.sha256((PLAN/'offline-gates.json').read_bytes()).hexdigest(),),
        scope='independent OFFLINE raw-frame/model replay; synthetic clock envelope, no live equivalence claim')
    eq_pin = write(tmp_path/'equivalence.json', equivalence.model_dump(mode='json'))
    from app.modules.autonomy.experimental.schemas import ExperimentalPolicy
    policy = ExperimentalPolicy.model_validate({**fixture.policy.model_dump(), 'runtime':runtime,
        'registry_sha256':registry_pin, 'checkpoint_sha256':MODEL, 'weights_sha256':weights,
        'model_source_sha256':model_source, 'wrapper_equivalence_sha256':eq_pin,
        'model_adapter_sha256':adapter_pin, 'expires_at':now+timedelta(minutes=10),
        'routes':[dict(action_id=f'route{i}',path=['access1',f'dist{i+1}','access2'],
        device_ids=['access1',f'dist{i+1}','access2']) for i in (0,1)]})
    redis = FakeRedis(decode_responses=True)
    adapter = live_adapters.LiveModelAdapter(registry, redis, policy, equivalence_path=tmp_path/'equivalence.json')
    try:
        await adapter.prepare()  # real confined qualification, actual original tensors
        results = []
        for scenario, wanted in [('path0',1), ('path1',0)]:
            raw_history = json.loads((root/f'recorded-history-{scenario}.json').read_bytes())
            untouched = copy.deepcopy(raw_history)
            raw = raw_history['frames'][0]['response']['data']
            observed = datetime.now(UTC)-timedelta(seconds=1)
            interval = raw['evidence']['post_control_interval']
            snapshot = PassiveSnapshot(version='nanfo.passive-measured-v4.v1',
                network_id=policy.network_id, workspace_id=policy.workspace_id, snapshot_id=uuid4(),
                run_id=raw['episode_id'], observed_at=observed,
                window_started_at=observed-timedelta(seconds=interval['end']-interval['start']),
                published_at=datetime.now(UTC), source='operator-attested-measured-lab',
                contract_sha256=template['contract_sha256'], spec_sha256=template['spec_sha256'],
                history=raw_history, history_sha256=contract_digest(raw_history))
            frame = MeasuredFrame(snapshot=snapshot, runtime=runtime, features=raw['observation'],
                observation=Observation(network_id=policy.network_id,workspace_id=policy.workspace_id,
                    provider_id='offline-independent-review',contract=snapshot.version, observed_at=observed,
                    collected_at=datetime.now(UTC), age_seconds=1, fresh=True,compatible=True,evidence=['offline']),
                provenance={'scope':'offline historical raw, synthetic clock only','wrapper_sha256':runtime.wrapper_sha256})
            record = await adapter.infer(frame)
            inference_allowed(policy,frame,record)
            assert record.result.action == wanted
            assert snapshot.run_id != policy.run_id
            assert frame.snapshot.history == untouched
            assert raw['evidence']['provenance']=={'lab_image_id':IMAGE,'source_sha256':SOURCE}
            assert record.wrapper_equivalence_sha256 == eq_pin
            results.append({'scenario':scenario,'action':record.result.action,'probabilities':record.result.probabilities,
                'value':record.result.value,'history_sha256':record.result.history_sha256,
                'input_sha256':record.result.input_sha256,'wrapper_sha256':runtime.wrapper_sha256,
                'checkpoint_sha256':record.result.checkpoint_sha256,'raw_unchanged':True})
        print('REAL_FROZEN_REPLAY',json.dumps(results,sort_keys=True))
    finally:
        await redis.aclose()
