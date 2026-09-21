"""Pure versioned FRR wire constants; importing schemas never imports a driver."""

RUNTIME = "isolated-linux-frr-host-route/v1"
PATHS = (("access1", "dist1", "access2"), ("access1", "dist2", "access2"))
ROUTERS = ("access1", "access2", "dist1", "dist2", "core")


def action_map():
    return {str(index): list(path) for index, path in enumerate(PATHS)}
