"""backend/.env.example documents every Settings field and is a valid dev source (ADR-028).

Drift in either direction fails: a new Settings field must be documented, and an
example key that is not a Settings field would make the generated backend/.env
unusable (Settings forbids extra inputs).
"""

import re
import secrets
from pathlib import Path

from app.core.config import Settings

EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
# `KEY=value` (active) or `# KEY=value` (documented but intentionally unset).
ASSIGNMENT = re.compile(r"^(?P<comment>#\s*)?(?P<key>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")
SECRETS = ("POSTGRES_PASSWORD", "NEO4J_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET_KEY")
# Settings fields intentionally absent from the example, each with its reason.
EXCLUDED = {
    "REPORTS_ARTIFACT_BUCKET": "dead setting: no code reads it; removal from Settings requested (config owner)",
}


def parse_example():
    active, documented = {}, []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = ASSIGNMENT.match(line.strip())
        if match:
            documented.append(match["key"])
            if not match["comment"]:
                active[match["key"]] = match["value"]
    return active, documented


def test_every_settings_field_is_documented_exactly_once():
    _, documented = parse_example()
    fields = set(Settings.model_fields)
    duplicates = sorted({key for key in documented if documented.count(key) > 1})
    assert not duplicates, f"documented more than once: {duplicates}"
    missing = sorted(fields - set(EXCLUDED) - set(documented))
    unknown = sorted(set(documented) - fields)
    assert not missing, f"Settings fields missing from backend/.env.example: {missing}"
    assert not unknown, f"backend/.env.example documents keys that are not Settings fields: {unknown}"


def test_exclusions_are_real_fields_and_not_documented():
    _, documented = parse_example()
    assert set(EXCLUDED) <= set(Settings.model_fields), "stale exclusion: field no longer exists"
    assert not set(EXCLUDED) & set(documented)
    assert all(len(reason) >= 16 for reason in EXCLUDED.values())


def test_asset_store_process_variables_listed_in_prose_match_asset_settings():
    # AssetSettings reads NETWORK_ASSET_* from the process environment only; an active
    # line in .env would be an unknown Settings input, so the example lists them as prose.
    from app.modules.network.asset_settings import AssetSettings

    prefix = AssetSettings.model_config["env_prefix"]
    expected = {prefix + name.upper() for name in AssetSettings.model_fields}
    text = EXAMPLE.read_text(encoding="utf-8")
    listed = set(re.findall(rf"\b{prefix}[A-Z0-9_]+\b", text))
    assert listed == expected
    _, documented = parse_example()
    assert not expected & set(documented), "asset store variables must not be assignments in .env.example"
    assert not expected & set(Settings.model_fields)


def test_example_is_a_development_template_with_blank_secrets():
    active, _ = parse_example()
    assert active["APP_ENV"] == "development"
    for name in SECRETS:
        assert active[name] == "", f"{name} must stay blank in the committed template"
    assert active["POSTGRES_HOST"] == active["REDIS_HOST"] == "127.0.0.1"


def test_filled_example_is_a_valid_settings_source(tmp_path, monkeypatch):
    # Only the file may supply values: remove harness/process overrides for every field.
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    text = EXAMPLE.read_text(encoding="utf-8")
    for name in SECRETS:
        text = re.sub(rf"(?m)^{name}=$", f"{name}={secrets.token_hex(32)}", text)
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    settings = Settings(_env_file=env_file)
    assert settings.APP_ENV == "development" and settings.is_local_environment
    assert settings.docs_enabled and settings.watchdog_enabled
    assert settings.REDIS_USERNAME == "nanfo"
    assert settings.JWT_PREVIOUS_SECRET_KEYS == []
    assert settings.TELEMETRY_MEASURED_SNMP_BINDING_PATH is None


def test_unfilled_example_cannot_start_an_api_process(tmp_path, monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        Settings(_env_file=env_file)
    except ValueError as exc:  # pydantic.ValidationError subclasses ValueError
        assert "JWT_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("blank template secrets must be rejected")
