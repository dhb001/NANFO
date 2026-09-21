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
