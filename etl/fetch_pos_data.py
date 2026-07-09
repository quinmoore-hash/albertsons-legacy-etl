"""Fetch the vendor POS store-sales CSV feed.

Ported from ``scripts/fetch_pos_data.sh``. Uses ``requests`` with a
``tenacity`` retry loop, preserving the ``X-Api-Key`` header and the connect /
read timeouts. The API key now comes from Secret Manager instead of the
plaintext ``POS_API_KEY`` in ``pipeline.env``.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from etl.config import Config, load_config
from etl.logging_setup import configure_logging, get_logger
from etl.secrets import get_secret

logger = get_logger(__name__)


class PosFetchError(RuntimeError):
    """Raised when the POS feed cannot be fetched."""


def _default_output(config: Config, fetch_date: str) -> Path:
    return config.data_input_dir / f"pos_store_sales_{fetch_date.replace('-', '')}.csv"


def fetch_pos_data(
    output_file: str | Path | None = None,
    fetch_date: str | None = None,
    config: Config | None = None,
) -> Path:
    """Fetch POS store-sales CSV for ``fetch_date`` (default today) to ``output_file``."""
    config = config or load_config()
    fetch_date = fetch_date or date.today().isoformat()
    output_file = Path(output_file) if output_file else _default_output(config, fetch_date)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    api_key = get_secret(config.pos_api_key_secret, config.gcp_project)
    url = f"{config.pos_api_base_url}/store-sales/daily"
    params = {"date": fetch_date, "format": "csv"}
    headers = {"X-Api-Key": api_key, "Accept": "text/csv"}

    logger.info("Fetching POS store-sales for %s -> %s", fetch_date, output_file)

    @retry(
        retry=retry_if_exception_type((requests.RequestException, PosFetchError)),
        stop=stop_after_attempt(config.pos_api_retry_count),
        wait=wait_fixed(10),
        before_sleep=before_sleep_log(logger, 30),  # logging.WARNING
        reraise=True,
    )
    def _do_fetch() -> None:
        resp = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=(config.pos_api_timeout, 180),
        )
        if resp.status_code != 200:
            raise PosFetchError(
                f"POS fetch returned HTTP {resp.status_code}"
            )
        output_file.write_bytes(resp.content)

    try:
        _do_fetch()
    except (requests.RequestException, PosFetchError) as exc:
        logger.error("POS fetch failed after %d attempts: %s", config.pos_api_retry_count, exc)
        raise PosFetchError(str(exc)) from exc

    rows = max(sum(1 for _ in output_file.open("r", encoding="utf-8", errors="replace")) - 1, 0)
    logger.info("POS fetch OK, %d rows -> %s", rows, output_file)
    return output_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch vendor POS store-sales CSV feed")
    parser.add_argument("output_file", nargs="?", help="Destination CSV path")
    parser.add_argument("fetch_date", nargs="?", help="ISO date (YYYY-MM-DD), default today")
    args = parser.parse_args(argv)

    config = load_config()
    configure_logging(config.log_dir, config.log_level)
    try:
        fetch_pos_data(args.output_file, args.fetch_date, config=config)
    except PosFetchError:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
