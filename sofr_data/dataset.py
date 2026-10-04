"""Load the cleaned SOFR futures data. This is the entry point for the model."""

from __future__ import annotations

import pandas as pd

from sofr_data import config


def _require(path) -> None:  # noqa: ANN001
    if not path.exists():
        msg = (
            f"{path} not found. Build it first:\n"
            "    python scripts/fetch_sofr_futures.py"
        )
        raise FileNotFoundError(msg)


def load_settlements(
    roots: tuple[str, ...] | None = None,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Load the tidy settlement panel, one row per contract per trade date.

    Args:
        roots: Restrict to these product roots, e.g. ``("SR3",)``.
        start: Earliest trade date to return, inclusive.
        end: Latest trade date to return, inclusive.

    Returns:
        A `pd.DataFrame` with the columns documented in `DATA.md`.
    """
    _require(config.SETTLEMENTS_PARQUET)
    panel = pd.read_parquet(config.SETTLEMENTS_PARQUET)
    if roots is not None:
        panel = panel.loc[panel["root"].isin(roots)]
    if start is not None:
        panel = panel.loc[panel["trade_date"] >= pd.Timestamp(start)]
    if end is not None:
        panel = panel.loc[panel["trade_date"] <= pd.Timestamp(end)]
    return panel.reset_index(drop=True)


def load_contracts() -> pd.DataFrame:
    """Load the contract reference table, one row per contract."""
    _require(config.CONTRACTS_PARQUET)
    return pd.read_parquet(config.CONTRACTS_PARQUET)


def settlement_curve(panel: pd.DataFrame, trade_date: pd.Timestamp | str) -> pd.DataFrame:
    """Return one trade date's priced contracts, in reference-period order.

    This is the cross-section the curve fitting consumes: every contract that
    had a settlement price on `trade_date`, with the SOFR window each one
    settles against.

    Args:
        panel: The settlement panel from `load_settlements`.
        trade_date: The date to extract.

    Returns:
        A `pd.DataFrame` sorted by `reference_start`, with no missing prices.
    """
    day = panel.loc[panel["trade_date"] == pd.Timestamp(trade_date)]
    return (
        day.dropna(subset=["settlement_price"])
        .sort_values(["root", "reference_start"])
        .reset_index(drop=True)
    )
