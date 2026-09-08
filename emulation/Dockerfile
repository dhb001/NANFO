FROM python:3.9.23-slim-bullseye@sha256:b9e06687fbfc57f6fe563e94e4c8751e39513dde89afc120dc6f56afe5ffc761

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/nanfo:/usr/lib/python3/dist-packages \
    NANFO_ISOLATED_LAB=1 EVENTLET_NO_GREENDNS=yes
COPY apt-sources.list /etc/apt/sources.list
RUN apt-get update && apt-get install -y --no-install-recommends \
    mininet=2.3.0-1 openvswitch-switch=2.15.0+ds1-2+deb11u5 \
    iproute2 iputils-ping iperf3 tcpdump procps tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/nanfo
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir pip==23.2.1 setuptools==57.5.0 wheel==0.37.1 \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip check
COPY . /opt/nanfo/emulation/
RUN mkdir -p /run/nanfo /output && python -m unittest discover -s emulation/tests -v
ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "emulation.runner"]
CMD ["--output", "/output"]
