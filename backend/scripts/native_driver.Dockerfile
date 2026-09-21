FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
RUN apt-get update && apt-get install -y --no-install-recommends mininet iproute2 iputils-ping ethtool frr procps util-linux \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir setuptools==75.8.2
ENV PYTHONPATH=/source:/usr/lib/python3/dist-packages PYTHONDONTWRITEBYTECODE=1 NANFO_ISOLATED_LAB=1
ENTRYPOINT ["python", "/source/backend/scripts/verify_native_driver.py"]
