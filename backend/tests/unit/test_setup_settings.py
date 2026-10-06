"""ADR027 production secret policy preserves development and URI fixtures."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


SECRETS = {
    "POSTGRES_PASSWORD": "P7@/+#%: a-valid-custom-password",
    "NEO4J_PASSWORD": "N9@/+#%: a-valid-custom-password",
    "REDIS_PASSWORD": "R3@/+#%: a-valid-custom-password",
    "JWT_SECRET_KEY": "J5@/+#%: a-valid-custom-signing-key-over-32",
}


@pytest.mark.parametrize("environment", ["production", " PROD ", "staging", "custom-deployment"])
@pytest.mark.parametrize("name", SECRETS)
@pytest.mark.parametrize("unsafe", [
    "", " " * 40, "CHANGE_ME", "change-me-before-production-use-now",
    "nanfo_dev_secret", "nanfo_test", "short", "a-valid-length-but-control\nsecret!",
    "test-secret-key-32-chars-minimum!",
])
def test_deployed_secrets_fail_without_echo(environment, name, unsafe):
    values = {**SECRETS, name: unsafe}
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, APP_ENV=environment, **values)
    message = str(error.value)
    assert name in message and "input_value=" not in message
    assert not any(secret in message for secret in SECRETS.values())
    if unsafe.strip():
        assert unsafe not in message


@pytest.mark.parametrize("environment", ["development", "dev", "test", "testing"])
def test_test_fixtures_and_execution_mode_remain_supported(environment):
    # Store fixtures stay legal locally; only `test` may use a weak JWT key (ADR-028).
    jwt_key = "test" if environment == "test" else SECRETS["JWT_SECRET_KEY"]
    settings = Settings(
        _env_file=None, APP_ENV=environment, EXECUTION_MODE="production",
        POSTGRES_PASSWORD="", REDIS_PASSWORD="line\nreturn\rtab\t", JWT_SECRET_KEY=jwt_key,
    )
    assert settings.POSTGRES_PASSWORD == ""
    assert settings.JWT_SECRET_KEY == jwt_key


@pytest.mark.parametrize("environment", ["development", "dev", "testing", "staging", "production"])
@pytest.mark.parametrize("weak", ["test", "j" * 64, "ab" * 32, "change-me-please-32-bytes-long-key!",
                                  "test-secret-key-32-chars-minimum!"])
def test_jwt_key_checks_apply_everywhere_except_test(environment, weak):
    values = {**SECRETS, "JWT_SECRET_KEY": weak}
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, APP_ENV=environment, **values)
    assert "JWT_SECRET_KEY" in str(error.value) and weak not in str(error.value)


@pytest.mark.parametrize("environment", ["test", "development", "production"])
@pytest.mark.parametrize("empty", ["", "   "])
def test_empty_jwt_key_is_never_accepted(environment, empty):
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, APP_ENV=environment, **{**SECRETS, "JWT_SECRET_KEY": empty})


def test_app_env_defaults_to_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None, **SECRETS)
    assert settings.APP_ENV == "production" and not settings.is_local_environment
    assert settings.docs_enabled is False
    with pytest.raises(ValidationError):
        Settings(_env_file=None, JWT_SECRET_KEY=SECRETS["JWT_SECRET_KEY"])  # conftest fixture passwords


def test_worker_role_needs_no_signing_key_but_api_does():
    worker = Settings(_env_file=None, APP_ENV="production", NANFO_SERVICE_ROLE="worker",
                      **{**SECRETS, "JWT_SECRET_KEY": None})
    assert worker.JWT_SECRET_KEY is None and worker.jwt_verification_keys == ()
    with pytest.raises(ValidationError, match="NANFO_SERVICE_ROLE"):
        Settings(_env_file=None, APP_ENV="production", **{**SECRETS, "JWT_SECRET_KEY": None})
    # A worker that is given a key must still get a strong one.
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, APP_ENV="production", NANFO_SERVICE_ROLE="worker",
                 **{**SECRETS, "JWT_SECRET_KEY": "short"})


def test_previous_signing_keys_are_comma_separated_verify_only_and_checked(monkeypatch):
    previous = "P1@/+#%: an-older-signing-key-for-rotation"
    monkeypatch.setenv("JWT_PREVIOUS_SECRET_KEYS", f" {previous} , {SECRETS['JWT_SECRET_KEY']} ")
    settings = Settings(_env_file=None, APP_ENV="production", **SECRETS)
    assert settings.JWT_PREVIOUS_SECRET_KEYS == [previous, SECRETS["JWT_SECRET_KEY"]]
    assert settings.jwt_verification_keys == (SECRETS["JWT_SECRET_KEY"], previous)
    assert previous not in repr(settings)
    monkeypatch.setenv("JWT_PREVIOUS_SECRET_KEYS", "weak")
    with pytest.raises(ValidationError, match="JWT_PREVIOUS_SECRET_KEYS"):
        Settings(_env_file=None, APP_ENV="production", **SECRETS)


@pytest.mark.parametrize("override", [
    {"JWT_ALGORITHM": "none"}, {"JWT_ALGORITHM": "RS256"}, {"JWT_ACCESS_TOKEN_EXPIRE_MINUTES": 0},
    {"JWT_ACCESS_TOKEN_EXPIRE_MINUTES": 1441}, {"JWT_REFRESH_TOKEN_EXPIRE_DAYS": 0},
    {"JWT_REFRESH_TOKEN_EXPIRE_DAYS": 91},
])
def test_jwt_algorithm_and_expiry_bounds(override):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, APP_ENV="production", **SECRETS, **override)


@pytest.mark.parametrize("origins", ["*", "http://a.example,*", "null", "http://a.example, NULL"])
def test_cors_wildcard_and_null_origins_rejected(origins):
    with pytest.raises(ValidationError, match="CORS_ALLOW_ORIGINS"):
        Settings(_env_file=None, APP_ENV="production", CORS_ALLOW_ORIGINS=origins, **SECRETS)


@pytest.mark.parametrize("environment,explicit,expected", [
    ("production", None, False), (" PROD ", None, False), ("staging", None, True),
    ("verification", None, True), ("development", None, True), ("test", None, True),
    ("production", True, True), ("development", False, False),
])
def test_api_docs_default_closed_in_production(environment, explicit, expected):
    values = {} if explicit is None else {"API_DOCS_ENABLED": explicit}
    assert Settings(_env_file=None, APP_ENV=environment, **SECRETS, **values).docs_enabled is expected


def test_event_replay_horizon_and_idle_transaction_bounds():
    settings = Settings(_env_file=None, APP_ENV="production", **SECRETS)
    # 20 deliveries x (60 s reclaim idle + 30 s handler timeout) = 1800 s <= 3600 s TTL.
    assert settings.EVENT_COMPLETION_TTL_SECONDS == 3600 and settings.EVENT_MAX_DELIVERIES == 20
    with pytest.raises(ValidationError, match="EVENT_COMPLETION_TTL_SECONDS"):
        Settings(_env_file=None, APP_ENV="production", EVENT_RECLAIM_IDLE_MS=600000, **SECRETS)
    with pytest.raises(ValidationError, match="DB_IDLE_IN_TRANSACTION_TIMEOUT_MS"):
        Settings(_env_file=None, APP_ENV="production", DB_IDLE_IN_TRANSACTION_TIMEOUT_MS=60000, **SECRETS)
    assert Settings(_env_file=None, APP_ENV="production", DB_IDLE_IN_TRANSACTION_TIMEOUT_MS=0,
                    **SECRETS).DB_IDLE_IN_TRANSACTION_TIMEOUT_MS == 0


def test_stable_consumer_name_default_and_validation(monkeypatch):
    import app.core.config as config

    monkeypatch.setattr(config.socket, "gethostname", lambda: "api host/7")
    settings = Settings(_env_file=None, APP_ENV="production", **SECRETS)
    assert settings.event_consumer_name == "api-api-host-7"
    worker = Settings(_env_file=None, APP_ENV="production", NANFO_SERVICE_ROLE="worker", **SECRETS)
    assert worker.event_consumer_name == "worker-api-host-7"
    assert Settings(_env_file=None, APP_ENV="production", EVENT_CONSUMER_NAME="api-1",
                    **SECRETS).event_consumer_name == "api-1"
    with pytest.raises(ValidationError, match="EVENT_CONSUMER_NAME"):
        Settings(_env_file=None, APP_ENV="production", EVENT_CONSUMER_NAME="bad name", **SECRETS)


def test_custom_production_credentials_preserved_exactly():
    settings = Settings(_env_file=None, APP_ENV="production", **SECRETS)
    for name, value in SECRETS.items():
        assert getattr(settings, name) == value
        assert value not in repr(settings)


def test_jwt_requires_32_characters_independent_of_store_minimum():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, APP_ENV="production", **{**SECRETS, "JWT_SECRET_KEY": "j" * 31})
