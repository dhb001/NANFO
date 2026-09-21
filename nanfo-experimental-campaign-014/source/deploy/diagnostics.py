"""Credential-free ADR020 diagnostics; does not start, stop or repair services."""

import argparse
import json
import sys

try:
    from deploy.backup_restore import (
        Deployment,
        OperationError,
        add_deployment_arguments,
    )
except ModuleNotFoundError:
    from backup_restore import Deployment, OperationError, add_deployment_arguments


def diagnose(deployment):
    containers = deployment.containers()
    services = []
    for container in containers:
        name = (
            container.get("Config", {})
            .get("Labels", {})
            .get("com.docker.compose.service")
        )
        if name not in deployment.config["services"]:
            continue
        state = container.get("State", {})
        services.append(
            {
                "service": name,
                "running": state.get("Running", False),
                "health": state.get("Health", {}).get("Status", "not_configured"),
                "restart_count": container.get("RestartCount", 0),
                "image_id": container.get("Image"),
            }
        )
    runtime = {"status": "unavailable"}
    if any(service["service"] == "api" and service["running"] for service in services):
        try:
            output = deployment.compose(
                "exec",
                "-T",
                "api",
                "python",
                "/opt/nanfo/deploy/entrypoint.py",
                "python",
                "/opt/nanfo/deploy/maintenance.py",
                "diagnose",
            )
            runtime = json.loads(output)
        except (OperationError, ValueError):
            pass
    return {
        "project": deployment.project,
        "services": services,
        "runtime": runtime,
        "telemetry_retention": "deletion_blocked_without_evidence_pin_contract",
        "optional_capabilities": "See runtime readiness; not inferred from container state",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_deployment_arguments(parser)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                diagnose(Deployment(args.project, args.compose_file, args.env_file)),
                sort_keys=True,
            )
        )
    except (OperationError, OSError, ValueError, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "Scoped deployment diagnostics failed; output suppressed",
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
