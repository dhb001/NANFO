"""Explicit isolated OVS driver. Reuses readback, not the manual authorization wire."""

import asyncio
import hashlib
import json


def readback_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


async def finish_thread(function):
    """Do not release receiver exclusion while a cancelled thread can still write."""
    task = asyncio.create_task(asyncio.to_thread(function))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


class IsolatedOVSDriver:
    driver_id = "isolated-ovs-autonomous/v1"

    def __init__(self, actions, *, resource_id, run_id, ownership_check):
        """ownership_check must prove this lab's lifetime exclusivity on every call.

        Provisioning must disable manual mailbox and experiment controllers. This
        driver is embedded beside the lab, never constructed for production.
        """
        self.actions, self.resource_id, self.run_id = actions, resource_id, str(run_id)
        self.ownership_check = ownership_check

    def owned(self):
        if self.ownership_check(self.resource_id, self.run_id) is not True:
            raise ValueError("isolated_lab_ownership_lost")

    async def prepare(self, plan):
        def read():
            self.owned()
            return self.actions.prepare(plan)
        return await finish_thread(read)

    async def apply(self, prepared, checkpoint):
        loop = asyncio.get_running_loop()

        def checked():
            self.owned()
            asyncio.run_coroutine_threadsafe(checkpoint(), loop).result(timeout=20)
            self.owned()

        await finish_thread(lambda: self.actions.apply(prepared, checked))

    async def verify(self, prepared, plan):
        def read():
            self.owned()
            actual = self.actions.reconcile(prepared)
            probe = self.actions.probe(plan)
            if not probe.get("sent") or probe.get("received") != probe["sent"]:
                raise ValueError("autonomous_reachability_failed")
            return {"readback_sha256": readback_digest(actual), "readback_verified": True,
                    "probe": probe, "traffic_effects_verified": False}
        return await finish_thread(read)

    async def compensate(self, prepared, checkpoint):
        loop = asyncio.get_running_loop()

        def checked():
            self.owned()
            asyncio.run_coroutine_threadsafe(checkpoint(), loop).result(timeout=20)
            self.owned()

        def restore():
            checked()
            actual = self.actions.rollback(prepared, checked)
            self.actions.reconcile()
            return {"readback_sha256": readback_digest(actual), "restoration_verified": True}
        return await finish_thread(restore)
