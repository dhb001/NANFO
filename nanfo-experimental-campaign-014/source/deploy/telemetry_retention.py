"""One finite operator invocation of Telemetry's CLI; no implicit age policy."""

import asyncio
import json
import os


def main():
    from app.core.config import get_settings
    from scripts.telemetry_retention import parser, run

    args = parser().parse_args()
    # Credentials arrive through the existing deployment secret entrypoint.
    # No DSN argument or separate privileged retention database role is needed.
    try:
        os.environ["TELEMETRY_RETENTION_DSN"] = get_settings().POSTGRES_DSN
        if not 1 <= args.timeout_seconds <= 300:
            raise ValueError("Invalid timeout")
        if args.operation in {"apply", "restore"}:
            if args.archive_root not in (None, "/var/lib/nanfo/telemetry-archive"):
                raise ValueError("Use the protected deployment archive")
            args.archive_root = "/var/lib/nanfo/telemetry-archive"
        print(json.dumps(asyncio.run(run(args)), sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001 - driver errors may contain credentials
        print(json.dumps({"status": "refused", "reason": "retention_scope_bounds_or_storage"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
