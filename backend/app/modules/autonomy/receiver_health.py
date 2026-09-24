"""Authenticated bounded progress receipts, published only by receiver iterations.

ADR-028 C21. v2 receipts are signed with the receiver's Ed25519 private key and carry
``key_id``; verifiers hold only the public key, so the API tier cannot forge receiver
progress. v1 (shared-secret HMAC) receipts are published/accepted only while
``NANFO_RECEIVER_HEALTH_LEGACY_HMAC=true`` for frozen runtimes.
"""

import asyncio
import hashlib
import hmac
import json
import time
import uuid

from app.core.canonical import canonical_json_bytes
from app.modules.autonomy.health_secret import legacy_hmac_enabled

RECEIPT_V1 = "nanfo.autonomous-receiver-health/v1"
RECEIPT_V2 = "nanfo.autonomous-receiver-health/v2"


class ReceiverHealth:
    def __init__(self, redis, installation, resource_id, key=None, *, max_age_seconds=10, signer=None, verifier=None):
        # ``key`` is the legacy shared HMAC secret (None unless legacy mode is enabled).
        self.redis, self.key, self.max_age = redis, key, max_age_seconds
        self.signer, self.verifier = signer, verifier
        data = installation.data
        self.scope = dict(installation_sha256=installation.sha256, resource_id=resource_id,
            runtime=data.runtime_action, runtime_binding_sha256=data.runtime_binding.sha256 if data.runtime_binding else None,
            network_id=str(data.network_id), workspace_id=str(data.workspace_id), run_id=data.calibration.run_id)
        self.redis_key = "autonomous:receiver-health:" + hashlib.sha256(self.canonical(self.scope)).hexdigest()
        self.process_id, self.iteration = str(uuid.uuid4()), 0

    @staticmethod
    def canonical(value):
        return canonical_json_bytes(value)

    @staticmethod
    def identity_of(identity, legacy_key):
        """Comparable credential identity (key id / legacy-secret digest), never key material."""
        return (getattr(identity, "key_id", None), hashlib.sha256(legacy_key).hexdigest() if legacy_key else None)

    @property
    def credentials_identity(self):
        return self.identity_of(self.verifier or self.signer, self.key)

    async def completed(self):
        self.iteration += 1
        common = dict(**self.scope, process_id=self.process_id, iteration=self.iteration, completed_at=time.time())
        if self.signer is not None:
            body = dict(version=RECEIPT_V2, key_id=self.signer.key_id, **common)
            receipt = dict(body=body, signature=self.signer.sign(self.canonical(body)))
        elif self.key is not None and legacy_hmac_enabled():
            body = dict(version=RECEIPT_V1, **common)
            receipt = dict(body=body, mac=hmac.new(self.key, self.canonical(body), hashlib.sha256).hexdigest())
        else:
            raise ValueError("receiver_health_signing_key_unconfigured")
        await self.redis.set(self.redis_key, self.canonical(receipt), ex=self.max_age)

    def _authenticate(self, receipt):
        body = receipt.get("body")
        if not isinstance(body, dict):
            raise ValueError("receiver_progress_invalid")
        if set(receipt) == {"body", "signature"}:
            if self.verifier is None:
                raise ValueError("receiver_progress_verifier_unconfigured")
            if body.get("version") != RECEIPT_V2:
                raise ValueError("receiver_progress_invalid_or_stale")
            if body.get("key_id") != self.verifier.key_id:
                raise ValueError("receiver_progress_key_id_mismatch")
            if not self.verifier.verify(self.canonical(body), receipt["signature"]):
                raise ValueError("receiver_progress_signature_invalid")
            return body
        if set(receipt) == {"body", "mac"}:
            if not legacy_hmac_enabled() or self.key is None:
                raise ValueError("receiver_progress_legacy_hmac_disabled")
            expected = hmac.new(self.key, self.canonical(body), hashlib.sha256).hexdigest()
            if (not isinstance(receipt["mac"], str) or not hmac.compare_digest(expected, receipt["mac"])
                    or body.get("version") != RECEIPT_V1):
                raise ValueError("receiver_progress_invalid_or_stale")
            return body
        raise ValueError("receiver_progress_invalid")

    async def check(self):
        async with asyncio.timeout(2):
            raw = await self.redis.get(self.redis_key)
            ttl = await self.redis.ttl(self.redis_key)
        if raw is None or len(raw) > 4096:
            raise ValueError("receiver_progress_missing")
        receipt = json.loads(raw)
        if not isinstance(receipt, dict):
            raise ValueError("receiver_progress_invalid")
        body = self._authenticate(receipt)
        if (any(body.get(k) != v for k, v in self.scope.items())
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
