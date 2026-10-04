"""Turn raw Databento records into a tidy SOFR futures settlement panel."""

from __future__ import annotations

import logging

import databento as db
import pandas as pd

from sofr_data import config
from sofr_data.contracts import (
    implied_expiration_month,
    parse_from_expiration,
    reference_period,
)

logger = logging.getLogger(__name__)

SETTLEMENT_FINAL_ACTUAL_MASK = 0b11
"""CME MDP3 tag 715 SettlPriceType: bit 0 = final, bit 1 = actual.

Masking rather than testing ``stat_flags == 3`` keeps the row if the exchange
also sets an unrelated higher bit. Preliminary and intraday settlements are
excluded, since the project needs the price the contract actually settled at.
"""

OUTPUT_COLUMNS = [
    "trade_date",
    "root",
    "contract_id",
    "raw_symbol",
    "contract_month",
    "reference_start",
    "reference_end",
    "expiration",
    "settlement_price",
    "implied_rate",
    "cleared_volume",
    "open_interest",
]


def to_naive_datetime(values: pd.Series) -> pd.Series:
    """Coerce a datetime column to timezone-naive UTC.

    Databento returns timezone-aware UTC timestamps while locally built
    columns are naive. Normalizing explicitly avoids relying on pandas'
    version-dependent handling of `tz_localize(None)` on naive input.

    The unit is pinned to nanoseconds because a parquet round-trip can return
    second- or microsecond-resolution datetimes, and `pd.merge_asof` refuses to
    join keys whose resolutions differ.
    """
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    naive = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
    return naive.astype("datetime64[ns]")


def filter_outright_futures(definitions: pd.DataFrame) -> pd.DataFrame:
    """Keep outright futures legs, dropping calendar spreads and other classes.

    `parent` symbology returns spreads alongside outrights, and a spread has no
    settlement reference period of its own.
    """
    if definitions.empty:
        return definitions
    is_future = definitions["instrument_class"].astype(str) == str(
        db.InstrumentClass.FUTURE
    )
    return definitions.loc[is_future].copy()


def build_instrument_table(definitions: pd.DataFrame) -> pd.DataFrame:
    """Collapse monthly definition snapshots into one row per instrument.

    Returns:
        `instrument_id`, `raw_symbol`, `expiration` and the first
        `snapshot_date` on which the instrument was seen.
    """
    outrights = filter_outright_futures(definitions)
    if outrights.empty:
        return pd.DataFrame(
            columns=["instrument_id", "raw_symbol", "expiration", "snapshot_date"]
        )

    outrights = outrights.dropna(subset=["expiration"]).sort_values("snapshot_date")
    return (
        outrights.groupby(["instrument_id", "raw_symbol"], as_index=False)
        .agg(expiration=("expiration", "first"), snapshot_date=("snapshot_date", "first"))
        .sort_values(["raw_symbol", "snapshot_date"])
        .reset_index(drop=True)
    )


def extract_daily_statistics(statistics: pd.DataFrame) -> pd.DataFrame:
    """Reduce raw statistics records to one row per contract per trade date.

    `ts_ref` is the session the statistic refers to, which is what we want as
    the trade date; `ts_event` is only used to pick the latest record when the
    exchange publishes a value more than once.

    Returns:
        `trade_date`, `instrument_id`, `symbol`, `settlement_price`,
        `cleared_volume` and `open_interest`.
    """
    if statistics.empty:
        return pd.DataFrame(
            columns=[
                "trade_date",
                "instrument_id",
                "symbol",
                "settlement_price",
                "cleared_volume",
                "open_interest",
            ]
        )

    frame = statistics.copy()
    frame["trade_date"] = pd.to_datetime(frame["ts_ref"], utc=True).dt.date
    frame = frame.sort_values("ts_event")
    keys = ["trade_date", "instrument_id"]

    is_settlement = (frame["stat_type"] == int(db.StatType.SETTLEMENT_PRICE)) & (
        frame["stat_flags"].fillna(0).astype(int) & SETTLEMENT_FINAL_ACTUAL_MASK
        == SETTLEMENT_FINAL_ACTUAL_MASK
    )
    settlement = (
        frame.loc[is_settlement]
        .groupby(keys, as_index=False)
        .agg(settlement_price=("price", "last"), symbol=("symbol", "last"))
    )

    def last_quantity(stat_type: db.StatType, name: str) -> pd.DataFrame:
        subset = frame.loc[frame["stat_type"] == int(stat_type)]
        return subset.groupby(keys, as_index=False).agg(**{name: ("quantity", "last")})

    volume = last_quantity(db.StatType.CLEARED_VOLUME, "cleared_volume")
    interest = last_quantity(db.StatType.OPEN_INTEREST, "open_interest")

    # An outer merge keeps contracts that reported volume or open interest but
    # no final settlement, so the quality checks can see the gap.
    symbols = frame.groupby(keys, as_index=False).agg(symbol_any=("symbol", "last"))
    daily = (
        symbols.merge(settlement, on=keys, how="outer")
        .merge(volume, on=keys, how="outer")
        .merge(interest, on=keys, how="outer")
    )
    daily["symbol"] = daily["symbol"].fillna(daily["symbol_any"])
    return daily.drop(columns="symbol_any")


