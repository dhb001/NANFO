"""ADR020 conservative retention. Dry-run by default; never age-delete evidence.

Report cleanup requires stopped application owners and a verified encrypted backup
from the same project. Raw telemetry remains assessment-only until every evidence
owner supplies a reference/pin contract. No audits, histories, streams or DLQs are
deleted or trimmed. Run through the same explicit project/env/Compose interface as
backup_restore.py. This tool does not automatically stop or resume services.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from deploy.backup_restore import (
        Deployment,
        OperationError,
        add_deployment_arguments,
        load_manifest,
        protected_file,
    )
except ModuleNotFoundError:
    from backup_restore import (
        Deployment,
        OperationError,
        add_deployment_arguments,
        load_manifest,
        protected_file,
    )


async def owner_cleanup(*, apply, grace_seconds, batch_size, telemetry_days=30):
    from app.db.postgres import AsyncSessionLocal
    from app.modules.report.operations import ReportOperationsService
    from app.modules.telemetry.operations import retention_assessment
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        await db.execute(text("SET LOCAL statement_timeout = '30s'"))
        telemetry = await retention_assessment(
            db, days=telemetry_days, batch_size=batch_size
        )
        reports = await ReportOperationsService(db).cleanup(
            apply=apply, grace_seconds=grace_seconds, batch_size=batch_size
        )
        return {"reports": reports, "telemetry": telemetry}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_deployment_arguments(parser)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup-manifest",
        type=Path,
        help="Authenticated manifest.json from a completed backup less than 24h old",
    )
    parser.add_argument("--encryption-key-file", type=Path)
    parser.add_argument("--grace-hours", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--telemetry-days",
        type=int,
        default=30,
        help="Assessment policy only, deletion blocked without pin contracts",
    )
    args = parser.parse_args()
    try:
        if (
            not 24 <= args.grace_hours <= 87600
            or not 1 <= args.batch_size <= 1000
            or not 1 <= args.telemetry_days <= 3650
        ):
            raise OperationError("Retention policy outside allowed bounds.")
        deployment = Deployment(args.project, args.compose_file, args.env_file)
        deployment.assert_stopped(stores_allowed=True)
        deployment.maintenance("checkpoint")
        if args.apply:
            if (
                args.backup_manifest is None
                or args.encryption_key_file is None
                or args.backup_manifest.name != "manifest.json"
            ):
                raise OperationError(
                    "Apply requires --backup-manifest and --encryption-key-file."
                )
            with protected_file(args.encryption_key_file, size=32) as source:
                key = source.read()
            manifest = load_manifest(args.backup_manifest.parent, key)
            age = datetime.now(UTC) - datetime.fromisoformat(manifest["created_at"])
            if manifest["project"] != args.project or not timedelta(
                0
            ) <= age <= timedelta(hours=24):
                raise OperationError(
                    "Apply requires a same-project backup less than 24h old."
                )
        code = (
            "import asyncio,json; from deploy.retention import owner_cleanup; "
            f"print(json.dumps(asyncio.run(owner_cleanup(apply={args.apply!r},"
            f"grace_seconds={args.grace_hours * 3600},batch_size={args.batch_size},telemetry_days={args.telemetry_days}))))"
        )
        mounts = deployment.config["services"]["api"].get("volumes", [])
        reports = [
            mount
            for mount in mounts
            if mount.get("target") == "/var/lib/nanfo/reports"
            and mount.get("type") == "volume"
        ]
        if len(reports) != 1:
            raise OperationError("Expected one owned report volume.")
        report_volume = deployment.volume_name(reports[0]["source"])
        result = json.loads(
            deployment.compose(
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--volume",
                f"{report_volume}:/var/lib/nanfo/reports",
                "api",
                "python",
                "-c",
                code,
            )
        )
        print(
            json.dumps(
                {
                    **result,
                    "streams": "preserved",
                    "audits_histories_models": "preserved",
                },
                sort_keys=True,
            )
        )
    except (OperationError, OSError, ValueError, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "Retention preconditions failed; no automatic service resume",
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
