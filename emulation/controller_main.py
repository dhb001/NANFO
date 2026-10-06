"""Fixed-argument os-ken launcher (os-ken 4.x ships no ``*-manager`` CLI).

Equivalent to the frozen ``ryu-manager --observe-links --ofp-listen-host 127.0.0.1
--ofp-tcp-listen-port 6653 --log-config-file .../logging.conf emulation.controller``.
The eventlet hub keeps the frozen controller's cooperative scheduling semantics. No
argument is accepted: the listener stays on container loopback.
"""

import os
import sys

ARGUMENTS = (
    "--observe-links",
    "--ofp-listen-host",
    "127.0.0.1",
    "--ofp-tcp-listen-port",
    "6653",
    "--log-config-file",
    "/opt/nanfo/emulation/logging.conf",
)
APPS = ("emulation.controller",)
HUB = "eventlet"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print("controller_main accepts no arguments", file=sys.stderr)
        return 2
    os.environ["OSKEN_HUB_TYPE"] = HUB
    from os_ken.lib import hub

    hub.patch(thread=False)
    # Same import order as the former manager CLI: app_manager before controller,
    # otherwise os_ken.controller.controller hits a circular import.
    # isort: off
    from os_ken.base.app_manager import AppManager
    import os_ken.controller.controller  # registers ofp-listen-host/port options
    import os_ken.topology.switches  # noqa: F401 - registers observe-links
    from os_ken import cfg, log

    # isort: on

    cfg.CONF(args=list(ARGUMENTS), project="os_ken", default_config_files=[])
    log.init_log()
    AppManager.run_apps(list(APPS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