def attach_definitions(
    daily: pd.DataFrame, instruments: pd.DataFrame
) -> pd.DataFrame:
    """Attach `raw_symbol` and `expiration` to each daily observation.

    Joined on `instrument_id` and resolved to the temporally nearest definition
    snapshot, so a recycled instrument id cannot silently pull in the wrong
    contract's expiration.
    """
    if daily.empty or instruments.empty:
        return daily.assign(raw_symbol=pd.NA, expiration=pd.NaT)

    left = daily.copy()
    left["_trade_ts"] = to_naive_datetime(left["trade_date"])
    right = instruments.copy()
    right["_snapshot_ts"] = to_naive_datetime(right["snapshot_date"])

    merged = pd.merge_asof(
        left.sort_values("_trade_ts"),
        right.sort_values("_snapshot_ts")[
            ["instrument_id", "raw_symbol", "expiration", "_snapshot_ts"]
        ],
        left_on="_trade_ts",
        right_on="_snapshot_ts",
        by="instrument_id",
        direction="nearest",
    )
    # Databento's own symbology mapping wins when the two disagree; it is
    # resolved per request date rather than per snapshot.
    merged["raw_symbol"] = merged["symbol"].fillna(merged["raw_symbol"])
    return merged.drop(columns=["_trade_ts", "_snapshot_ts"])


def standardize(frame: pd.DataFrame) -> pd.DataFrame:
    """Add standardized contract identifiers, reference periods and rates.

    Rows whose symbol is not an outright SR1/SR3 future are dropped, as are
    observations dated after the contract stopped trading.
    """
    if frame.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    out = frame.copy()
    out["expiration"] = to_naive_datetime(out["expiration"])

    contracts = [
        parse_from_expiration(str(sym), exp) if pd.notna(sym) else None
        for sym, exp in zip(out["raw_symbol"], out["expiration"], strict=True)
    ]
    recognized = pd.Series([c is not None for c in contracts], index=out.index)
    dropped = int((~recognized).sum())
    if dropped:
        logger.info("dropped %d rows that are not outright SR1/SR3 futures", dropped)

    out = out.loc[recognized].copy()
    kept = [c for c in contracts if c is not None]

    out["root"] = [c.root for c in kept]
    out["contract_id"] = [c.contract_id for c in kept]
    out["raw_symbol"] = [c.raw_symbol for c in kept]
    out["contract_month"] = [c.contract_month_start for c in kept]
    periods = [reference_period(c) for c in kept]
    out["reference_start"] = [p[0] for p in periods]
    out["reference_end"] = [p[1] for p in periods]
    out["expected_expiration_month"] = [
        implied_expiration_month(c).to_timestamp() for c in kept
    ]

    out["trade_date"] = to_naive_datetime(out["trade_date"])
    # Cast explicitly: a statistics chunk in which every settlement record was
    # preliminary leaves an all-NA object column, and `100.0 - object` silently
    # yields another object column that breaks arithmetic downstream.
    out["settlement_price"] = pd.to_numeric(
        out["settlement_price"], errors="coerce"
    ).astype("float64")
    out["implied_rate"] = 100.0 - out["settlement_price"]
    for column in ("cleared_volume", "open_interest"):
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")

    return out.sort_values(["trade_date", "root", "reference_start"]).reset_index(
        drop=True
    )


def build_panel(statistics: pd.DataFrame, definitions: pd.DataFrame) -> pd.DataFrame:
    """Run the full raw-to-tidy pipeline for one product root."""
    instruments = build_instrument_table(definitions)
    daily = extract_daily_statistics(statistics)
    return standardize(attach_definitions(daily, instruments))


def drop_post_expiry(panel: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Remove observations dated after a contract stopped trading.

    Returns:
        The filtered panel and the number of rows removed.
    """
    if panel.empty:
        return panel, 0
    keep = panel["trade_date"] <= panel["expiration"].dt.normalize()
    keep = keep | panel["expiration"].isna()
    return panel.loc[keep].reset_index(drop=True), int((~keep).sum())


def build_contract_table(panel: pd.DataFrame) -> pd.DataFrame:
    """One row per contract: its identifiers, reference period and sample span."""
    if panel.empty:
        return pd.DataFrame()
    return (
        panel.groupby(["root", "contract_id"], as_index=False)
        .agg(
            raw_symbol=("raw_symbol", "first"),
            contract_month=("contract_month", "first"),
            reference_start=("reference_start", "first"),
            reference_end=("reference_end", "first"),
            expiration=("expiration", "first"),
            first_trade_date=("trade_date", "min"),
            last_trade_date=("trade_date", "max"),
            n_settlements=("settlement_price", "count"),
        )
        .sort_values(["root", "reference_start"])
        .reset_index(drop=True)
    )
