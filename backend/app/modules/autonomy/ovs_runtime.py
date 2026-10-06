"""Isolated OVS lab runtime profile (driver module; OVS specifics stay here, fix 7).

Declares no extra capabilities: OVS reroute plans are the reviewed plans themselves and
the driver needs no independent dispatch guard. Emulation imports are lazy so API and
journal-client processes never load lab driver code.
"""

from app.modules.autonomy.drivers import RuntimeProfile, register_runtime
from app.modules.intent.lab import LabPlan

RUNTIME_ID = "isolated-ovs-autonomous/v1"


def build_lab_driver(lab, *, resource_id, run_id, ownership_check):
    from emulation.actions import Actions
    from emulation.autonomous_driver import IsolatedOVSDriver

    return IsolatedOVSDriver(Actions(lab), resource_id=resource_id, run_id=run_id, ownership_check=ownership_check)


PROFILE = register_runtime(RuntimeProfile(runtime_id=RUNTIME_ID, plan_type=LabPlan, lab_driver_factory=build_lab_driver))
