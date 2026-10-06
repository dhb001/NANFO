# ADR-028 C23 successor lab: Debian 13 "trixie", CPython 3.12, os-ken (maintained Ryu
# fork), hash-pinned Python closure. This is a NEW runtime identity: its results
# require fresh qualification and never relabel frozen evidence. The frozen EOL
# recipe is preserved byte-identically in Dockerfile.frozen / requirements.frozen.txt
# (historical reproduction uses the recorded frozen image ID, NANFO_LAB_FROZEN=1).
# Runtime profile (no privileged mode): cap_drop ALL, cap_add NET_ADMIN NET_RAW
# SYS_ADMIN (+NET_BIND_SERVICE for FRR modes), no-new-privileges, read-only root,
# nosuid/nodev tmpfs. emulation.runner refuses any other capability profile.
FROM python:3.12.14-slim-trixie@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/nanfo NANFO_ISOLATED_LAB=1 NANFO_LAB_PROFILE=successor \
    OSKEN_HUB_TYPE=eventlet EVENTLET_NO_GREENDNS=yes \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PIP_NO_INPUT=1
# Signed Debian trixie from ONE dated snapshot (debian-snapshot.sources replaces the base
# image's live sources): every package is pinned to the exact version in that snapshot,
# and dependencies resolve from the same frozen indices, so the pins never vanish.
COPY debian-snapshot.sources /etc/apt/sources.list.d/debian.sources
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        mininet=2.3.0-1.1 openvswitch-switch=3.5.0-1+b1 frr=10.3-3+deb13u1 \
        iproute2=6.15.0-1 iputils-ping=3:20240905-3 iperf3=3.18-2+deb13u2 \
        tcpdump=4.99.5-2 procps=2:4.0.4-9 tini=0.19.0-3+b8 ca-certificates=20250419 \
    && rm -rf /var/lib/apt/lists/* \
    # Only Debian's pure-Python Mininet library is exposed to CPython 3.12 (never the
    # whole system dist-packages tree, whose compiled modules target another ABI).
    && ln -s /usr/lib/python3/dist-packages/mininet /usr/local/lib/python3.12/site-packages/mininet \
    # FRR keeps uid 0 (no SETUID/SETGID capability): privs_init requires root to be a
    # member of its VTY group, so no setgroups() is ever attempted at runtime.
    && usermod -a -G frrvty root
WORKDIR /opt/nanfo
COPY requirements-build.txt requirements.txt /tmp/
# Build backend first (hash-pinned), then the closure without build isolation so no
# unpinned build dependency can be fetched for the sdist-only `ovs` binding.
RUN python -m pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements-build.txt \
    && python -m pip install --require-hashes --no-deps --no-build-isolation \
        --only-binary=:all: --no-binary=ovs -r /tmp/requirements.txt \
    && python -m pip check \
    && python -c "import mininet.net, os_ken.base.app_manager, os_ken.topology.switches"
COPY . /opt/nanfo/emulation/
RUN mkdir -p /run/nanfo /output \
    && python -m unittest -v emulation.tests.test_controller emulation.tests.test_runner \
        emulation.tests.test_emulation emulation.tests.test_actions emulation.tests.test_lab_contracts \
        emulation.tests.test_successor_image
LABEL org.nanfo.lab.profile="successor" org.nanfo.lab.frozen="false" \
      org.nanfo.lab.contract="nanfo.lab-contracts/v1" \
      org.opencontainers.image.title="nanfo-emulation successor lab (ADR-028 C23)"
ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "emulation.runner"]
CMD ["--output", "/output"]
