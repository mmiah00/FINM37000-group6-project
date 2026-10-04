"""Shared fixtures: synthetic records shaped like Databento's `to_df()` output."""

from __future__ import annotations

import sys
from pathlib import Path

import databento as db
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sofr_data.contracts import Contract, reference_period, third_wednesday  # noqa: E402

FINAL_ACTUAL = 3
PRELIMINARY = 1


def sr1_expiration(contract: Contract) -> pd.Timestamp:
    """Last business day of an SR1 contract month."""
    month_end = contract.contract_month_start + pd.offsets.MonthEnd(0)
    return month_end - pd.offsets.BDay(0) if month_end.dayofweek < 5 else month_end - pd.offsets.BDay(1)


def sr3_expiration(contract: Contract) -> pd.Timestamp:
    """Last day of an SR3 reference quarter."""
    return reference_period(contract)[1]


def make_definitions(contracts: list[Contract], snapshots: list[pd.Timestamp]) -> pd.DataFrame:
    """Definition snapshot records for a set of contracts."""
    rows = []
    for snapshot in snapshots:
        for index, contract in enumerate(contracts, start=1):
            expiration = (
                sr1_expiration(contract)
                if contract.root == "SR1"
                else sr3_expiration(contract)
            )
            rows.append(
                {
                    "instrument_id": 1000 + index,
                    "raw_symbol": contract.raw_symbol,
                    "instrument_class": str(db.InstrumentClass.FUTURE),
                    "expiration": expiration.tz_localize("UTC"),
                    "activation": (expiration - pd.Timedelta(days=400)).tz_localize("UTC"),
                    "snapshot_date": snapshot,
                }
            )
        # A calendar spread, which `parent` symbology returns alongside outrights.
        rows.append(
            {
                "instrument_id": 9999,
                "raw_symbol": f"{contracts[0].raw_symbol}-{contracts[-1].raw_symbol}",
                "instrument_class": str(db.InstrumentClass.FUTURE_SPREAD),
                "expiration": pd.Timestamp("2026-03-18").tz_localize("UTC"),
                "activation": pd.Timestamp("2022-01-03").tz_localize("UTC"),
                "snapshot_date": snapshot,
            }
        )
    return pd.DataFrame(rows)


def make_statistics(
    contracts: list[Contract],
    trade_dates: list[pd.Timestamp],
    prices: dict[str, list[float]],
) -> pd.DataFrame:
    """Statistics records carrying settlement, volume and open interest."""
    rows = []
    for index, contract in enumerate(contracts, start=1):
        instrument_id = 1000 + index
        for day_index, trade_date in enumerate(trade_dates):
            price = prices[contract.raw_symbol][day_index]
            ts_ref = trade_date.tz_localize("UTC")
            ts_event = ts_ref + pd.Timedelta(hours=21)
            common = {
                "ts_ref": ts_ref,
                "instrument_id": instrument_id,
                "symbol": contract.raw_symbol,
            }
            # A preliminary settlement that must be ignored.
            rows.append(
                {
                    **common,
                    "ts_event": ts_event - pd.Timedelta(minutes=30),
                    "price": price + 5.0,
                    "quantity": pd.NA,
                    "stat_type": int(db.StatType.SETTLEMENT_PRICE),
                    "stat_flags": PRELIMINARY,
                }
            )
            if price is not None and not pd.isna(price):
                rows.append(
                    {
                        **common,
                        "ts_event": ts_event,
                        "price": price,
                        "quantity": pd.NA,
                        "stat_type": int(db.StatType.SETTLEMENT_PRICE),
                        "stat_flags": FINAL_ACTUAL,
                    }
                )
            rows.append(
                {
                    **common,
                    "ts_event": ts_event,
                    "price": pd.NA,
                    "quantity": 1500 + day_index,
                    "stat_type": int(db.StatType.CLEARED_VOLUME),
                    "stat_flags": 0,
                }
            )
            rows.append(
                {
                    **common,
                    "ts_event": ts_event,
                    "price": pd.NA,
                    "quantity": 25000,
                    "stat_type": int(db.StatType.OPEN_INTEREST),
                    "stat_flags": 0,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def sr3_contracts() -> list[Contract]:
    """Four consecutive SR3 quarterly contracts."""
    return [
        Contract("SR3", 2024, 3),
        Contract("SR3", 2024, 6),
        Contract("SR3", 2024, 9),
        Contract("SR3", 2024, 12),
    ]


@pytest.fixture
def trade_dates() -> list[pd.Timestamp]:
    """Twenty consecutive business days in January 2024."""
    return list(pd.bdate_range("2024-01-02", periods=20))


@pytest.fixture
def clean_inputs(
    sr3_contracts: list[Contract], trade_dates: list[pd.Timestamp]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Well-formed statistics and definitions for the SR3 contracts."""
    prices = {
        contract.raw_symbol: [
            95.0 - 0.25 * index + 0.01 * day for day in range(len(trade_dates))
        ]
        for index, contract in enumerate(sr3_contracts)
    }
    statistics = make_statistics(sr3_contracts, trade_dates, prices)
    definitions = make_definitions(sr3_contracts, [pd.Timestamp("2024-01-02")])
    return statistics, definitions
