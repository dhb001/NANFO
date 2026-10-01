"""Pure versioned FRR wire constants; importing schemas never imports a driver."""

from emulation.lab_contracts import ACTION_PATHS
from emulation.lab_contracts import action_map as action_map

RUNTIME = "isolated-linux-frr-host-route/v1"
PATHS = ACTION_PATHS
# Wire order of this runtime's router list (same set as lab_contracts.ROUTERS).
ROUTERS = ("access1", "access2", "dist1", "dist2", "core")
