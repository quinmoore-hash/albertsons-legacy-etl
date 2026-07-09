"""Fetch POS / store-sales data from the vendor API.

Python port of ``scripts/fetch_pos_data.sh``. Performs a GET against
``${POS_API_BASE_URL}/store-sales/daily?date=...&format=csv`` with an
``X-Api-Key`` header (resolved from Secret Manager), retrying on failure, and
writes the CSV response to disk.

Exit codes: ``0`` success, ``1`` failure (matching the Bash original).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional, Sequence, Union

import requests

from etl.config import Settings, get_settings
from etl.file_utils import count_data_rows
from etl.logging_util import log_error, log_info, log_warn, setup_logging

RETRY_SLEEP_SECONDS = 10
MAX_TIME_SECONDS = 180

PathLike = Union[str, Path]


def fetch_pos_data(
    output_file: PathLike,
    fetch_date: Optional[str] = None,
    settings: Optional[Settings] = None,
    session: Optional[requests.Session] = None,
) -> int:
    """Fetch POS store-sales for ``fetch_date`` into ``output_file``.

    Returns ``0`` on success, ``1`` after exhausting retries.
    """
    settings = settings or get_settings()
    session = session or requests.Session()
    fetch_date = fetch_date or date.today().isoformat()

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        api_key = settings.pos_api_key
    except Exception as exc:  # secret resolution failure
        log_warn("Could not resolve POS_API_KEY (%s); requests will likely 401", exc)
        api_key = ""
    if not api_key:
        log_warn("POS_API_KEY is not set; requests will likely 401")

    url = f"{settings.pos_api_base_url}/store-sales/daily"
    params = {"date": fetch_date, "format": "csv"}
    headers = {"X-Api-Key": api_key, "Accept": "text/csv"}

    log_info("Fetching POS store-sales for %s -> %s", fetch_date, out_path)

    retries = settings.pos_api_retry_count
    timeout = (settings.pos_api_timeout, MAX_TIME_SECONDS)

    last_status: object = "n/a"
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=timeout)
            last_status = resp.status_code
            if resp.status_code == 200:
                out_path.write_bytes(resp.content)
                rows = count_data_rows(out_path)
                log_info("POS fetch OK (HTTP 200), %s rows -> %s", rows, out_path)
                return 0
        except requests.RequestException as exc:
            last_status = f"error: {exc}"

        log_warn(
            "POS fetch attempt %s/%s failed (HTTP %s), retrying in %ss...",
            attempt,
            retries,
            last_status,
            RETRY_SLEEP_SECONDS,
        )
        if attempt < retries:
            time.sleep(RETRY_SLEEP_SECONDS)

    log_error("POS fetch failed after %s attempts (last HTTP %s)", retries, last_status)
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)

    parser = argparse.ArgumentParser(description="Fetch POS store-sales CSV from the vendor API")
    default_out = os.path.join(
        settings.data_input_dir, f"pos_store_sales_{date.today():%Y%m%d}.csv"
    )
    parser.add_argument("output_file", nargs="?", default=default_out)
    parser.add_argument("fetch_date", nargs="?", default=None, help="YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)

    return fetch_pos_data(args.output_file, args.fetch_date, settings=settings)


if __name__ == "__main__":
    sys.exit(main())
