"""Tests for the raw-to-tidy pipeline and the data quality checks."""

from __future__ import annotations

import databento as db
import pandas as pd
import pytest
from conftest import make_definitions, make_statistics

from sofr_data import clean, quality
from sofr_data.contracts import Contract


def test_build_panel_produces_one_row_per_contract_day(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
    sr3_contracts: list[Contract],
    trade_dates: list[pd.Timestamp],
) -> None:
    statistics, definitions = clean_inputs
    panel = clean.build_panel(statistics, definitions)

    assert len(panel) == len(sr3_contracts) * len(trade_dates)
    assert not panel.duplicated(subset=["trade_date", "contract_id"]).any()
    assert set(clean.OUTPUT_COLUMNS).issubset(panel.columns)


def test_build_panel_drops_calendar_spreads(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    statistics, definitions = clean_inputs
    panel = clean.build_panel(statistics, definitions)
    assert panel["raw_symbol"].str.contains("-").sum() == 0
    assert set(panel["root"].unique()) == {"SR3"}


def test_build_panel_ignores_preliminary_settlements(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    """The fixture publishes a preliminary price 5.0 above the final one."""
    statistics, definitions = clean_inputs
    panel = clean.build_panel(statistics, definitions)
    front = panel.loc[panel["contract_id"] == "SR3-2024-03"].sort_values("trade_date")
    assert front["settlement_price"].iloc[0] == pytest.approx(95.0)
    assert panel["settlement_price"].max() < 96.0


def test_build_panel_takes_the_latest_final_settlement(
    sr3_contracts: list[Contract],
) -> None:
    """A revised final settlement must supersede the earlier one."""
    contracts = sr3_contracts[:1]
    trade_dates = [pd.Timestamp("2024-01-02")]
    statistics = make_statistics(
        contracts, trade_dates, {contracts[0].raw_symbol: [95.0]}
    )
    revision = statistics.iloc[[1]].copy()
    revision["ts_event"] = revision["ts_event"] + pd.Timedelta(hours=2)
    revision["price"] = 94.5
    statistics = pd.concat([statistics, revision], ignore_index=True)

    panel = clean.build_panel(
        statistics, make_definitions(contracts, [pd.Timestamp("2024-01-02")])
    )
    assert len(panel) == 1
    assert panel["settlement_price"].iloc[0] == pytest.approx(94.5)


def test_implied_rate_is_the_price_complement(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    statistics, definitions = clean_inputs
    panel = clean.build_panel(statistics, definitions)
    expected = 100.0 - panel["settlement_price"]
    pd.testing.assert_series_equal(
        panel["implied_rate"], expected, check_names=False
    )


def test_reference_periods_are_attached_and_ordered(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    statistics, definitions = clean_inputs
    panel = clean.build_panel(statistics, definitions)
    assert panel["reference_start"].notna().all()
    assert panel["reference_end"].notna().all()
    assert (panel["reference_end"] > panel["reference_start"]).all()
    # Within a trade date the chain is sorted by reference period.
    for _, group in panel.groupby("trade_date"):
        assert group["reference_start"].is_monotonic_increasing


def test_expiration_convention_check_passes_on_consistent_data(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    statistics, definitions = clean_inputs
    panel = clean.build_panel(statistics, definitions)
    report = quality.run_checks(panel)
    assert report.summary["expiration_convention_mismatches"] == 0


def test_expiration_convention_check_catches_a_wrong_convention(
    sr3_contracts: list[Contract], trade_dates: list[pd.Timestamp]
) -> None:
    """Shifting every expiration by a quarter must be detected, not absorbed.

    This is the guard against the SR3 contract-month convention being
    implemented backwards.
    """
    prices = {c.raw_symbol: [95.0] * len(trade_dates) for c in sr3_contracts}
    statistics = make_statistics(sr3_contracts, trade_dates, prices)
    definitions = make_definitions(sr3_contracts, [pd.Timestamp("2024-01-02")])
    definitions["expiration"] = definitions["expiration"] - pd.DateOffset(months=3)

    panel = clean.build_panel(statistics, definitions)
    report = quality.run_checks(panel)
    assert report.summary["expiration_convention_mismatches"] > 0


def test_missing_settlement_with_open_interest_is_flagged(
    sr3_contracts: list[Contract], trade_dates: list[pd.Timestamp]
) -> None:
    prices = {
        c.raw_symbol: [95.0] * len(trade_dates) for c in sr3_contracts
    }
    # Drop the front contract's settlement on two days; open interest stays.
    prices[sr3_contracts[0].raw_symbol][5] = pd.NA
    prices[sr3_contracts[0].raw_symbol][6] = pd.NA

    statistics = make_statistics(sr3_contracts, trade_dates, prices)
    definitions = make_definitions(sr3_contracts, [pd.Timestamp("2024-01-02")])
    panel = clean.build_panel(statistics, definitions)
    report = quality.run_checks(panel)

    assert report.summary["rows_without_settlement"] == 2
    assert report.summary["live_rows_without_settlement"] == 2
    assert len(report.tables["missing_settlement_with_open_interest"]) == 2


def test_implausible_price_is_flagged(
    sr3_contracts: list[Contract], trade_dates: list[pd.Timestamp]
) -> None:
    prices = {c.raw_symbol: [95.0] * len(trade_dates) for c in sr3_contracts}
    prices[sr3_contracts[1].raw_symbol][3] = 9.5  # a decimal-shift error

    statistics = make_statistics(sr3_contracts, trade_dates, prices)
    definitions = make_definitions(sr3_contracts, [pd.Timestamp("2024-01-02")])
    report = quality.run_checks(clean.build_panel(statistics, definitions))

    assert report.summary["implausible_prices"] == 1
    assert report.summary["large_rate_jumps"] >= 1


def test_stale_price_run_is_flagged(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
    sr3_contracts: list[Contract],
    trade_dates: list[pd.Timestamp],
) -> None:
    """A flat 20-day series must trip the stale-price check."""
    prices = {c.raw_symbol: [95.0] * len(trade_dates) for c in sr3_contracts}
    statistics = make_statistics(sr3_contracts, trade_dates, prices)
    definitions = make_definitions(sr3_contracts, [pd.Timestamp("2024-01-02")])
    report = quality.run_checks(clean.build_panel(statistics, definitions))
    assert report.summary["stale_price_runs"] == len(sr3_contracts)

    # The drifting fixture prices must not trip it.
    moving = quality.run_checks(clean.build_panel(*clean_inputs))
    assert moving.summary["stale_price_runs"] == 0


def test_post_expiry_rows_are_dropped() -> None:
    """A contract must not carry settlements past its last trading day."""
    contracts = [Contract("SR3", 2024, 3)]
    # SR3 Mar-2024 stops trading 2024-06-18; include dates either side.
    trade_dates = list(pd.bdate_range("2024-06-14", periods=6))
    prices = {contracts[0].raw_symbol: [95.0] * len(trade_dates)}
    statistics = make_statistics(contracts, trade_dates, prices)
    definitions = make_definitions(contracts, [pd.Timestamp("2024-06-14")])

    panel = clean.build_panel(statistics, definitions)
    filtered, dropped = clean.drop_post_expiry(panel)

    assert dropped > 0
    assert len(filtered) == len(panel) - dropped
    assert (filtered["trade_date"] <= filtered["expiration"]).all()


def test_intra_life_gap_is_flagged(
    sr3_contracts: list[Contract]
) -> None:
    """A missing trading day inside a contract's life must be reported."""
    dates = list(pd.bdate_range("2024-01-02", periods=10))
    del dates[4]  # remove 2024-01-08, an ordinary Monday
    prices = {c.raw_symbol: [95.0 + 0.01 * i for i in range(len(dates))] for c in sr3_contracts}

    statistics = make_statistics(sr3_contracts, dates, prices)
    definitions = make_definitions(sr3_contracts, [pd.Timestamp("2024-01-02")])
    report = quality.run_checks(clean.build_panel(statistics, definitions))

    assert report.summary["contracts_with_intra_life_gaps"] == len(sr3_contracts)
    assert report.summary["total_intra_life_gap_days"] == len(sr3_contracts)


def test_coverage_check_does_not_flag_holidays(
    sr3_contracts: list[Contract]
) -> None:
    """Good Friday and federal holidays are not missing data."""
    dates = [
        d
        for d in pd.bdate_range("2024-03-25", "2024-04-05")
        if d != pd.Timestamp("2024-03-29")  # Good Friday
    ]
    prices = {c.raw_symbol: [95.0 + 0.01 * i for i in range(len(dates))] for c in sr3_contracts}
    statistics = make_statistics(sr3_contracts, dates, prices)
    definitions = make_definitions(sr3_contracts, [pd.Timestamp("2024-03-25")])
    report = quality.run_checks(clean.build_panel(statistics, definitions))

    coverage = report.tables["coverage"]
    assert coverage["missing_days"].sum() == 0


def test_sr1_and_sr3_combine_into_one_panel(trade_dates: list[pd.Timestamp]) -> None:
    """Both roots must coexist with distinct identifiers and reference periods."""
    panels = []
    for contracts in (
        [Contract("SR1", 2024, 3), Contract("SR1", 2024, 4)],
        [Contract("SR3", 2024, 3), Contract("SR3", 2024, 6)],
    ):
        prices = {
            c.raw_symbol: [95.0 + 0.01 * i for i in range(len(trade_dates))]
            for c in contracts
        }
        panels.append(
            clean.build_panel(
                make_statistics(contracts, trade_dates, prices),
                make_definitions(contracts, [pd.Timestamp("2024-01-02")]),
            )
        )

    panel = pd.concat(panels, ignore_index=True)
    report = quality.run_checks(panel)

    assert set(panel["root"]) == {"SR1", "SR3"}
    assert report.summary["expiration_convention_mismatches"] == 0
    assert panel["contract_id"].nunique() == 4
    sr1 = panel.loc[panel["root"] == "SR1"].iloc[0]
    sr3 = panel.loc[panel["root"] == "SR3"].iloc[0]
    assert (sr1["reference_end"] - sr1["reference_start"]).days < 35
    assert (sr3["reference_end"] - sr3["reference_start"]).days > 80


def test_contract_table_summarizes_each_contract(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
    sr3_contracts: list[Contract],
    trade_dates: list[pd.Timestamp],
) -> None:
    panel = clean.build_panel(*clean_inputs)
    table = clean.build_contract_table(panel)
    assert len(table) == len(sr3_contracts)
    assert (table["n_settlements"] == len(trade_dates)).all()
    assert table["reference_start"].is_monotonic_increasing


def test_quality_report_renders_markdown(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    report = quality.run_checks(clean.build_panel(*clean_inputs))
    text = quality.render_markdown(report)
    assert text.startswith("# SOFR futures data quality report")
    assert "| Metric | Value |" in text
    assert "coverage" in text


def test_empty_inputs_do_not_raise() -> None:
    panel = clean.build_panel(pd.DataFrame(), pd.DataFrame())
    assert panel.empty
    report = quality.run_checks(panel)
    assert report.summary["rows"] == 0


def test_numeric_columns_have_numeric_dtypes(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    """Prices must be float, not object, or downstream arithmetic degrades."""
    panel = clean.build_panel(*clean_inputs)
    assert panel["settlement_price"].dtype == "float64"
    assert panel["implied_rate"].dtype == "float64"
    assert panel["cleared_volume"].dtype == "Int64"
    assert panel["open_interest"].dtype == "Int64"


def test_numeric_dtypes_survive_object_input(
    sr3_contracts: list[Contract], trade_dates: list[pd.Timestamp]
) -> None:
    """Databento chunks can arrive with object-dtype price columns."""
    prices = {c.raw_symbol: [95.0] * len(trade_dates) for c in sr3_contracts}
    statistics = make_statistics(sr3_contracts, trade_dates, prices)
    statistics["price"] = statistics["price"].astype(object)
    definitions = make_definitions(sr3_contracts, [pd.Timestamp("2024-01-02")])

    panel = clean.build_panel(statistics, definitions)
    assert panel["settlement_price"].dtype == "float64"
    assert panel["implied_rate"].dtype == "float64"


def test_build_panel_survives_a_parquet_round_trip(
    clean_inputs: tuple[pd.DataFrame, pd.DataFrame], tmp_path
) -> None:
    """Cached chunks come back from parquet at second or microsecond resolution.

    `pd.merge_asof` refuses to join datetime keys whose resolutions differ, so
    the pipeline must normalize them rather than inherit whatever parquet gave
    back.
    """
    statistics, definitions = clean_inputs
    stats_path, defs_path = tmp_path / "s.parquet", tmp_path / "d.parquet"
    statistics.to_parquet(stats_path, index=False)
    definitions.to_parquet(defs_path, index=False)

    direct = clean.build_panel(statistics, definitions)
    reloaded = clean.build_panel(
        pd.read_parquet(stats_path), pd.read_parquet(defs_path)
    )

    assert len(reloaded) == len(direct)
    pd.testing.assert_frame_equal(
        reloaded[clean.OUTPUT_COLUMNS], direct[clean.OUTPUT_COLUMNS]
    )


def test_to_naive_datetime_normalizes_resolution() -> None:
    for values in (
        pd.Series(pd.to_datetime(["2024-01-02"])).astype("datetime64[s]"),
        pd.Series(pd.to_datetime(["2024-01-02"], utc=True)),
        pd.Series(pd.to_datetime(["2024-01-02"])),
    ):
        result = clean.to_naive_datetime(values)
        assert result.dtype == "datetime64[ns]"
        assert result.iloc[0] == pd.Timestamp("2024-01-02")
