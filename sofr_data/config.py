"""Configuration for the SOFR futures data collection stage."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Databento -------------------------------------------------------------

DATASET = "GLBX.MDP3"
"""CME Globex MDP 3.0, which carries the CME SOFR futures complex."""

ROOT_SR1 = "SR1"
"""CME product root for One-Month SOFR futures."""

ROOT_SR3 = "SR3"
"""CME product root for Three-Month SOFR futures."""

ROOTS: tuple[str, ...] = (ROOT_SR1, ROOT_SR3)

PARENT_SYMBOL = {root: f"{root}.FUT" for root in ROOTS}
"""Databento `parent` symbology selects every leg of a product's futures chain."""

API_KEY_FILE = Path.home() / ".databento_api_key"
"""Course convention: one line, mode 600. See `finm37000.db_env_util`."""

API_KEY_ENV = "DATABENTO_API_KEY"

# --- Sample period ---------------------------------------------------------

START = pd.Timestamp("2022-01-01")
END = pd.Timestamp("2026-09-30")

# --- Paths -----------------------------------------------------------------

DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = REPO_ROOT / "reports"

SETTLEMENTS_PARQUET = PROCESSED_DIR / "sofr_futures_settlements.parquet"
SETTLEMENTS_CSV = PROCESSED_DIR / "sofr_futures_settlements.csv"
CONTRACTS_PARQUET = PROCESSED_DIR / "sofr_futures_contracts.parquet"
CONTRACTS_CSV = PROCESSED_DIR / "sofr_futures_contracts.csv"
QUALITY_REPORT = REPORTS_DIR / "data_quality_sofr_futures.md"
QUALITY_JSON = REPORTS_DIR / "data_quality_sofr_futures.json"

# --- Sanity bounds used by the quality checks ------------------------------

MIN_PLAUSIBLE_PRICE = 80.0
"""A settlement of 80 implies a 20% rate; anything lower is a data error."""

MAX_PLAUSIBLE_PRICE = 102.0
"""A settlement above 100 implies a negative rate, which is possible but rare."""

MAX_PLAUSIBLE_DAILY_RATE_MOVE_BP = 50.0
"""Day-over-day implied-rate moves beyond this are flagged for inspection."""

STALE_PRICE_RUN_LENGTH = 10
"""Flag a contract whose settlement is unchanged for this many trading days."""


def ensure_dirs() -> None:
    """Create the data and report directories if they do not already exist."""
    for path in (RAW_DIR, PROCESSED_DIR, REPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def resolve_api_key() -> str:
    """Return the Databento API key.

    Looks in `~/.databento_api_key` first (the convention used by the course
    package) and falls back to the `DATABENTO_API_KEY` environment variable.

    Raises:
        FileNotFoundError: If neither source provides a key.
    """
    if API_KEY_FILE.exists():
        key = API_KEY_FILE.read_text().splitlines()[0].strip()
        if key:
            return key

    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key

    msg = (
        f"No Databento API key found.\n"
        f"  Save it to {API_KEY_FILE} (recommended):\n"
        f"      printf '%s' 'db-YOUR_KEY' > {API_KEY_FILE}\n"
        f"      chmod 600 {API_KEY_FILE}\n"
        f"  or export {API_KEY_ENV}."
    )
    raise FileNotFoundError(msg)
