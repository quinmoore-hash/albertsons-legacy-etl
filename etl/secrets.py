"""Runtime secret resolution via Google Secret Manager.

Replaces the plaintext ``POS_API_KEY`` / ``SLACK_WEBHOOK_URL`` that used to
live in ``configs/pipeline.env``. Secrets are fetched at runtime from
Secret Manager for ``GCP_PROJECT``.

For local development / testing you can bypass Secret Manager entirely by
exporting the secret value directly as an environment variable named after
the secret id, upper-cased with ``-`` replaced by ``_`` (e.g. the secret
``pos-api-key`` maps to the env var ``POS_API_KEY``). This lets the pipeline
run without GCP credentials and keeps unit tests hermetic.
"""

from __future__ import annotations

import os
from functools import lru_cache

from etl.logging_setup import get_logger

logger = get_logger(__name__)


def _env_var_name(secret_id: str) -> str:
    return secret_id.replace("-", "_").upper()


@lru_cache(maxsize=None)
def get_secret(secret_id: str, project: str, version: str = "latest") -> str:
    """Return the secret payload for ``secret_id`` in ``project``.

    Resolution order:
      1. An environment variable override (see module docstring) — used for
         local dev and tests.
      2. Google Secret Manager.
    """
    override = os.environ.get(_env_var_name(secret_id))
    if override:
        logger.debug("Using environment override for secret '%s'", secret_id)
        return override

    # Imported lazily so importing this module doesn't require the GCP SDK
    # (e.g. in unit tests that only exercise the env-var override path).
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/{version}"
    logger.debug("Accessing secret '%s'", name)
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")
