"""Verify the Python/GCP dependencies the pipeline needs are importable.

Python port of ``scripts/check_dependencies.sh``. The legacy script checked for
CLI tools (``snowsql``, ``bq``, ``gsutil``, ``jq`` ...); the pipeline is now a
Python package, so instead we verify the required libraries import cleanly.

Exit codes: ``0`` all required deps present, ``1`` one or more missing.
"""

from __future__ import annotations

import importlib
import sys
from typing import Optional, Sequence

from etl.logging_util import log_error, log_info, log_warn, setup_logging

# import name -> pip distribution (for the operator-facing hint)
REQUIRED = {
    "google.cloud.bigquery": "google-cloud-bigquery",
    "google.cloud.storage": "google-cloud-storage",
    "google.cloud.secretmanager": "google-cloud-secret-manager",
    "requests": "requests",
}

OPTIONAL = {
    "pandas": "pandas",
}


def _try_import(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


def check_dependencies() -> int:
    missing = 0

    for module, dist in REQUIRED.items():
        if _try_import(module):
            log_info("OK: %s", module)
        else:
            log_error("MISSING: %s (pip install %s)", module, dist)
            missing += 1

    for module, dist in OPTIONAL.items():
        if _try_import(module):
            log_info("OK (optional): %s", module)
        else:
            log_warn("optional dependency not installed: %s (pip install %s)", module, dist)

    if missing > 0:
        log_error("%s core dependencies missing", missing)
        return 1

    log_info("All core dependencies present")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    setup_logging()
    return check_dependencies()


if __name__ == "__main__":
    sys.exit(main())
