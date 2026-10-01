"""Host-only compatibility shim (ADR-028); not part of the stdlib-only lab package.

The native observation clock needs Python 3.11+ (``datetime.UTC``) and now lives in
``app.modules.autonomy.experimental.native_qualification_clock``. Importing this
module returns that module object.
"""

import sys
from importlib import import_module

TARGET = "app.modules.autonomy.experimental.native_qualification_clock"

sys.modules[__name__] = import_module(TARGET)
