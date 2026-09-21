"""Host operator-only exact-container Docker exec transport; never imported by app."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from .experimental_lab_contract import (
        IMAGE,
        RESPONSE_LIMIT,
        Request,
        atomic_write,
        canonical,
        decode,
        load_policy,
        protected_read,
        require,
    )
except ImportError:
    from experimental_lab_contract import (
        IMAGE,
        RESPONSE_LIMIT,
        Request,
        atomic_write,
        canonical,
        decode,
        load_policy,
        protected_read,
        require,
    )


CLIENT = """import socket,sys
raw=sys.stdin.buffer.read(8193)
if len(raw)>8192: raise ValueError('request_too_large')
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(50)
 s.connect('/run/nanfo-experimental/receiver.sock')
 s.sendall(raw); s.shutdown(socket.SHUT_WR)
 result=bytearray()
 while len(result)<=2097152:
  part=s.recv(min(65536,2097153-len(result)))
  if not part: break
  result.extend(part)
 if len(result)>2097152: raise ValueError('response_too_large')
 sys.stdout.buffer.write(result)
"""


def teardown_owned_graph(policy):
    """Explicit last-resort operator release; not a normal restoration receipt.

    Container removal kills its cgroup, including orphan namespace keepers/FRR.
    Verify recorded host PIDs and namespace identities are absent afterwards.
    Never reattach a new graph or return RecoveryReceipt(status='restored').
    """
    container = policy["container_id"]
    result = subprocess.run(["docker", "inspect", "--format",
        '{{json .Id}} {{json .Image}} {{json .HostConfig.NetworkMode}} {{json .Config.Labels}}',
        container], capture_output=True, timeout=5, check=True)
    decoder, text, values = json.JSONDecoder(), result.stdout.decode(), []
    while text.strip():
        value, end = decoder.raw_decode(text.lstrip())
        values.append(value)
        text = text.lstrip()[end:]
    identity, image, network, labels = values
    require(identity == container and image == IMAGE and network == "none"
            and labels.get("nanfo.adr025.owner") == policy["owner_label"], "teardown_not_owned")
    top = subprocess.run(["docker", "top", container, "-eo", "pid"],
                         capture_output=True, timeout=5, check=True).stdout.decode().splitlines()[1:]
    require(0 < len(top) <= 4096, "owned_process_inventory_unavailable")
    identities = []
    for row in top:
        pid = int(row.strip())
        try:
            text = Path(f"/proc/{pid}/stat").read_text()
            identities.append({"pid": pid, "start_ticks": int(text[text.rfind(")") + 2:].split()[19]),
                               "netns": os.readlink(f"/proc/{pid}/ns/net")})
        except FileNotFoundError:
            continue
    require(bool(identities), "owned_process_identity_unavailable")
    # Caller must preserve this before destructive teardown; stdout is not the WAL.
    return identities


def complete_teardown(policy, identities):
    current = teardown_owned_graph(policy)
    require({(row["pid"], row["start_ticks"], row["netns"]) for row in current}
            <= {(row["pid"], row["start_ticks"], row["netns"]) for row in identities},
            "teardown_process_family_changed")
    subprocess.run(["docker", "rm", "--force", policy["container_id"]],
                   capture_output=True, timeout=30, check=True)
    deadline = time.monotonic() + 10
    namespaces = {item["netns"] for item in identities}
    while True:
        survivors = []
        for path in Path("/proc").iterdir():
            if not path.name.isdigit():
                continue
            try:
                if os.readlink(path / "ns/net") in namespaces:
                    survivors.append(int(path.name))
            except FileNotFoundError:
                continue
            except PermissionError:
                raise ValueError("namespace_teardown_visibility_insufficient") from None
        if not survivors:
            return {"status": "owned_graph_destroyed", "container_id": policy["container_id"],
                    "recorded_processes": identities, "surviving_namespace_processes": [],
                    "original_forwarding_restored": False,
                    "scope": "disposable graph release, not in-place forwarding restoration"}
        require(time.monotonic() < deadline, "owned_namespace_teardown_unverified")
        time.sleep(.1)


def exchange(policy, payload):
    Request.parse(payload)
    container = policy["container_id"]
    result = subprocess.run(["docker", "inspect", "--format",
        '{{json .Id}} {{json .Image}} {{json .HostConfig.NetworkMode}} {{json .Config.Labels}} {{json .Mounts}}',
        container], capture_output=True, timeout=5, check=True)
    decoder, text, values = json.JSONDecoder(), result.stdout.decode(), []
    while text.strip():
        value, end = decoder.raw_decode(text.lstrip())
        values.append(value)
        text = text.lstrip()[end:]
    identity, image, network, labels, mounts = values
    require(identity == container and image == IMAGE and network == "none"
            and labels.get("nanfo.adr025.owner") == policy["owner_label"], "container_not_owned_or_pinned")
    require(all(not (m["Destination"] == "/" or m["Destination"] == "/opt"
                     or m["Destination"].startswith("/opt/nanfo")) for m in mounts), "original_source_mount_forbidden")
    require(any(m["Destination"] == "/run/nanfo-experimental" and m["RW"] for m in mounts),
            "durable_receiver_mount_required")
    result = subprocess.run(["docker", "exec", "-i", container, "python", "-B", "-c", CLIENT],
                            input=payload, capture_output=True, timeout=55, check=True)
    return decode(result.stdout, RESPONSE_LIMIT)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--teardown-evidence-directory")
    args = parser.parse_args(argv)
    policy = load_policy(args.policy, args.policy_sha256)
    if args.teardown_evidence_directory:
        directory = Path(args.teardown_evidence_directory)
        require(directory.is_absolute(), "absolute_teardown_evidence_directory_required")
        require(not (directory / "teardown-intent.json").exists(), "teardown_attempt_already_exists")
        identities = teardown_owned_graph(policy)
        atomic_write(directory / "teardown-intent.json", {
            "policy_sha256": args.policy_sha256, "container_id": policy["container_id"],
            "processes": identities, "began_at": time.time()})
        result = complete_teardown(policy, identities)
        atomic_write(directory / "teardown-result.json", result)
        print(canonical(result).decode())
        return
    request = decode(sys.stdin.buffer.read(8193))
    require("token" not in request, "token_must_come_from_protected_file")
    request["token"] = protected_read(args.token).decode().strip()
    require(request["policy_sha256"] == args.policy_sha256, "request_policy_mismatch")
    print(canonical(exchange(policy, canonical(request))).decode())


if __name__ == "__main__":
    main()
