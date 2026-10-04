"""Tests for contract identifier parsing and settlement reference periods."""

from __future__ import annotations

import pandas as pd
import pytest

from sofr_data.contracts import (
    Contract,
    implied_expiration_month,
    parse_from_expiration,
    parse_raw_symbol,
    reference_period,
    resolve_year,
    third_wednesday,
)


@pytest.mark.parametrize(
    ("digits", "anchor", "expected"),
    [
        ("2", 2022, 2022),
        ("5", 2025, 2025),
        ("9", 2021, 2019),
        ("1", 2022, 2021),
        ("0", 2029, 2030),
        ("26", 2026, 2026),
        ("31", 2026, 2031),
    ],
)
def test_resolve_year_picks_nearest_candidate(digits: str, anchor: int, expected: int) -> None:
    assert resolve_year(digits, anchor) == expected


def test_parse_raw_symbol_round_trips() -> None:
    contract = parse_raw_symbol("SR3Z5", 2025)
    assert contract == Contract("SR3", 2025, 12)
    assert contract.contract_id == "SR3-2025-12"
    assert contract.raw_symbol == "SR3Z5"


@pytest.mark.parametrize(
    "symbol",
    ["SR3H5-SR3M5", "ZNH5", "SR3", "SR2H5", "", "SR3W5"],
)
def test_parse_raw_symbol_rejects_non_outrights(symbol: str) -> None:
    assert parse_raw_symbol(symbol, 2025) is None


def test_parse_from_expiration_disambiguates_decades() -> None:
    """An SR3 with a one-digit year must resolve against its own expiration."""
    old = parse_from_expiration("SR3Z1", pd.Timestamp("2022-03-15"))
    new = parse_from_expiration("SR3Z1", pd.Timestamp("2032-03-16"))
    assert old is not None and new is not None
    assert old.contract_id == "SR3-2021-12"
    assert new.contract_id == "SR3-2031-12"


def test_parse_from_expiration_handles_year_boundary() -> None:
    """An SR3 expiring in January belongs to the prior October."""
    contract = parse_from_expiration("SR3V4", pd.Timestamp("2025-01-14"))
    assert contract is not None
    assert contract.contract_id == "SR3-2024-10"


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2024, 1, "2024-01-17"),
        (2024, 3, "2024-03-20"),
        (2024, 12, "2024-12-18"),
        (2025, 3, "2025-03-19"),
        (2026, 9, "2026-09-16"),
    ],
)
def test_third_wednesday(year: int, month: int, expected: str) -> None:
    result = third_wednesday(year, month)
    assert result.date().isoformat() == expected
    assert result.day_name() == "Wednesday"


def test_sr1_reference_period_is_the_contract_month() -> None:
    start, end = reference_period(Contract("SR1", 2024, 2))
    assert start.date().isoformat() == "2024-02-01"
    assert end.date().isoformat() == "2024-02-29"  # leap year


def test_sr3_reference_period_spans_imm_dates() -> None:
    start, end = reference_period(Contract("SR3", 2024, 12))
    assert start.date().isoformat() == "2024-12-18"
    assert end.date().isoformat() == "2025-03-18"
    # The quarter is bounded by consecutive third Wednesdays.
    assert start == third_wednesday(2024, 12)
    assert end + pd.Timedelta(days=1) == third_wednesday(2025, 3)


def test_sr3_reference_periods_tile_without_gaps_or_overlaps() -> None:
    """Consecutive SR3 quarters must join end-to-start."""
    quarters = [Contract("SR3", 2024, m) for m in (3, 6, 9, 12)]
    periods = [reference_period(c) for c in quarters]
    for (_, end), (next_start, _) in zip(periods, periods[1:], strict=False):
        assert next_start == end + pd.Timedelta(days=1)


def test_sr3_reference_period_is_about_three_months() -> None:
    for month in (3, 6, 9, 12):
        start, end = reference_period(Contract("SR3", 2025, month))
        length = (end - start).days + 1
        assert 84 <= length <= 98, (month, length)


def test_implied_expiration_month_follows_the_convention() -> None:
    assert str(implied_expiration_month(Contract("SR1", 2024, 3))) == "2024-03"
    assert str(implied_expiration_month(Contract("SR3", 2024, 12))) == "2025-03"
