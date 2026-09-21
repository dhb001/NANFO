"""Authenticated bounded progress receipts, published only by receiver iterations."""

import hashlib
import asyncio
import hmac
import json
import time
import uuid


class ReceiverHealth:
    def __init__(self, redis, installation, resource_id, key, *, max_age_seconds=10):
        self.redis, self.key, self.max_age = redis, key, max_age_seconds
        data = installation.data
        self.scope = dict(installation_sha256=installation.sha256, resource_id=resource_id,
            runtime=data.runtime_action, runtime_binding_sha256=data.runtime_binding.sha256 if data.runtime_binding else None,
            network_id=str(data.network_id), workspace_id=str(data.workspace_id), run_id=data.calibration.run_id)
        self.redis_key = "autonomous:receiver-health:" + hashlib.sha256(self.canonical(self.scope)).hexdigest()
        self.process_id, self.iteration = str(uuid.uuid4()), 0

    @staticmethod
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    async def completed(self):
        self.iteration += 1
        body = dict(version="nanfo.autonomous-receiver-health/v1", **self.scope,
                    process_id=self.process_id, iteration=self.iteration, completed_at=time.time())
        mac = hmac.new(self.key, self.canonical(body), hashlib.sha256).hexdigest()
        await self.redis.set(self.redis_key, self.canonical(dict(body=body, mac=mac)), ex=self.max_age)

    async def check(self):
        async with asyncio.timeout(2):
            raw = await self.redis.get(self.redis_key)
            ttl = await self.redis.ttl(self.redis_key)
        if raw is None or len(raw) > 4096:
            raise ValueError("receiver_progress_missing")
        receipt = json.loads(raw)
        if set(receipt) != {"body", "mac"}:
            raise ValueError("receiver_progress_invalid")
        body = receipt["body"]
        expected = hmac.new(self.key, self.canonical(body), hashlib.sha256).hexdigest()
        if (not isinstance(receipt["mac"], str) or not hmac.compare_digest(expected, receipt["mac"])
                or body.get("version") != "nanfo.autonomous-receiver-health/v1"
                or any(body.get(k) != v for k, v in self.scope.items())
                or type(body.get("iteration")) is not int or body["iteration"] < 1
                or type(body.get("completed_at")) not in (float, int)
                or not 0 <= time.time() - body["completed_at"] < self.max_age):
            raise ValueError("receiver_progress_invalid_or_stale")
        uuid.UUID(body["process_id"])
        # No await follows timestamp validation above. A renewed key's TTL cannot
        # extend the authenticated lifetime of the body obtained by the earlier GET.
        if not 0 < ttl <= self.max_age:
            raise ValueError("receiver_progress_ttl_invalid")
        return body
