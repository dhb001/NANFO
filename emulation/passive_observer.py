"""Host-only compatibility shim (ADR-028); not part of the stdlib-only lab package.

The passive observer needs the backend interpreter (Python 3.12, pydantic, app code)
and now lives in ``app.modules.autonomy.experimental.passive_observer``. Importing
this module returns that module object; ``python -m emulation.passive_observer``
still runs its CLI.
"""

import sys
from importlib import import_module

TARGET = "app.modules.autonomy.experimental.passive_observer"

if __name__ == "__main__":
    raise SystemExit(import_module(TARGET).main())
sys.modules[__name__] = import_module(TARGET)
