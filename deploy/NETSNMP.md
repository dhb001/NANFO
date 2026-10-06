# Net-SNMP worker provenance (ADR023)

Inspected on 2026-09-20 by fetching and decompressing the actual Debian repository
indices; no container build or package installation was run. Target: **linux/amd64**.
`with-fleet` installs `snmp`, `libsnmp40`, `libsnmp-base`, each exactly
**5.9.3+dfsg-2+deb12u1**, from the fixed snapshots in `fleet.sources`.

Repository release:
`https://snapshot.debian.org/archive/debian/20260901T000000Z/dists/bookworm/InRelease`

- Origin/Label Debian; Suite oldstable; Version 12.15; Codename bookworm.
- Release Date: Sat, 11 Jul 2026 10:16:37 UTC.
- InRelease SHA256: `77737fa4b34f2693e982cc9ee35736816c35a7778fc2d326cc1bbf5b301fe1aa`.
- `main/binary-amd64/Packages.xz` (8,790,396 bytes) SHA256:
  `9e0b5aabb2465b3d2e7a7fe27f9913846277833f7a2826e7767acccff5b588c5`.
  That hash appears in InRelease and matches the downloaded index.
- Security index at
  `https://snapshot.debian.org/archive/debian-security/20260901T000000Z/dists/bookworm-security/main/binary-amd64/Packages.xz`
  SHA256: `f6c2fe702b8cabb044e7bb46c5eaf3962abb6cfed5fcac896ffeb271b9d15104`;
  it lists the same three package versions and hashes.

| Package (main repository path prefix `pool/main/n/net-snmp/`) | Bytes | SHA256 |
|---|---:|---|
| `snmp_5.9.3+dfsg-2+deb12u1_amd64.deb` | 171900 | `e59d62511f5a6703c970cb9507be3623f129ea2e5d6a137318f8408ff50037f4` |
| `libsnmp40_5.9.3+dfsg-2+deb12u1_amd64.deb` | 2556916 | `bf91bd54cc35e2d790216b05f4d0d1331649e8e90ec8441849a137adeed5d9a3` |
| `libsnmp-base_5.9.3+dfsg-2+deb12u1_all.deb` | 1753352 | `fa1f522dfa4fe1289b4e7dfb3d15a0b1ef3f29f549f5f03fa23b876978746106` |

`snmp` declares exact dependency `libsnmp40 (= 5.9.3+dfsg-2+deb12u1)`.
APT verifies repository signatures using the pinned base image's Debian archive
keyring, then package hashes. Only historical Valid-Until checking is disabled;
signature/authentication checking remains required. The fetch above is provenance
inspection, not a claim of a completed APT signature/build acceptance gate.
Release admission still requires SHA-256/AES SNMPv3 integration and image package
inventory from the source-matched campaign. No daemon, MIB download or credentials
are included in the image.

## Collector runtime and egress restriction (ADR-028)

`compose.fleet.yaml` gives the collector a private memory-backed SNMP runtime base,
`NANFO_SNMP_RUNTIME_DIR=/run/nanfo-snmp` (tmpfs `noexec,nosuid,nodev`, UID/GID 10001,
mode 0700). `snmp_transport.py` refuses any base that is not owner-only, writes each
per-request USM `snmp.conf` (0600) in a fresh 0700 directory there and unlinks it after
the child exits, so SNMPv3 secrets never reach the shared `/tmp` or persistent storage.
The inherited `/tmp` and `/run/nanfo` scratch mounts are restated verbatim in the
overlay, so the merged mount list is the same whichever tmpfs merge rule Compose applies.

The `fleet_egress` bridge is the only non-internal network of the package. Its subnet
is pinned by the required `NANFO_FLEET_EGRESS_SUBNET` (an unused private /24 in
`deployment.env`), because an unpinned bridge may be recreated on a different subnet
and silently escape host firewall rules. Restrict it to SNMP requests to the managed
devices with host rules in Docker's `DOCKER-USER` chain (evaluated before Docker's own
forwarding rules, never flushed by Docker):

```sh
SUBNET=10.231.9.0/24     # NANFO_FLEET_EGRESS_SUBNET
DEVICES=10.20.0.0/16     # managed SNMP agents only; repeat the first rule per prefix
iptables -I DOCKER-USER 1 -s "$SUBNET" -d "$DEVICES" -p udp --dport 161 -j RETURN
iptables -I DOCKER-USER 2 -s "$SUBNET" -j DROP      # every other destination/port
iptables -I INPUT 1 -s "$SUBNET" -j DROP            # host services via the bridge gateway
```

Replies from the agents are accepted by Docker's established-connection rule; the
collector reaches PostgreSQL/Redis over the separate internal `private` bridge, whose
addresses these rules do not match. If the manifest names devices by DNS name, also
allow UDP/TCP 53 to the resolver only (`-d <resolver> -p udp --dport 53 -j RETURN`
before the DROP). Add matching `ip6tables` rules if the daemon enables IPv6 on bridges.
Persist the rules (for example `netfilter-persistent`, or a oneshot unit ordered
`After=docker.service`) and re-check them after host upgrades. Verify from the collector
that polling works while another destination times out:

```sh
docker compose --project-name nanfo-deploy-instance1 --env-file /srv/nanfo/instance1/deployment.env \
  -f deploy/compose.yaml -f deploy/compose.fleet.yaml --profile fleet exec fleet-worker \
  python -c "import socket; socket.create_connection(('192.0.2.1', 443), timeout=3)"   # must time out
```
