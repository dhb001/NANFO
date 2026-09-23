"""NANFO Backend — Core application configuration.

All values are loaded from environment variables / .env file.
No secrets or operational values are hardcoded (security.md guardrail).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        hide_input_in_errors=True,
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
    POSTGRES_PASSWORD: str = Field(repr=False)
    POSTGRES_DB: str

    # Neo4j
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str = Field(repr=False)

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = Field(repr=False)
    REDIS_DB: int = 0

    # ADR010 singleton remains default; ADR023 explicitly enables multi-API serving.
    API_REALTIME_LEASE_TTL_SECONDS: int = Field(default=30, ge=3, le=300)
    API_REALTIME_DISTRIBUTED: bool = False
    API_REALTIME_FANOUT_MAX_ENTRIES: int = Field(default=4096, ge=16, le=65536)
    API_REALTIME_FANOUT_MAX_PAYLOAD_BYTES: int = Field(default=262144, ge=1024, le=1048576)
    API_REALTIME_FANOUT_BATCH_SIZE: int = Field(default=32, ge=1, le=100)
    API_REALTIME_FANOUT_DEDUP_ENTRIES: int = Field(default=4096, ge=16, le=65536)
    API_REALTIME_FANOUT_HEARTBEAT_SECONDS: float = Field(default=1, ge=0.1, le=10, allow_inf_nan=False)
    API_REALTIME_FANOUT_STALE_SECONDS: float = Field(default=5, ge=0.5, le=60, allow_inf_nan=False)
    API_REALTIME_FANOUT_IO_TIMEOUT_SECONDS: float = Field(default=2, ge=0.1, le=10, allow_inf_nan=False)
    API_REALTIME_FANOUT_RETRY_SECONDS: float = Field(default=1, ge=0.05, le=10, allow_inf_nan=False)
    API_REALTIME_FANOUT_SHUTDOWN_SECONDS: float = Field(default=5, ge=0.1, le=30, allow_inf_nan=False)
    API_REALTIME_COLLECTOR_WATCHDOG_SECONDS: float = Field(default=1, ge=0.1, le=10, allow_inf_nan=False)
    EVENT_RECLAIM_IDLE_MS: int = Field(default=60000, ge=1000, le=3600000)
    EVENT_CONSUMER_BATCH_SIZE: int = Field(default=10, ge=1, le=100)
    EVENT_COMPLETION_TTL_SECONDS: int = Field(default=86400, ge=60, le=604800)
    EVENT_HANDLER_TIMEOUT_SECONDS: int = Field(default=30, ge=1, le=300)

    # Disabled for local commands; deployment supplies a private writable path.
    WORKER_HEARTBEAT_PATH: str = ""
    WORKER_ITERATION_TIMEOUT_SECONDS: float = Field(default=330, gt=0, le=600, allow_inf_nan=False)
    WORKER_HEARTBEAT_MAX_AGE_SECONDS: float = Field(default=360, gt=0, le=900, allow_inf_nan=False)

    # JWT — per Authentication.md §5 and §8
    JWT_SECRET_KEY: str = Field(repr=False)
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Rate limiting — per Authentication.md §5
    RATE_LIMIT_LOGIN_MAX_ATTEMPTS: int = 5
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 60

    # Runtime telemetry adapter
    # Keep the existing unknown-selector fallback for legacy/demo callers.
    TELEMETRY_RUNTIME_ADAPTER_MODE: str = Field(
        default="stub", description="stub, seeded, snmp (demo), grpc (demo), emulation, measured_snmp"
    )
    # Independent fleet worker owns collection; API domain consumers still run.
    TELEMETRY_FLEET_ENABLED: bool = False
    TELEMETRY_MEASURED_SNMP_BINDING_PATH: Path | None = Field(default=None, repr=False)
    TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH: Path | None = Field(default=None, repr=False)
    TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS: float = Field(
        default=10.0, ge=1, le=300, allow_inf_nan=False
    )
    TELEMETRY_MEASURED_SNMP_POLL_TIMEOUT_SECONDS: float = Field(
        default=60.0, ge=1, le=300, allow_inf_nan=False
    )
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
    REPORTS_MIN_FREE_BYTES: int = Field(default=67108864, ge=1048576, le=1099511627776)
    REPORTS_LEASE_SECONDS: int = Field(default=120, ge=30, le=300)

    @model_validator(mode="after")
    def validate_deployed_credentials(self):
        # Execution mode also describes test fixtures/adapter selection. Only the
        # application environment determines whether development secrets are legal.
        if self.APP_ENV.strip().lower() in {"development", "dev", "test", "testing"}:
            return self
        for name in ("POSTGRES_PASSWORD", "NEO4J_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET_KEY"):
            value = getattr(self, name)
            normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
            minimum = 32 if name == "JWT_SECRET_KEY" else 16
            if (
                len(value) < minimum
                or not value.strip()
                or "change_me" in normalized
                or "changeme" in normalized
                or normalized in {"nanfo_dev_secret", "nanfo_test", "test_secret_key_32_chars_minimum!"}
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError(f"{name} must be a non-placeholder secret of at least {minimum} characters")
        return self

    def realtime_fanout_settings(self):
        from app.events.fanout_contract import FanoutSettings

        return FanoutSettings(
            max_entries=self.API_REALTIME_FANOUT_MAX_ENTRIES,
            max_payload_bytes=self.API_REALTIME_FANOUT_MAX_PAYLOAD_BYTES,
            batch_size=self.API_REALTIME_FANOUT_BATCH_SIZE,
            dedup_entries=self.API_REALTIME_FANOUT_DEDUP_ENTRIES,
            heartbeat_seconds=self.API_REALTIME_FANOUT_HEARTBEAT_SECONDS,
            stale_seconds=self.API_REALTIME_FANOUT_STALE_SECONDS,
            io_timeout_seconds=self.API_REALTIME_FANOUT_IO_TIMEOUT_SECONDS,
            retry_seconds=self.API_REALTIME_FANOUT_RETRY_SECONDS,
            shutdown_seconds=self.API_REALTIME_FANOUT_SHUTDOWN_SECONDS,
            lease_ttl_seconds=self.API_REALTIME_LEASE_TTL_SECONDS,
        )

    @model_validator(mode="after")
    def validate_realtime_and_collection(self):
        self.realtime_fanout_settings()
        if self.API_REALTIME_COLLECTOR_WATCHDOG_SECONDS >= self.API_REALTIME_FANOUT_STALE_SECONDS:
            raise ValueError("Collector watchdog interval must be below fanout freshness")
        if self.TELEMETRY_FLEET_ENABLED and self.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower() not in ("", "stub"):
            raise ValueError("Fleet collection requires the API adapter to be stub; configure fleet separately")
        return self

    @field_validator(
        "API_REALTIME_LEASE_TTL_SECONDS", "API_REALTIME_FANOUT_MAX_ENTRIES",
        "API_REALTIME_FANOUT_MAX_PAYLOAD_BYTES", "API_REALTIME_FANOUT_BATCH_SIZE",
        "API_REALTIME_FANOUT_DEDUP_ENTRIES", "API_REALTIME_FANOUT_HEARTBEAT_SECONDS",
        "API_REALTIME_FANOUT_STALE_SECONDS", "API_REALTIME_FANOUT_IO_TIMEOUT_SECONDS",
        "API_REALTIME_FANOUT_RETRY_SECONDS", "API_REALTIME_FANOUT_SHUTDOWN_SECONDS",
        "API_REALTIME_COLLECTOR_WATCHDOG_SECONDS", mode="before",
    )
    @classmethod
    def validate_realtime_numeric(cls, value):
        if isinstance(value, bool):
            raise ValueError("Realtime limits must be numeric, not boolean")
        return value

    @field_validator("TELEMETRY_MEASURED_SNMP_BINDING_PATH", "TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH")
    @classmethod
    def validate_measured_snmp_path(cls, value: Path | None) -> Path | None:
        if value is not None and (
            not value.is_absolute() or ".." in value.parts
            or any(ord(character) < 32 or ord(character) == 127 for character in str(value))
        ):
            raise ValueError("Measured SNMP paths must be absolute without traversal or control characters")
        return value

    @field_validator("TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS", "TELEMETRY_MEASURED_SNMP_POLL_TIMEOUT_SECONDS", mode="before")
    @classmethod
    def validate_measured_snmp_numeric(cls, value):
        if isinstance(value, bool):
            raise ValueError("Measured SNMP limits must be numeric, not boolean")
        return value

    @model_validator(mode="after")
    def validate_measured_snmp_selection(self):
        if self.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower() == "measured_snmp":
            if self.EXECUTION_MODE == "demo":
                raise ValueError("Measured SNMP requires production or emulation execution mode")
            if self.TELEMETRY_MEASURED_SNMP_BINDING_PATH is None or self.TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH is None:
                raise ValueError("Measured SNMP requires protected binding and credential paths")
            if self.TELEMETRY_MEASURED_SNMP_BINDING_PATH == self.TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH:
                raise ValueError("Measured SNMP binding and credential files must be distinct")
        return self

    @field_validator("POSTGRES_HOST", "REDIS_HOST")
    @classmethod
    def validate_dsn_host(cls, value: str) -> str:
        if not value or any(c in value for c in "@/#?\\\r\n\t "):
            raise ValueError("Invalid database host")
        return value

    @field_validator("POSTGRES_DB")
    @classmethod
    def validate_postgres_database(cls, value: str) -> str:
        """Allow literal names, including spaces/slashes/percent, but no URL query or controls."""
        if not value or "?" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Database name must be nonempty and contain no question mark or control characters")
        return value

    @computed_field(repr=False)  # type: ignore[misc]
    @property
    def POSTGRES_DSN(self) -> str:
        """Async SQLAlchemy DSN using asyncpg driver."""
        return URL.create(
            "postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        ).render_as_string(hide_password=False)

    @computed_field(repr=False)  # type: ignore[misc]
    @property
    def POSTGRES_SYNC_DSN(self) -> str:
        """Synchronous DSN for Alembic migrations."""
        return URL.create(
            "postgresql+psycopg2",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        ).render_as_string(hide_password=False)

    @computed_field(repr=False)  # type: ignore[misc]
    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{quote(self.REDIS_PASSWORD, safe='')}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @computed_field  # type: ignore[misc]
    @property
    def CORS_ALLOW_ORIGINS_LIST(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]
