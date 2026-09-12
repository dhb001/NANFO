"""NANFO Backend — Core application configuration.

All values are loaded from environment variables / .env file.
No secrets or operational values are hardcoded (security.md guardrail).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_ENV: str = "development"
    EXECUTION_MODE: Literal["demo", "emulation", "production"] = "demo"
    LOG_LEVEL: str = "INFO"
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

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

    # ADR-010: always-on single API process guard and bounded stream recovery.
    API_REALTIME_LEASE_TTL_SECONDS: int = Field(default=30, ge=3, le=300)
    EVENT_RECLAIM_IDLE_MS: int = Field(default=60000, ge=1000, le=3600000)
    EVENT_CONSUMER_BATCH_SIZE: int = Field(default=10, ge=1, le=100)
    EVENT_COMPLETION_TTL_SECONDS: int = Field(default=86400, ge=60, le=604800)
    EVENT_HANDLER_TIMEOUT_SECONDS: int = Field(default=30, ge=1, le=300)

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
    EMULATION_SNAPSHOT_PATH: str = ""
    EMULATION_BINDING_PATH: str = ""
    EMULATION_CONTROL_ENABLED: bool = False
    EMULATION_COMMANDS_PATH: str = ""
    EMULATION_RESULTS_PATH: str = ""
    EMULATION_EXECUTION_TIMEOUT_SECONDS: int = Field(default=120, ge=10, le=300)
    EMULATION_EXECUTION_LEASE_SECONDS: int = Field(default=15, ge=5, le=60)
    EMULATION_EXECUTION_POLL_SECONDS: float = Field(default=1, gt=0, le=2, allow_inf_nan=False)
    EMULATION_CONTROL_MAX_BYTES: int = Field(default=1048576, ge=1024, le=4194304)
    EMULATION_SNAPSHOT_MAX_BYTES: int = Field(default=4194304, ge=1, le=16777216)
    EMULATION_SNAPSHOT_MAX_AGE_SECONDS: float = Field(default=30, gt=0, le=3600, allow_inf_nan=False)
    EMULATION_SNAPSHOT_FUTURE_SKEW_SECONDS: float = Field(default=2, ge=0, le=30, allow_inf_nan=False)
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

    # Plugin runtime safety baseline
    PLUGIN_PLATFORM_VERSION: str = "0.1.0"
    PLUGIN_TRUSTED_SIGNERS: str = "nanfo-labs,partner-signed"
    PLUGIN_SIGNATURE_PREFIX: str = "sig:"
    PLUGIN_SIGNATURE_MIN_LENGTH: int = 16
    PLUGIN_MAX_DEPENDENCY_COUNT: int = 25
    PLUGIN_ALLOWED_ISOLATION_MODES: str = "process,container"
    PLUGIN_ALLOWED_PERMISSIONS: str = "read:telemetry,read:topology,read:alerts"

    # Reporting artifact lifecycle baseline
    REPORTS_ARTIFACT_BUCKET: str = "nanfo-reports"
    REPORTS_STORAGE_PATH: str = "/var/lib/nanfo/reports"
    REPORTS_MAX_BYTES: int = Field(default=8388608, ge=1024, le=16777216)
    REPORTS_LEASE_SECONDS: int = Field(default=120, ge=30, le=300)

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

    @computed_field  # type: ignore[misc]
    @property
    def CORS_ALLOW_ORIGINS_LIST(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]
