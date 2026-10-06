"""ADR-028 intent request bounds and additive contract fields."""

import json
import math
import uuid

import pytest
from pydantic import ValidationError

from app.modules.intent.schemas import (
    MAX_INTENT_ARRAY_ITEMS,
    MAX_INTENT_OBJECT_KEYS,
    MAX_INTENT_PAYLOAD_DEPTH,
    ApprovalBinding,
    ExecuteIntentRequest,
    ValidateIntentRequest,
)


def _request(intent):
    return ValidateIntentRequest.model_validate({"workspace_id": str(uuid.uuid4()), "intent": intent})


def _nested(depth):
    value = {"leaf": 1}
    for _ in range(depth - 1):
        value = {"child": value}
    return value


def test_bounded_json_native_intent_is_accepted():
    intent = {"action": "reroute_path", "scope": {"source_host": "h1"}, "constraints": {
        "paths": [["access1", "dist1", "access2"]], "rate_mbps": 1.5, "dscp": None, "flag": True}}
    assert _request(intent).intent == intent
    assert _request(_nested(MAX_INTENT_PAYLOAD_DEPTH)).intent


@pytest.mark.parametrize("intent", [
    _nested(MAX_INTENT_PAYLOAD_DEPTH + 1),                               # depth > 10
    {"blob": "x" * (64 * 1024)},                                          # > 64 KiB serialized
    {f"k{i}": i for i in range(MAX_INTENT_OBJECT_KEYS + 1)},              # too many keys
    {"items": list(range(MAX_INTENT_ARRAY_ITEMS + 1))},                   # array too long
    {"k" * 129: 1},                                                       # key too long
    {"rate": math.nan}, {"rate": math.inf}, {"rate": -math.inf},          # not JSON-native
    {"nested": [[[[[[[[[[[1]]]]]]]]]]]},                                  # deep arrays count too
])
def test_unbounded_or_non_json_intent_is_a_validation_error(intent):
    with pytest.raises(ValidationError):
        _request(intent)


def test_deeply_nested_document_does_not_exhaust_the_stack():
    value = {}
    for _ in range(50_000):
        value = {"x": value}
    with pytest.raises(ValidationError):
        _request(value)


def test_nan_from_wire_json_is_rejected():
    # Python's json accepts NaN tokens; the bound turns them into 422, not a 500.
    body = json.loads('{"workspace_id": "%s", "intent": {"rate": NaN}}' % uuid.uuid4())
    with pytest.raises(ValidationError):
        ValidateIntentRequest.model_validate(body)


def test_execute_accepts_strict_optional_approval_binding():
    binding = {"plan_hash": "a" * 64, "binding_digest": "b" * 64, "run_id": str(uuid.uuid4())}
    request = ExecuteIntentRequest.model_validate({"workspace_id": str(uuid.uuid4()), "intent_id": str(uuid.uuid4()),
                                                   "manual_approval": True, "approval_binding": binding})
    assert request.approval_binding == ApprovalBinding.model_validate(binding)
    for bad in ({**binding, "plan_hash": "A" * 64}, {**binding, "extra": 1}, {**binding, "run_id": "run"}):
        with pytest.raises(ValidationError):
            ExecuteIntentRequest.model_validate({"workspace_id": str(uuid.uuid4()),
                                                 "intent_id": str(uuid.uuid4()), "approval_binding": bad})
    assert ExecuteIntentRequest(workspace_id=uuid.uuid4(), intent_id=uuid.uuid4()).approval_binding is None
