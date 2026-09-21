"""Attach to explicitly handed-off existing namespaces; never launches a lab.

PID start time and netns inode are bound before opening namespace descriptors.
nsenter gets the pinned descriptor, not a mutable PID path. The owner must retain
processes and stop old controllers before installing the protected binding.
"""

import fcntl
import json
import os
import subprocess
from pathlib import Path

from emulation.ospf import OSPFNetwork


def process_identity(pid):
    text = Path(f"/proc/{pid}/stat").read_text()
    # comm can contain spaces and ')'; field22 follows the final ')' and19 fields.
    start = int(text[text.rfind(")") + 2:].split()[19])
    return start, os.stat(f"/proc/{pid}/ns/net").st_ino


class AttachedFRRNetwork(OSPFNetwork):
    def __init__(self, binding, *, lock_directory):
        super().__init__()
        self.binding, self.fds, self.owner_fd = binding, {}, None
        directory = Path(lock_directory)
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
            raise ValueError("frr_exclusive_lock_directory_required")
        try:
            self.owner_fd = os.open(directory / ".autonomous-frr.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            fcntl.flock(self.owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for node, identity in binding.namespaces.items():
                expected = identity.start_ticks, identity.netns_inode
                if process_identity(identity.pid) != expected:
                    raise ValueError("frr_namespace_identity_changed")
                fd = os.open(f"/proc/{identity.pid}/ns/net", os.O_RDONLY)
                self.fds[node] = fd
                if os.fstat(fd).st_ino != identity.netns_inode or process_identity(identity.pid) != expected:
                    raise ValueError("frr_namespace_identity_changed")
        except BaseException:
            self.close()
            raise

    def ownership(self, resource_id, run_id):
        if self.owner_fd is None or resource_id != self.binding.resource_id or str(run_id) != self.binding.run_id:
            return False
        try:
            return all(process_identity(v.pid) == (v.start_ticks, v.netns_inode)
                       and os.fstat(self.fds[k]).st_ino == v.netns_inode for k, v in self.binding.namespaces.items())
        except OSError:
            return False

    def command(self, name, args, timeout=5, *, final_checkpoint=None):
        if not self.ownership(self.binding.resource_id, self.binding.run_id):
            raise ValueError("frr_namespace_ownership_lost")
        if name not in self.fds or not args or args[0] not in {"ip", "tc", "nft", "ping"}:
            raise ValueError("frr_command_not_allowed")
        # Only driver code supplies args; no shell and no wire-level arbitrary CLI.
        fd = self.fds[name]
        command = ["nsenter", f"--net=/proc/self/fd/{fd}", "--", *args]
        if final_checkpoint is not None:
            # PID/start-time/netns reads above can block too. No read, binding lookup
            # or another namespace sweep may intervene between this and process I/O.
            final_checkpoint()
        result = subprocess.run(command,
            pass_fds=(fd,), capture_output=True, timeout=timeout, check=False)
        if result.returncode or len(result.stdout) > 2 * 1024**2 or len(result.stderr) > 65536:
            raise ValueError("frr_device_command_failed")
        return result.stdout.decode("utf-8")

    def mutate(self, name, args, checkpoint, timeout=5):
        if (len(args) < 3 or args[0] != "ip" or args[1] not in {"route", "rule"}
                or args[2] not in {"add", "del"}):
            raise ValueError("frr_mutation_not_allowed")
        return self.command(name, args, timeout, final_checkpoint=checkpoint)

    def close(self):
        for fd in self.fds.values():
            os.close(fd)
        self.fds.clear()
        if self.owner_fd is not None:
            os.close(self.owner_fd)
            self.owner_fd = None

    def native_inventory(self):
        return {node: json.loads(self.command(node, ["ip", "-j", "link", "show"])) for node in self.fds}
