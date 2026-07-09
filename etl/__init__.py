"""Albertsons store ETL pipeline (Python, BigQuery/GCS target).

This package is the Python rewrite of the legacy Bash + cron pipeline that
previously lived in ``scripts/`` and ``utils/``. It repoints the warehouse
steps from the decommissioned Snowflake account to BigQuery and reads its
configuration from environment variables and Google Secret Manager instead of
the plaintext ``configs/pipeline.env`` file.
"""

__version__ = "1.0.0"
