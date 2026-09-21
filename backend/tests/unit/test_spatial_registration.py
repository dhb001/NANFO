"""Explicit asset registration rejects ambiguous or unbounded coordinate mappings."""

import math

import pytest
from pydantic import ValidationError

from app.modules.network.registration import AssetRegistration


def registration():
    return {
        "version": 1, "translation": {"x": 0, "y": 0, "z": 0},
        "rotation": {"x": 0, "y": math.pi, "z": 0}, "scale": {"x": 1, "y": 1, "z": 1},
        "target_units": "m", "target_up_axis": "y", "source": "operator-registration",
    }


def test_explicit_registration_roundtrip_and_boundaries():
    body = registration()
    body["scale"] = {"x": 0.000001, "y": 1_000_000, "z": 1}
    body["translation"] = {"x": -1_000_000, "y": 1_000_000, "z": 0}
    body["rotation"] = {"x": -math.tau, "y": math.tau, "z": 0}
    assert AssetRegistration.model_validate(body).model_dump(mode="json") == body


@pytest.mark.parametrize("field,value", [
    ("version", True), ("version", 1.0), ("version", "1"), ("version", 2),
    ("target_units", "ft"), ("target_up_axis", "z"), ("source", " "),
    ("source", "x" * 129), ("source", "survey\x00"),
])
def test_registration_metadata_is_explicit(field, value):
    body = registration()
    body[field] = value
    with pytest.raises(ValidationError):
        AssetRegistration.model_validate(body)


@pytest.mark.parametrize("field,value", [
    ("scale", 0), ("scale", -1), ("scale", 0.0000001), ("scale", 1_000_001),
    ("translation", 1_000_001), ("rotation", math.tau + 0.001),
])
def test_registration_vector_bounds(field, value):
    body = registration()
    body[field]["x"] = value
    with pytest.raises(ValidationError):
        AssetRegistration.model_validate(body)


@pytest.mark.parametrize("field", ["scale", "translation", "rotation"])
@pytest.mark.parametrize("value", [True, "1", math.inf, -math.inf, math.nan])
def test_all_registration_vectors_are_finite_and_noncoercing(field, value):
    body = registration()
    body[field]["z"] = value
    with pytest.raises(ValidationError):
        AssetRegistration.model_validate(body)


@pytest.mark.parametrize("field", list(registration()))
def test_registration_fields_have_no_inferred_defaults(field):
    body = registration()
    del body[field]
    with pytest.raises(ValidationError):
        AssetRegistration.model_validate(body)


@pytest.mark.parametrize("field", [None, "scale", "translation", "rotation"])
def test_registration_extra_fields_forbidden(field):
    body = registration()
    target = body if field is None else body[field]
    target["inferred"] = True
    with pytest.raises(ValidationError):
        AssetRegistration.model_validate(body)
