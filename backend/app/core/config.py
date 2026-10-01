"""NANFO Backend — Core application configuration.

All values are loaded from environment variables / .env file.
No secrets or operational values are hardcoded (security.md guardrail).
"""

import re
import socket
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

# Environments that may use local fixture credentials for the backing stores.
_LOCAL_ENVIRONMENTS = frozenset({"development", "dev", "test", "testing"})
_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})
# Environments in which the process watchdog is off unless explicitly enabled.
_TEST_ENVIRONMENTS = frozenset({"test", "testing"})
# The only environment in which JWT signing-key strength is not enforced (ADR-028).
_JWT_EXEMPT_ENVIRONMENT = "test"
_KNOWN_PLACEHOLDER_SECRETS = frozenset({
    "nanfo_dev_secret", "nanfo_test", "test_secret_key_32_chars_minimum!",
})
_CONSUMER_NAME = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def _normalized_environment(value: str) -> str:
    return value.strip().lower()


def _secret_problem(value: str, *, minimum_bytes: int, minimum_distinct: int = 0) -> bool:
    """True when a secret is empty, short, a placeholder, low-entropy or has controls."""
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return (
        not value.strip()
        or len(value.encode("utf-8")) < minimum_bytes
        or "change_me" in normalized
        or "changeme" in normalized
        or normalized in _KNOWN_PLACEHOLDER_SECRETS
        or len(set(value)) < minimum_distinct
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    # Application. Fail closed: deployments must opt into local/test behaviour.
    APP_ENV: str = "production"
    # Workers never issue or verify user tokens and therefore need no JWT key (C10).
    NANFO_SERVICE_ROLE: Literal["api", "worker"] = "api"
    EXECUTION_MODE: Literal["demo", "emulation", "production"] = "demo"
    LOG_LEVEL: str = "INFO"
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    # None: disabled in production (APP_ENV production/prod), enabled otherwise.
    API_DOCS_ENABLED: bool | None = None
    # Request body bounds (C2). Asset uploads are the only larger route.
    API_MAX_BODY_BYTES: int = Field(default=1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    API_MAX_ASSET_UPLOAD_BYTES: int = Field(default=12 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    # PUT .../spatial-scene replaces a whole scene (<= 10,000 objects): 8 MiB by default.
    API_MAX_SPATIAL_SCENE_BYTES: int = Field(default=8 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    # Readiness probe result reuse; bounded so /ready never serves stale health for long.
    API_READINESS_CACHE_SECONDS: float = Field(default=1.5, ge=0, le=2, allow_inf_nan=False)
    # Leader startup: bounded background topology backfill (never blocks readiness).
    # Collector + graph schema (15 + 10 s) stay below the distributed leader's
    # readiness deadline (lease TTL + fanout freshness, 30 + 5 s by default).
    API_STARTUP_BACKFILL_TIMEOUT_SECONDS: float = Field(default=300, gt=0, le=3600, allow_inf_nan=False)
    API_STARTUP_GRAPH_SCHEMA_TIMEOUT_SECONDS: float = Field(default=10, gt=0, le=120, allow_inf_nan=False)
    API_STARTUP_COLLECTOR_TIMEOUT_SECONDS: float = Field(default=15, gt=0, le=120, allow_inf_nan=False)
    # Lease loss: graceful SIGTERM first, then a hard exit if shutdown stalls.
    API_REALTIME_LEASE_LOSS_EXIT_SECONDS: float = Field(default=20, gt=0, le=120, allow_inf_nan=False)

    # PostgreSQL
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = Field(repr=False)
    POSTGRES_DB: str
    # Per process: API + six workers x (5 + 5) = 70 < PostgreSQL max_connections 100.
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=50)
    DB_POOL_TIMEOUT_SECONDS: float = Field(default=10, gt=0, le=120, allow_inf_nan=False)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60, le=86400)
    DB_CONNECT_TIMEOUT_SECONDS: float = Field(default=5, gt=0, le=60, allow_inf_nan=False)
    # 0 disables. Session advisory locks (fleet collector, autonomy execution) are
    # held outside transactions by short statements, so neither timeout can end them.
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=30000, ge=0, le=3600000)
    # Above every bounded worker iteration/lease (<= 600 s); only leaked transactions end.
    DB_IDLE_IN_TRANSACTION_TIMEOUT_MS: int = Field(default=900000, ge=0, le=86400000)
    DB_ECHO: bool = False

    # Neo4j
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str = Field(repr=False)
    NEO4J_CONNECTION_TIMEOUT_SECONDS: float = Field(default=5, gt=0, le=60, allow_inf_nan=False)
    NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS: float = Field(default=10, gt=0, le=120, allow_inf_nan=False)
    NEO4J_MAX_TRANSACTION_RETRY_TIME_SECONDS: float = Field(default=15, ge=0, le=120, allow_inf_nan=False)
    NEO4J_MAX_CONNECTION_POOL_SIZE: int = Field(default=50, ge=1, le=500)

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int = 6379
    # ACL user (C24). None/empty authenticates as Redis `default` (legacy requirepass).
    REDIS_USERNAME: str | None = None
    REDIS_PASSWORD: str = Field(repr=False)
    REDIS_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = Field(default=50, ge=4, le=1000)
    REDIS_STREAM_MAX_CONNECTIONS: int = Field(default=24, ge=4, le=1000)
    REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS: float = Field(default=2, gt=0, le=30, allow_inf_nan=False)
    # Must exceed the XREADGROUP BLOCK interval (2 s) used by domain consumers.
    REDIS_SOCKET_TIMEOUT_SECONDS: float = Field(default=5, gt=2, le=60, allow_inf_nan=False)
    REDIS_HEALTH_CHECK_INTERVAL_SECONDS: int = Field(default=30, ge=0, le=3600)
    REDIS_POOL_TIMEOUT_SECONDS: float = Field(default=2, gt=0, le=30, allow_inf_nan=False)

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
    # Replay horizon: an entry is redelivered at most EVENT_MAX_DELIVERIES times, each
    # >= EVENT_RECLAIM_IDLE_MS after the previous delivery and <= one handler timeout
    # long: 20 x (60 s + 30 s) = 1800 s. Markers live 2x that (validated below).
    EVENT_COMPLETION_TTL_SECONDS: int = Field(default=3600, ge=60, le=604800)
    EVENT_HANDLER_TIMEOUT_SECONDS: int = Field(default=30, ge=1, le=300)
    EVENT_MAX_DELIVERIES: int = Field(default=20, ge=1, le=1000)
    # Stable per instance; default "<role>-<hostname>". Restarts reuse one consumer.
    EVENT_CONSUMER_NAME: str = ""
    # 1 keeps strict per-stream ordering; >1 keeps order per network/device key only.
    EVENT_CONSUMER_CONCURRENCY: int = Field(default=1, ge=1, le=32)
    # Producer admission: refuse XADD when Redis memory reaches this share of maxmemory.
    EVENT_PUBLISH_MAX_MEMORY_RATIO: float = Field(default=0.90, gt=0, le=1, allow_inf_nan=False)

    # WebSocket admission and authorization caching (ADR-028 C1)
    WS_MAX_CONNECTIONS_PER_USER: int = Field(default=16, ge=1, le=1024)
    WS_SUBSCRIBE_TIMEOUT_SECONDS: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    WS_AUTH_CACHE_SECONDS: float = Field(default=15, ge=0, le=15, allow_inf_nan=False)
    WS_MAX_FRAME_BYTES: int = Field(default=65536, ge=1024, le=1048576)

    # Disabled for local commands; deployment supplies a private writable path.
    WORKER_HEARTBEAT_PATH: str = ""
    WORKER_ITERATION_TIMEOUT_SECONDS: float = Field(default=330, gt=0, le=600, allow_inf_nan=False)
    WORKER_HEARTBEAT_MAX_AGE_SECONDS: float = Field(default=360, gt=0, le=900, allow_inf_nan=False)

    # In-process event-loop watchdog (app.core.watchdog). Container healthchecks never
    # restart a hung process; a loop stalled longer than the timeout exits with code 70
    # so the restart policy replaces it. None: enabled except when APP_ENV is test/testing.
    WATCHDOG_ENABLED: bool | None = None
    WATCHDOG_TIMEOUT_SECONDS: float = Field(default=120.0, ge=10, le=3600, allow_inf_nan=False)
    # Loop-side heartbeat period and thread-side check period (both << timeout).
    WATCHDOG_HEARTBEAT_INTERVAL_SECONDS: float = Field(default=5.0, gt=0, le=60, allow_inf_nan=False)
    WATCHDOG_CHECK_INTERVAL_SECONDS: float = Field(default=5.0, gt=0, le=60, allow_inf_nan=False)

    # JWT — per Authentication.md §5 and §8, ADR-028 C10/C19
    JWT_SECRET_KEY: str | None = Field(default=None, repr=False)
    # Verify-only keys accepted after rotation; tokens are always signed with the current key.
    JWT_PREVIOUS_SECRET_KEYS: Annotated[list[str], NoDecode] = Field(default_factory=list, repr=False)
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, ge=1, le=1440)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30, ge=1, le=90)

    # Rate limiting — per Authentication.md §5
    RATE_LIMIT_LOGIN_MAX_ATTEMPTS: int = 5
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 60

    # Session lifecycle (C9): idle sessions expire without a refresh; a refresh token
    # rotated at most this many seconds ago is an idempotent retry (same issued pair).
    AUTH_SESSION_IDLE_TIMEOUT_SECONDS: int = Field(default=43200, ge=300, le=90 * 86400)
    # Bounded low: the grace window is also a replay window for a copied refresh token.
    AUTH_REFRESH_GRACE_SECONDS: int = Field(default=20, ge=1, le=60)

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
    # plugin.failed events for rejected installs: one per (actor, key, code) per window
    # and at most PLUGIN_FAILED_EVENT_MAX_PER_ACTOR per actor per window.
    PLUGIN_FAILED_EVENT_WINDOW_SECONDS: int = Field(default=60, ge=1, le=86400)
    PLUGIN_FAILED_EVENT_MAX_PER_ACTOR: int = Field(default=10, ge=1, le=10000)

    # Reporting artifact lifecycle baseline
    REPORTS_ARTIFACT_BUCKET: str = "nanfo-reports"
    REPORTS_STORAGE_PATH: str = "/var/lib/nanfo/reports"
    REPORTS_MAX_BYTES: int = Field(default=8388608, ge=1024, le=16777216)
    REPORTS_MIN_FREE_BYTES: int = Field(default=67108864, ge=1048576, le=1099511627776)
    REPORTS_LEASE_SECONDS: int = Field(default=120, ge=30, le=300)
    # Claims without committed progress; exceeding it is terminal failed/attempts_exhausted (C20).
    REPORTS_MAX_CLAIM_ATTEMPTS: int = Field(default=5, ge=1, le=100)
    # Generated-report expiry in days; 0 keeps reports forever (opt-in retention).
    REPORTS_RETENTION_DAYS: int = Field(default=0, ge=0, le=36500)
    # Per-organisation stored-report budget in addition to the global reserve (C26).
    REPORTS_MAX_BYTES_PER_ORG: int = Field(default=512 * 1024 * 1024, ge=1048576, le=1099511627776)
    # Unreferenced attempt files older than this are removed by report maintenance.
    REPORTS_ORPHAN_GRACE_SECONDS: int = Field(default=86400, ge=3600, le=3650 * 86400)
    REPORTS_MAINTENANCE_INTERVAL_SECONDS: float = Field(default=3600.0, ge=60, le=86400, allow_inf_nan=False)

    # Workflow governance (constitution §2, C3/C18/C20)
    # Four-eyes rule: the approving (executing) user must differ from the requester.
    INTENT_REQUIRE_DISTINCT_APPROVER: bool = True
    SIMULATION_MAX_CLAIM_ATTEMPTS: int = Field(default=5, ge=1, le=100)
    # Queued + running modeled simulations per workspace before 429 SIMULATION_QUOTA_EXCEEDED.
    SIMULATION_MAX_ACTIVE_PER_WORKSPACE: int = Field(default=8, ge=1, le=1000)
    # Server policy floors: execution evidence limits may be stricter, never weaker.
    SIMULATION_POLICY_MAX_LOSS_PCT: float = Field(default=1.0, ge=0, le=100, allow_inf_nan=False)
    SIMULATION_POLICY_MAX_LATENCY_MS: float = Field(default=1000.0, gt=0, le=600000, allow_inf_nan=False)
    SIMULATION_POLICY_MIN_THROUGHPUT_MBPS: float = Field(default=0.0, ge=0, le=1000000, allow_inf_nan=False)

    # Autonomy governance (C25). Two-person switch to autonomous; STOP stays available
    # to read-only members; clearing STOP always requires org Admin.
    AUTONOMY_REQUIRE_DISTINCT_APPROVER: bool = True
    AUTONOMY_STOP_ALLOW_READ_ONLY: bool = True
    # Decision rows older than this are pruned by the autonomy worker; 0 keeps them forever.
    AUTONOMY_DECISION_RETENTION_DAYS: int = Field(default=30, ge=0, le=36500)
    # C26 tenant fairness: concurrent frozen-model diagnostics per organisation (one slot lock each).
    AUTONOMY_MODEL_DIAGNOSTICS_MAX_PER_ORG: int = Field(default=2, ge=1, le=16)
    # Experimental lab surfaces (C17 allow_uncalibrated_confidence) are opt-in only.
    NANFO_EXPERIMENTAL_LAB_ENABLED: bool = False

    # Retention of *published* outbox rows and alert observations, in days, applied in
    # bounded batches by the owning worker. 0 disables deletion (keep forever); deleting
    # is the unsafe direction, so consumers must treat 0 as "retention off".
    NETWORK_OUTBOX_RETENTION_DAYS: int = Field(default=30, ge=0, le=36500)
    REPORT_OUTBOX_RETENTION_DAYS: int = Field(default=30, ge=0, le=36500)
    SIMULATION_OUTBOX_RETENTION_DAYS: int = Field(default=30, ge=0, le=36500)
    INTENT_OUTBOX_RETENTION_DAYS: int = Field(default=30, ge=0, le=36500)
    ALERT_OBSERVATION_RETENTION_DAYS: int = Field(default=30, ge=0, le=36500)
    # Alert observation purge: rows per batch, batches per run, minimum spacing of runs.
    ALERT_OBSERVATION_PURGE_BATCH_SIZE: int = Field(default=1000, ge=1, le=10000)
    ALERT_OBSERVATION_PURGE_MAX_BATCHES: int = Field(default=10, ge=1, le=1000)
    ALERT_OBSERVATION_PURGE_INTERVAL_SECONDS: int = Field(default=300, ge=30, le=86400)

    @field_validator("JWT_PREVIOUS_SECRET_KEYS", mode="before")
    @classmethod
    def split_previous_keys(cls, value):
        """Comma-separated environment value (C19); never JSON-decoded."""
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("CORS_ALLOW_ORIGINS")
    @classmethod
    def reject_wildcard_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if any(origin == "*" or origin.lower() == "null" for origin in origins):
            raise ValueError("CORS_ALLOW_ORIGINS must list explicit origins; '*' and 'null' are rejected")
        return value

    @field_validator("EVENT_CONSUMER_NAME")
    @classmethod
    def validate_consumer_name(cls, value: str) -> str:
        if value and not _CONSUMER_NAME.fullmatch(value):
            raise ValueError("EVENT_CONSUMER_NAME must be 1-128 characters of [A-Za-z0-9._:-]")
        return value

    @field_validator("REDIS_USERNAME")
    @classmethod
    def validate_redis_username(cls, value: str | None) -> str | None:
        """Empty means unset; an ACL user name never contains whitespace or controls (C24)."""
        if value is None or not value.strip():
            return None
        if len(value) > 128 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("REDIS_USERNAME must be 1-128 characters without whitespace or control characters")
        return value

    @model_validator(mode="after")
    def validate_watchdog_and_quotas(self):
        # Several missed heartbeats must fit inside the timeout, so scheduling jitter
        # or a slow (but progressing) loop never looks like a hang.
        if self.WATCHDOG_HEARTBEAT_INTERVAL_SECONDS * 3 > self.WATCHDOG_TIMEOUT_SECONDS:
            raise ValueError("WATCHDOG_TIMEOUT_SECONDS must be at least 3 x WATCHDOG_HEARTBEAT_INTERVAL_SECONDS")
        if self.WATCHDOG_CHECK_INTERVAL_SECONDS * 2 > self.WATCHDOG_TIMEOUT_SECONDS:
            raise ValueError("WATCHDOG_TIMEOUT_SECONDS must be at least 2 x WATCHDOG_CHECK_INTERVAL_SECONDS")
        if self.REPORTS_MAX_BYTES_PER_ORG < self.REPORTS_MAX_BYTES:
            raise ValueError("REPORTS_MAX_BYTES_PER_ORG must be at least REPORTS_MAX_BYTES")
        return self

    @model_validator(mode="after")
    def validate_deployed_credentials(self):
        # Execution mode also describes test fixtures/adapter selection. Only the
        # application environment determines whether development secrets are legal.
        environment = _normalized_environment(self.APP_ENV)
        if environment not in _LOCAL_ENVIRONMENTS:
            for name in ("POSTGRES_PASSWORD", "NEO4J_PASSWORD", "REDIS_PASSWORD"):
                if _secret_problem(getattr(self, name), minimum_bytes=16):
                    raise ValueError(f"{name} must be a non-placeholder secret of at least 16 characters")
        return self

    @model_validator(mode="after")
    def validate_signing_keys(self):
        """Every environment except `test` enforces JWT key strength; empty is never legal."""
        environment = _normalized_environment(self.APP_ENV)
        keys = [("JWT_SECRET_KEY", self.JWT_SECRET_KEY)]
        keys += [("JWT_PREVIOUS_SECRET_KEYS", key) for key in self.JWT_PREVIOUS_SECRET_KEYS]
        if self.JWT_SECRET_KEY is None:
            if self.NANFO_SERVICE_ROLE != "worker":
                raise ValueError("JWT_SECRET_KEY is required unless NANFO_SERVICE_ROLE=worker")
            keys = keys[1:]
        for name, value in keys:
            if value is None or not value.strip():
                raise ValueError(f"{name} must not be empty")
            if environment != _JWT_EXEMPT_ENVIRONMENT and _secret_problem(
                value, minimum_bytes=32, minimum_distinct=10,
            ):
                raise ValueError(
                    f"{name} must be a non-placeholder, high-entropy secret of at least 32 bytes"
                )
        return self

    @model_validator(mode="after")
    def validate_event_and_database_bounds(self):
        horizon = self.EVENT_MAX_DELIVERIES * (
            self.EVENT_RECLAIM_IDLE_MS / 1000 + self.EVENT_HANDLER_TIMEOUT_SECONDS
        )
        if self.EVENT_COMPLETION_TTL_SECONDS < horizon:
            raise ValueError(
                "EVENT_COMPLETION_TTL_SECONDS must cover EVENT_MAX_DELIVERIES x "
                "(EVENT_RECLAIM_IDLE_MS + EVENT_HANDLER_TIMEOUT_SECONDS)"
            )
        idle = self.DB_IDLE_IN_TRANSACTION_TIMEOUT_MS
        bounded = max(self.WORKER_ITERATION_TIMEOUT_SECONDS, self.EVENT_HANDLER_TIMEOUT_SECONDS) * 1000
        if idle and idle <= bounded:
            raise ValueError(
                "DB_IDLE_IN_TRANSACTION_TIMEOUT_MS must be 0 or exceed every bounded worker/handler timeout"
            )
        return self

    @property
    def is_local_environment(self) -> bool:
        return _normalized_environment(self.APP_ENV) in _LOCAL_ENVIRONMENTS

    @property
    def watchdog_enabled(self) -> bool:
        """Explicit WATCHDOG_ENABLED, else on everywhere except test environments."""
        if self.WATCHDOG_ENABLED is not None:
            return self.WATCHDOG_ENABLED
        return _normalized_environment(self.APP_ENV) not in _TEST_ENVIRONMENTS

    @property
    def docs_enabled(self) -> bool:
        """OpenAPI/Swagger routes: explicit setting, else everywhere except production."""
        if self.API_DOCS_ENABLED is not None:
            return self.API_DOCS_ENABLED
        return _normalized_environment(self.APP_ENV) not in _PRODUCTION_ENVIRONMENTS

    @property
    def event_consumer_name(self) -> str:
        """Stable per-instance consumer identity: explicit, else `<role>-<hostname>`."""
        if self.EVENT_CONSUMER_NAME:
            return self.EVENT_CONSUMER_NAME
        host = re.sub(r"[^A-Za-z0-9._:-]", "-", socket.gethostname() or "localhost")[:100] or "localhost"
        return f"{self.NANFO_SERVICE_ROLE}-{host}"

    @property
    def jwt_verification_keys(self) -> tuple[str, ...]:
        """Current key first, then verify-only previous keys (C19)."""
        current = (self.JWT_SECRET_KEY,) if self.JWT_SECRET_KEY else ()
        return current + tuple(key for key in self.JWT_PREVIOUS_SECRET_KEYS if key != self.JWT_SECRET_KEY)

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
        """Every client/worker URL; carries the ACL user when REDIS_USERNAME is set (C24)."""
        user = quote(self.REDIS_USERNAME, safe="") if self.REDIS_USERNAME else ""
        return f"redis://{user}:{quote(self.REDIS_PASSWORD, safe='')}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @computed_field  # type: ignore[misc]
    @property
    def CORS_ALLOW_ORIGINS_LIST(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]
