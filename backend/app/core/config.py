"""NANFO Backend — Core application configuration.

All values are loaded from environment variables / .env file.
No secrets or operational values are hardcoded (security.md guardrail).
"""

from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # PostgreSQL
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    # Neo4j
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str
    REDIS_DB: int = 0

    # JWT — per Authentication.md §5 and §8
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Rate limiting — per Authentication.md §5
    RATE_LIMIT_LOGIN_MAX_ATTEMPTS: int = 5
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 60

    # Runtime telemetry adapter
    TELEMETRY_RUNTIME_ADAPTER_MODE: str = "stub"
    TELEMETRY_RUNTIME_ADAPTER_SEEDED_SAMPLE_KEY: str = "nanfo-runtime"
    TELEMETRY_RUNTIME_ADAPTER_SEEDED_METRIC: str = "runtime_adapter_heartbeat"
    TELEMETRY_RUNTIME_ADAPTER_SEEDED_VALUE: float = 1.0
    TELEMETRY_RUNTIME_ADAPTER_SEEDED_UNIT: str = "count"
    TELEMETRY_RUNTIME_ADAPTER_SEEDED_SOURCE: str = "runtime_seeded"
    TELEMETRY_RUNTIME_ADAPTER_SNMP_TARGET: str = "127.0.0.1"
    TELEMETRY_RUNTIME_ADAPTER_SNMP_OID: str = "1.3.6.1.2.1.1.3.0"
    TELEMETRY_RUNTIME_ADAPTER_SNMP_SAMPLE_KEY: str = "nanfo-snmp-runtime"
    TELEMETRY_RUNTIME_ADAPTER_SNMP_METRIC: str = "runtime_adapter_snmp_poll_latency_ms"
    TELEMETRY_RUNTIME_ADAPTER_SNMP_VALUE: float = 1.0
    TELEMETRY_RUNTIME_ADAPTER_SNMP_UNIT: str = "ms"
    TELEMETRY_RUNTIME_ADAPTER_SNMP_SOURCE: str = "runtime_snmp"
    TELEMETRY_RUNTIME_ADAPTER_GRPC_ENDPOINT: str = "localhost:50051"
    TELEMETRY_RUNTIME_ADAPTER_GRPC_METHOD: str = "TelemetryService/Poll"
    TELEMETRY_RUNTIME_ADAPTER_GRPC_SAMPLE_KEY: str = "nanfo-grpc-runtime"
    TELEMETRY_RUNTIME_ADAPTER_GRPC_METRIC: str = "runtime_adapter_grpc_poll_latency_ms"
    TELEMETRY_RUNTIME_ADAPTER_GRPC_VALUE: float = 1.0
    TELEMETRY_RUNTIME_ADAPTER_GRPC_UNIT: str = "ms"
    TELEMETRY_RUNTIME_ADAPTER_GRPC_SOURCE: str = "runtime_grpc"

    @computed_field  # type: ignore[misc]
    @property
    def POSTGRES_DSN(self) -> str:
        """Async SQLAlchemy DSN using asyncpg driver."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[misc]
    @property
    def POSTGRES_SYNC_DSN(self) -> str:
        """Synchronous DSN for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[misc]
    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]
