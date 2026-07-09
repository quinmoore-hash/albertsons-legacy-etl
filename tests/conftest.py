"""Shared pytest fixtures."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from etl.config import Config, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


@pytest.fixture
def sample_sales_csv() -> Path:
    return DATA_DIR / "store_sales_sample.csv"


@pytest.fixture
def sample_inventory_csv() -> Path:
    return DATA_DIR / "inventory_sample.csv"


@pytest.fixture
def sample_catalog_json() -> Path:
    return DATA_DIR / "product_catalog_sample.json"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A Config whose working dirs point at an isolated tmp dir."""
    base = load_config()
    return dataclasses.replace(
        base,
        data_input_dir=tmp_path / "incoming",
        data_output_dir=tmp_path / "processed",
        data_staging_dir=tmp_path / "staging",
        data_archive_dir=tmp_path / "archive",
        data_error_dir=tmp_path / "errors",
        log_dir=tmp_path / "logs",
    )
