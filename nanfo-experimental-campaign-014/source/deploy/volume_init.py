"""Fresh-only volume permissions and per-role secret staging. No recursive chown."""

import os
import stat
from pathlib import Path

from deploy.entrypoint import SECRETS


def main():
    for name in (
        "reports",
        "network_assets",
        "telemetry_archive",
        "lab_output",
        "lab_commands",
        "lab_results",
        "runtime_secrets",
        "init_secrets",
    ):
        path = Path("/volumes") / name
        if any(path.iterdir()):
            raise ValueError("Refusing to initialize a nonempty volume")
        os.chown(path, 10001, 10001)
        os.chmod(path, 0o700)
    names = {
        *SECRETS.values(),
        "postgres_admin_password",
        "postgres_owner_password",
        "bootstrap_password",
    }
    if {path.name for path in Path("/source-secrets").iterdir()} != names:
        raise ValueError("Source secrets must match the deployment allowlist")
    for name in sorted(names):
        source = Path("/source-secrets") / name
        info = source.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_size > 4096
        ):
            raise ValueError("Invalid source secret permissions")
        targets = ["init_secrets"]
        if source.name in SECRETS.values():
            targets.append("runtime_secrets")
        for target in targets:
            path = Path("/volumes") / target / source.name
            with path.open("xb") as stream:
                stream.write(source.read_bytes())
            os.chown(path, 10001, 10001)
            os.chmod(path, 0o400)


if __name__ == "__main__":
    main()
