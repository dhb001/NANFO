import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.events.bus import process_entry
from app.events.fanout import FanoutPublisher, FanoutSubscriber
from app.events.fanout_contract import FanoutEnvelope, FanoutSettings
from app.modules.network.schemas import CreateDeviceRequest
from tests.unit.test_distributed_realtime import envelope, fields


def test_hostname_request_bound_blocks_review_repro():
    for hostname in ("", "x" * 254, "x" * 300000):
        with pytest.raises(ValidationError):
            CreateDeviceRequest(hostname=hostname, device_type="switch")
    assert CreateDeviceRequest(hostname="x" * 253, device_type="switch").hostname == "x" * 253


@pytest.mark.parametrize("poison", ["oversize", "schema", "lua_size", "nan", "unsupported"])
async def test_permanent_poison_has_bounded_receipt_and_reset_before_completion(poison):
    redis = AsyncMock()
    redis.exists.return_value = False
    redis.eval.return_value = "1-0"
    if poison == "lua_size":
        redis.eval.side_effect = [-1, "1-0"]
    args = envelope().arguments()
    if poison == "oversize":
        args["node"] = {"hostname": "x" * 300000}
    elif poison == "schema":
        args["network_id"] = None
    elif poison == "nan":
        args["node"] = {"value": float("nan")}
    elif poison == "unsupported":
        args["node"] = {"value": object()}
    publisher = FanoutPublisher(redis, token="leader", settings=FanoutSettings(max_entries=16))
    async def handler(event):
        await publisher.publish(channel="topology", delivery_id=event["event_id"], kwargs=args)
    await process_entry(redis, "stream:network", "group", "1-0", {
        "event_id": "00000000-0000-0000-0000-000000000001", "event_type": "event", "payload": "{}",
    }, {"event": handler})
    call = redis.eval.await_args.args
    assert call[1] == 4 and call[-1] == 16
    receipt, reset = json.loads(call[-3]), FanoutEnvelope.model_validate_json(call[-2])
    assert len(call[-3]) < 512 and "hostname" not in call[-3]
    assert receipt["reason"] in {"oversized_envelope", "invalid_envelope", "encoded_envelope_oversized"}
    assert reset.kind == "reset"
    redis.set.assert_awaited_once()
    redis.xack.assert_awaited_once()
    redis.xadd.assert_not_awaited()  # Never copy huge poison into the generic DLQ.


async def test_poison_quarantine_failure_must_not_ack():
    redis = AsyncMock()
    redis.exists.return_value = False
    redis.eval.side_effect = OSError("no confirmed receipt")
    publisher = FanoutPublisher(redis, token="leader", settings=FanoutSettings())
    async def handler(event):
        await publisher.publish(channel="invalid", delivery_id="poison", kwargs={})
    with pytest.raises(asyncio.CancelledError):
        await process_entry(redis, "stream:network", "group", "1-0", {
            "event_id": "00000000-0000-0000-0000-000000000001", "event_type": "event", "payload": "{}",
        }, {"event": handler})
    redis.xack.assert_not_awaited()
    redis.set.assert_not_awaited()


async def test_reset_closes_stale_projection_until_fresh_heartbeat():
    dispatch, availability = AsyncMock(), AsyncMock()
    subscriber = FanoutSubscriber(None, settings=FanoutSettings(), dispatch=dispatch, availability=availability)
    await subscriber._accept(fields(envelope()))
    await subscriber._accept(fields(envelope(2, kind="reset", channel=None, kwargs=None)))
    assert not subscriber.available
    assert [call.args[0] for call in availability.await_args_list] == [True, False]
    assert dispatch.await_count == 1
    await subscriber._accept(fields(envelope(3, kind="heartbeat", channel=None, kwargs=None)))
    assert subscriber.available
