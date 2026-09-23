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
    settings = Settings(
        _env_file=None, APP_ENV=environment, EXECUTION_MODE="production",
        POSTGRES_PASSWORD="", REDIS_PASSWORD="line\nreturn\rtab\t", JWT_SECRET_KEY="test",
    )
    assert settings.POSTGRES_PASSWORD == ""
    assert settings.JWT_SECRET_KEY == "test"


def test_custom_production_credentials_preserved_exactly():
    settings = Settings(_env_file=None, APP_ENV="production", **SECRETS)
    for name, value in SECRETS.items():
        assert getattr(settings, name) == value
        assert value not in repr(settings)


def test_jwt_requires_32_characters_independent_of_store_minimum():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, APP_ENV="production", **{**SECRETS, "JWT_SECRET_KEY": "j" * 31})
