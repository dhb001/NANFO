"""Lifetime exclusion for the explicit OVS autonomous driver composition."""

import fcntl
import os
import stat
from pathlib import Path


class IsolatedLabOwnership:
    def __init__(self, lab, resource_id, *, results_directory, manual_enabled, experiment_enabled):
        if manual_enabled or experiment_enabled or lab.mailbox is not None or lab.stopping:
            raise ValueError("autonomous_lab_requires_exclusive_control")
        directory = Path(results_directory)
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
            raise ValueError("dedicated_lab_results_required")
        # Same lock inode as legacy manual receiver, held throughout autonomous life.
        # Parent provisioning owns directory ancestry; leaf and inode checks reject swaps.
        fd = os.open(directory, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if os.path.lexists(directory / ".journal.json"):
                raise ValueError("manual_journal_requires_owned_reconciliation")
            self.fd = os.open(".executor.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                info = os.fstat(self.fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("invalid_lab_exclusion_inode")
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                os.close(self.fd)
                raise
        finally:
            os.close(fd)
        self.lab, self.resource_id, self.run_id = lab, resource_id, str(lab.runId)

    def check(self, resource_id, run_id):
        return (self.fd is not None and resource_id == self.resource_id and str(run_id) == self.run_id
                and str(self.lab.runId) == self.run_id and self.lab.mailbox is None)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
