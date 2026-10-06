"""ADR021 bounded read-only SNMP collector. Dry-run is entirely offline."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.modules.telemetry.snmp import MeasuredSNMPAdapter
from app.modules.telemetry.snmp_config import SNMPBinding, SNMPCredentials, SNMPError, load_protected_json
from app.modules.telemetry.snmp_transport import NetSNMPTransport, requested_oids


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--binding", type=Path, required=True, help="Operator-owned 0600 binding JSON")
    result.add_argument("--credentials", type=Path, required=True, help="Secret-manager provisioned 0600 JSON")
    modes = result.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true", help="Validate files/tooling only; no network or DB I/O")
    modes.add_argument("--diagnostic", action="store_true", help="Authorized real GETs, print samples without publication")
    modes.add_argument("--publish", action="store_true", help="Authorized GETs and TelemetryIngestionService publication")
    result.add_argument("--samples", type=int, default=2, help="Bounded cycles (1..100), first cycle establishes baseline")
    result.add_argument("--interval", type=float, default=10.0, help="Seconds between cycles (1..300)")
    return result


async def run(args: argparse.Namespace) -> None:
    if not 1 <= args.samples <= 100 or not 1 <= args.interval <= 300:
        raise SNMPError("invalid_collection_limits")
    binding = load_protected_json(args.binding, SNMPBinding)
    load_protected_json(args.credentials, SNMPCredentials)
    transport = NetSNMPTransport(credentials_path=args.credentials)
    transport.check_available()
    if args.dry_run:
        print(json.dumps({"status": "offline_validated", "transport": "net-snmp/snmpget",
                          "security": "SNMPv3/authPriv", "device_id": str(binding.device_id),
                          "requests_per_cycle": len(binding.interfaces), "scope_checked": False,
                          "oids": [requested_oids(interface) for interface in binding.interfaces]}))
        return
    from redis.asyncio import Redis

    from app.core.config import get_settings
    from app.db.postgres import AsyncSessionLocal
    from app.modules.telemetry.service import TelemetryIngestionService
    from app.modules.telemetry.snmp_ownership import SNMPOwnerBoundary

    settings = get_settings()
    if settings.EXECUTION_MODE != binding.execution_mode:
        raise SNMPError("execution_mode_mismatch")
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        owner = SNMPOwnerBoundary(binding_path=args.binding, session_factory=AsyncSessionLocal, redis=redis)
        adapter = MeasuredSNMPAdapter(binding=binding, transport=transport, authorize=owner.authorize)
        ingestion = TelemetryIngestionService(redis)
        for index in range(args.samples):
            owner.invalidate()  # full owner authorization once per cycle (batch)
            if args.publish:
                count = await adapter.collect_and_publish(ingestion)
                print(json.dumps({"status": "published", "cycle": index + 1, "sample_count": count}))
            else:
                samples = await adapter.poll()
                print(json.dumps({"status": "diagnostic_only", "cycle": index + 1, "samples": samples}))
                await adapter.acknowledge_batch(samples)
            if index + 1 < args.samples:
                await asyncio.sleep(args.interval)
    finally:
        await redis.aclose()


def main() -> int:
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
        return 0
    except SNMPError as exc:
        print(json.dumps({"status": "unavailable", "reason": str(exc)}))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted"}))
        return 130
    except Exception:
        # Never print raw exceptions: driver, settings and DB errors can contain secrets.
        print(json.dumps({"status": "unavailable", "reason": "collector_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
