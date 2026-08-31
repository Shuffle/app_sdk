# __init__.py
# In Docker image, shuffle_sdk.py is renamed to app_base.py
try:
    from .app_base import AppBase, csv_parse, shuffle_filters
except (ImportError, ModuleNotFoundError):
    from .shuffle_sdk import AppBase, csv_parse, shuffle_filters

from .sandbox import run_python, run_bash, run_liquid, is_available, configure, SANDBOX_ENABLED

__all__ = [
    "AppBase",
    "csv_parse",
    "shuffle_filters",
    "run_python",
    "run_bash",
    "run_liquid",
    "is_available",
    "configure",
    "SANDBOX_ENABLED",
]

__version__ = '0.0.26'

import sys
print(f"[SHUFFLE_SDK] Initialized", file=sys.stderr, flush=True)
