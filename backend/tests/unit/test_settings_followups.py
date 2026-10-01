"""ADR-028 follow-up settings: every optionally read name is declared, typed and bounded.

Owners read several settings with ``getattr(settings, "NAME", default)`` (or small
helpers such as ``bounded_setting``/``_configured_seconds``) so their code works
before and after the platform declares the field. This test keeps that pattern
honest: every such name must exist on ``Settings`` and literal fallbacks must equal
the declared default, so behaviour never depends on which path supplied the value.
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BACKEND = Path(__file__).resolve().parents[2]
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_MISSING = object()
# A strong development key (the shared test key is a known placeholder outside APP_ENV=test).
_DEV_JWT = "Zq8#vL2@pN5$wR9!kT4%yB7^mC1&xF6*"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _settings_like(node: ast.AST) -> bool:
    source = ast.unparse(node).lower()
    return "settings" in source or "config" in source


def _literal(node: ast.AST | None, constants: dict[str, object] | None = None):
    if node is None:
        return _MISSING
    if isinstance(node, ast.Name):
        return (constants or {}).get(node.id, _MISSING)
    try:
        return ast.literal_eval(node)
    except (TypeError, ValueError, SyntaxError):
        return _MISSING


def _module_constants(tree: ast.Module) -> dict[str, object]:
    """Top-level ``NAME = <literal>`` bindings, so named fallbacks (``DEFAULT_X``) are compared too."""
    constants: dict[str, object] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets, value = statement.targets, statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets, value = [statement.target], statement.value
        else:
            continue
        literal = _literal(value)
        for target in targets:
            if isinstance(target, ast.Name) and literal is not _MISSING:
                constants[target.id] = literal
    return constants


def _source_reads(source: str, location: str, reads: dict[str, list[tuple[str, object]]]) -> None:
    tree = ast.parse(source, filename=location)
    constants = _module_constants(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = ast.unparse(node.func)
        names = [
            (index, arg.value) for index, arg in enumerate(node.args)
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _NAME.match(arg.value)
        ]
        site = f"{location}:{node.lineno}"
        if function == "getattr":
            if len(node.args) >= 2 and names and names[0][0] == 1 and _settings_like(node.args[0]):
                default = _literal(node.args[2], constants) if len(node.args) > 2 else _MISSING
                reads.setdefault(names[0][1], []).append((site, default))
        elif ("setting" in function.lower() or "configured" in function.lower()) and not function.startswith(
            ("os.", "environ"),
        ):
            for index, name in names:
                default = _literal(node.args[index + 1], constants) if len(node.args) > index + 1 else _MISSING
                reads.setdefault(name, []).append((site, default))


def optional_setting_reads() -> dict[str, list[tuple[str, object]]]:
    """``{NAME: [(location, literal default | _MISSING), ...]}`` for app/ and scripts/."""
    reads: dict[str, list[tuple[str, object]]] = {}
    for path in sorted([*(BACKEND / "app").rglob("*.py"), *(BACKEND / "scripts").rglob("*.py")]):
        _source_reads(path.read_text(encoding="utf-8"), str(path.relative_to(BACKEND)), reads)
    return reads


def test_scanner_discovers_known_optional_readers():
    reads = optional_setting_reads()
    # Guards the scanner itself: each reader style below must be recognised.
    for name in ("SIMULATION_MAX_CLAIM_ATTEMPTS",  # getattr(settings, ...)
                 "INTENT_REQUIRE_DISTINCT_APPROVER",  # getattr(get_settings(), ...)
                 "AUTH_REFRESH_GRACE_SECONDS",  # _configured_seconds(...)
                 "REPORTS_MAX_CLAIM_ATTEMPTS"):  # bounded_setting(self.settings, ...)
        assert name in reads, name


def test_scanner_resolves_module_level_named_fallbacks():
    reads: dict[str, list[tuple[str, object]]] = {}
    _source_reads(
        "LIMIT = 2\n"
        "WINDOW: float = 1.5\n"
        "COMPUTED = compute()\n"
        "def read(service, settings):\n"
        '    return (getattr(service.settings, "X_LIMIT", LIMIT), getattr(settings, "X_WINDOW", WINDOW),\n'
        '            getattr(settings, "X_COMPUTED", COMPUTED), getattr(settings, "X_LOCAL", local))\n',
        "sample.py", reads,
    )
    assert reads == {"X_LIMIT": [("sample.py:5", 2)], "X_WINDOW": [("sample.py:5", 1.5)],
                     "X_COMPUTED": [("sample.py:6", _MISSING)], "X_LOCAL": [("sample.py:6", _MISSING)]}


def test_every_optionally_read_setting_name_is_declared():
    declared = set(Settings.model_fields) | set(Settings.model_computed_fields)
    missing = {name: sites for name, sites in optional_setting_reads().items() if name not in declared}
    assert not missing, f"settings read via getattr but not declared on Settings: {missing}"


def test_literal_fallbacks_equal_declared_defaults():
    settings = _settings()
    mismatched = {}
    for name, sites in optional_setting_reads().items():
        for location, default in sites:
            # ``None`` fallbacks are defensive guards, not optional-setting defaults.
            if default is _MISSING or default is None:
                continue
            if getattr(settings, name) != default:
                mismatched[f"{location} {name}"] = (default, getattr(settings, name))
    assert not mismatched, mismatched


FOLLOWUP_DEFAULTS = {
    "INTENT_REQUIRE_DISTINCT_APPROVER": True,
    "SIMULATION_MAX_CLAIM_ATTEMPTS": 5,
    "SIMULATION_MAX_ACTIVE_PER_WORKSPACE": 8,
    "SIMULATION_POLICY_MAX_LOSS_PCT": 1.0,
    "SIMULATION_POLICY_MAX_LATENCY_MS": 1000.0,
    "SIMULATION_POLICY_MIN_THROUGHPUT_MBPS": 0.0,
    "PLUGIN_FAILED_EVENT_WINDOW_SECONDS": 60,
    "PLUGIN_FAILED_EVENT_MAX_PER_ACTOR": 10,
    "AUTH_SESSION_IDLE_TIMEOUT_SECONDS": 43200,
    "AUTH_REFRESH_GRACE_SECONDS": 20,
    "REPORTS_MAX_CLAIM_ATTEMPTS": 5,
    "REPORTS_RETENTION_DAYS": 0,
    "REPORTS_MAX_BYTES_PER_ORG": 512 * 1024 * 1024,
    "REPORTS_ORPHAN_GRACE_SECONDS": 86400,
    "REPORTS_MAINTENANCE_INTERVAL_SECONDS": 3600.0,
    "REPORT_OUTBOX_RETENTION_DAYS": 30,
    "NETWORK_OUTBOX_RETENTION_DAYS": 30,
    "SIMULATION_OUTBOX_RETENTION_DAYS": 30,
    "INTENT_OUTBOX_RETENTION_DAYS": 30,
    "ALERT_OBSERVATION_RETENTION_DAYS": 30,
    "ALERT_OBSERVATION_PURGE_BATCH_SIZE": 1000,
    "ALERT_OBSERVATION_PURGE_MAX_BATCHES": 10,
    "ALERT_OBSERVATION_PURGE_INTERVAL_SECONDS": 300,
    "AUTONOMY_REQUIRE_DISTINCT_APPROVER": True,
    "AUTONOMY_STOP_ALLOW_READ_ONLY": True,
    "AUTONOMY_DECISION_RETENTION_DAYS": 30,
    "AUTONOMY_MODEL_DIAGNOSTICS_MAX_PER_ORG": 2,
    "NANFO_EXPERIMENTAL_LAB_ENABLED": False,
    "REDIS_USERNAME": None,
    "WATCHDOG_ENABLED": None,
    "WATCHDOG_TIMEOUT_SECONDS": 120.0,
    "WATCHDOG_HEARTBEAT_INTERVAL_SECONDS": 5.0,
    "WATCHDOG_CHECK_INTERVAL_SECONDS": 5.0,
}


@pytest.mark.parametrize(("name", "expected"), sorted(FOLLOWUP_DEFAULTS.items()))
def test_followup_contract_names_and_defaults(name, expected, monkeypatch):
    monkeypatch.delenv(name, raising=False)
    assert name in Settings.model_fields
    value = getattr(_settings(), name)
    assert value == expected and type(value) is type(expected)


@pytest.mark.parametrize(("name", "value"), [
    ("SIMULATION_MAX_CLAIM_ATTEMPTS", 0), ("SIMULATION_MAX_CLAIM_ATTEMPTS", 101),
    ("SIMULATION_MAX_ACTIVE_PER_WORKSPACE", 0), ("SIMULATION_POLICY_MAX_LOSS_PCT", -0.1),
    ("SIMULATION_POLICY_MAX_LOSS_PCT", math.nan), ("SIMULATION_POLICY_MAX_LATENCY_MS", 0),
    ("SIMULATION_POLICY_MIN_THROUGHPUT_MBPS", math.inf), ("PLUGIN_FAILED_EVENT_WINDOW_SECONDS", 0),
    ("PLUGIN_FAILED_EVENT_MAX_PER_ACTOR", 0), ("AUTH_SESSION_IDLE_TIMEOUT_SECONDS", 299),
    ("AUTH_REFRESH_GRACE_SECONDS", 0), ("AUTH_REFRESH_GRACE_SECONDS", 61),
    ("REPORTS_MAX_CLAIM_ATTEMPTS", 0), ("REPORTS_RETENTION_DAYS", -1),
    ("REPORTS_MAX_BYTES_PER_ORG", 1024), ("REPORT_OUTBOX_RETENTION_DAYS", -1),
    ("NETWORK_OUTBOX_RETENTION_DAYS", 36501), ("SIMULATION_OUTBOX_RETENTION_DAYS", -1),
    ("INTENT_OUTBOX_RETENTION_DAYS", 36501), ("ALERT_OBSERVATION_RETENTION_DAYS", -1),
    ("AUTONOMY_DECISION_RETENTION_DAYS", -1), ("ALERT_OBSERVATION_PURGE_BATCH_SIZE", 0),
    ("ALERT_OBSERVATION_PURGE_MAX_BATCHES", 1001), ("ALERT_OBSERVATION_PURGE_INTERVAL_SECONDS", 29),
    ("AUTONOMY_MODEL_DIAGNOSTICS_MAX_PER_ORG", 0), ("AUTONOMY_MODEL_DIAGNOSTICS_MAX_PER_ORG", 17),
    ("WATCHDOG_TIMEOUT_SECONDS", 9),
    ("WATCHDOG_TIMEOUT_SECONDS", math.inf), ("WATCHDOG_HEARTBEAT_INTERVAL_SECONDS", 0),
])
def test_followup_settings_are_bounded(name, value):
    with pytest.raises(ValidationError):
        _settings(**{name: value})


@pytest.mark.parametrize("name", ["NETWORK_OUTBOX_RETENTION_DAYS", "REPORT_OUTBOX_RETENTION_DAYS",
                                  "SIMULATION_OUTBOX_RETENTION_DAYS", "INTENT_OUTBOX_RETENTION_DAYS",
                                  "ALERT_OBSERVATION_RETENTION_DAYS", "AUTONOMY_DECISION_RETENTION_DAYS",
                                  "REPORTS_RETENTION_DAYS"])
def test_zero_retention_is_the_documented_keep_forever_switch(name):
    # BE-Network's outbox (and report retention) read 0 as "retention off"; it must load.
    assert getattr(_settings(**{name: 0}), name) == 0
    assert getattr(_settings(**{name: 36500}), name) == 36500


def test_env_strings_are_parsed_to_typed_values(monkeypatch):
    monkeypatch.setenv("INTENT_REQUIRE_DISTINCT_APPROVER", "false")
    monkeypatch.setenv("SIMULATION_POLICY_MAX_LATENCY_MS", "250.5")
    monkeypatch.setenv("NANFO_EXPERIMENTAL_LAB_ENABLED", "1")
    monkeypatch.setenv("REPORTS_MAX_BYTES_PER_ORG", str(64 * 1024 * 1024))
    settings = _settings()
    assert settings.INTENT_REQUIRE_DISTINCT_APPROVER is False
    assert settings.SIMULATION_POLICY_MAX_LATENCY_MS == 250.5
    assert settings.NANFO_EXPERIMENTAL_LAB_ENABLED is True
    assert settings.REPORTS_MAX_BYTES_PER_ORG == 64 * 1024 * 1024


def test_per_org_report_budget_must_hold_one_maximum_report():
    with pytest.raises(ValidationError, match="REPORTS_MAX_BYTES_PER_ORG"):
        _settings(REPORTS_MAX_BYTES=16 * 1024 * 1024, REPORTS_MAX_BYTES_PER_ORG=8 * 1024 * 1024)
    assert _settings(REPORTS_MAX_BYTES=8 * 1024 * 1024, REPORTS_MAX_BYTES_PER_ORG=8 * 1024 * 1024)


@pytest.mark.parametrize(("heartbeat", "check", "timeout", "valid"), [
    (5, 5, 120, True), (10, 5, 30, True), (11, 5, 30, False), (5, 16, 30, False), (60, 60, 180, True),
])
def test_watchdog_intervals_must_fit_several_times_inside_the_timeout(heartbeat, check, timeout, valid):
    values = {"WATCHDOG_HEARTBEAT_INTERVAL_SECONDS": heartbeat, "WATCHDOG_CHECK_INTERVAL_SECONDS": check,
              "WATCHDOG_TIMEOUT_SECONDS": timeout}
    if valid:
        assert _settings(**values).WATCHDOG_TIMEOUT_SECONDS == timeout
    else:
        with pytest.raises(ValidationError, match="WATCHDOG_TIMEOUT_SECONDS"):
            _settings(**values)


@pytest.mark.parametrize(("environment", "explicit", "enabled"), [
    ("test", None, False), ("TESTING", None, False), ("development", None, True),
    ("production", None, True), ("test", True, True), ("production", False, False),
])
def test_watchdog_defaults_on_except_in_tests(environment, explicit, enabled, monkeypatch):
    monkeypatch.delenv("WATCHDOG_ENABLED", raising=False)
    overrides = {"APP_ENV": environment, "WATCHDOG_ENABLED": explicit}
    if environment.lower() not in {"test", "testing", "development"}:
        overrides.update(POSTGRES_PASSWORD="Pg-7f3a9c1e5b2d8f40", NEO4J_PASSWORD="Neo-4b8e2a6c9d1f7e30",
                         REDIS_PASSWORD="Rd-9c2e7a4f1b6d3e80")
    if environment.lower() not in {"test"}:
        overrides["JWT_SECRET_KEY"] = _DEV_JWT
    assert _settings(**overrides).watchdog_enabled is enabled


@pytest.mark.parametrize(("value", "expected"), [(None, None), ("", None), ("   ", None), ("nanfo", "nanfo"),
                                                 ("svc:api@x", "svc:api@x")])
def test_redis_username_normalisation(value, expected):
    assert _settings(REDIS_USERNAME=value).REDIS_USERNAME == expected


@pytest.mark.parametrize("value", ["two words", "tab\tname", "line\nbreak", "bell\x07", "x" * 129])
def test_redis_username_rejects_whitespace_and_controls(value):
    with pytest.raises(ValidationError) as error:
        _settings(REDIS_USERNAME=value)
    assert value not in str(error.value)  # hide_input_in_errors: never echo the value
