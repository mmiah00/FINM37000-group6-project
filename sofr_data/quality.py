"""Checks for missing or inconsistent SOFR futures settlement observations.

Nothing here modifies the panel. The job is to surface anything that would
quietly corrupt the implied-path estimation later: absent settlements on days a
contract was clearly live, prices that cannot be right, stale repeats, and
contract identifiers that disagree with the exchange's own expiration dates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    USFederalHolidayCalendar,
)
from pandas.tseries.offsets import CustomBusinessDay

from sofr_data import config
from sofr_data.contracts import EXPIRY_MONTH_OFFSET


class CMEHolidayCalendar(AbstractHolidayCalendar):
    """US federal holidays plus Good Friday, on which CME is closed.

    Columbus Day and Veterans Day are included via the federal calendar even
    though CME trades then. That only makes the expected-trading-day set
    conservative, which costs us a little sensitivity but produces no false
    reports of missing data.
    """

    rules = [*USFederalHolidayCalendar.rules, GoodFriday]


CME_BUSINESS_DAY = CustomBusinessDay(calendar=CMEHolidayCalendar())


@dataclass
class QualityReport:
    """Results of the data quality checks."""

    summary: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)

    def add(self, key: str, value: Any) -> None:  # noqa: ANN401
        """Record a scalar summary value."""
        self.summary[key] = value

    def add_table(self, key: str, table: pd.DataFrame) -> None:
        """Record a table of flagged rows."""
        self.tables[key] = table


def expected_trading_days(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Trading days expected between `start` and `end` inclusive."""
    return pd.date_range(start.normalize(), end.normalize(), freq=CME_BUSINESS_DAY)


def check_coverage(panel: pd.DataFrame, report: QualityReport) -> None:
    """Compare observed trade dates against the expected trading calendar."""
    rows = []
    for root, group in panel.groupby("root"):
        observed = pd.DatetimeIndex(group["trade_date"].unique()).normalize()
        expected = expected_trading_days(observed.min(), observed.max())
        missing = expected.difference(observed)
        unexpected = observed.difference(expected)
        rows.append(
            {
                "root": root,
                "first_trade_date": observed.min().date(),
                "last_trade_date": observed.max().date(),
                "trading_days_observed": len(observed),
                "trading_days_expected": len(expected),
                "missing_days": len(missing),
                "days_outside_calendar": len(unexpected),
                "missing_dates": ", ".join(d.date().isoformat() for d in missing[:20]),
            }
        )
    report.add_table("coverage", pd.DataFrame(rows))


def check_duplicates(panel: pd.DataFrame, report: QualityReport) -> None:
    """Flag repeated (trade date, contract) pairs, which must be unique."""
    duplicated = panel.duplicated(subset=["trade_date", "contract_id"], keep=False)
    report.add("duplicate_rows", int(duplicated.sum()))
    if duplicated.any():
        report.add_table(
            "duplicates",
            panel.loc[duplicated, ["trade_date", "contract_id", "settlement_price"]],
        )


def check_missing_settlements(panel: pd.DataFrame, report: QualityReport) -> None:
    """Flag live contracts with no final settlement price.

    Open interest above zero means the contract existed and was held that day,
    so a missing settlement is a real gap rather than an unlisted contract.
    """
    missing = panel["settlement_price"].isna()
    report.add("rows_without_settlement", int(missing.sum()))

    live = missing & (panel["open_interest"].fillna(0) > 0)
    report.add("live_rows_without_settlement", int(live.sum()))
    if live.any():
        report.add_table(
            "missing_settlement_with_open_interest",
            panel.loc[
                live,
                ["trade_date", "contract_id", "open_interest", "cleared_volume"],
            ].head(200),
        )


def check_price_bounds(panel: pd.DataFrame, report: QualityReport) -> None:
    """Flag settlement prices outside a plausible range for a STIR future."""
    priced = panel.dropna(subset=["settlement_price"])
    bad = priced.loc[
        (priced["settlement_price"] < config.MIN_PLAUSIBLE_PRICE)
        | (priced["settlement_price"] > config.MAX_PLAUSIBLE_PRICE)
    ]
    report.add("implausible_prices", len(bad))
    report.add("min_settlement_price", float(priced["settlement_price"].min()))
    report.add("max_settlement_price", float(priced["settlement_price"].max()))
    if not bad.empty:
        report.add_table(
            "implausible_prices",
            bad[["trade_date", "contract_id", "settlement_price"]].head(200),
        )


def check_rate_jumps(panel: pd.DataFrame, report: QualityReport) -> None:
    """Flag day-over-day implied-rate moves too large to be genuine."""
    priced = panel.dropna(subset=["settlement_price"]).sort_values(
        ["contract_id", "trade_date"]
    )
    moves = priced.assign(
        rate_move_bp=priced.groupby("contract_id")["implied_rate"].diff() * 100.0
    )
    bad = moves.loc[
        moves["rate_move_bp"].abs() > config.MAX_PLAUSIBLE_DAILY_RATE_MOVE_BP
    ]
    report.add("large_rate_jumps", len(bad))
    report.add(
        "max_abs_rate_move_bp",
        float(moves["rate_move_bp"].abs().max()) if len(moves) else 0.0,
    )
    if not bad.empty:
        report.add_table(
            "large_rate_jumps",
            bad[
                ["trade_date", "contract_id", "settlement_price", "rate_move_bp"]
            ].head(200),
        )


def check_stale_prices(panel: pd.DataFrame, report: QualityReport) -> None:
    """Flag contracts whose settlement never moves over a long run of days.

    Back-month SOFR contracts are illiquid, so a long flat run usually means
    the exchange is carrying a stale settlement forward rather than marking it.
    """
    priced = panel.dropna(subset=["settlement_price"]).sort_values(
        ["contract_id", "trade_date"]
    )
    if priced.empty:
        report.add("stale_price_runs", 0)
        return

    changed = priced.groupby("contract_id")["settlement_price"].diff().ne(0)
    run_id = changed.fillna(True).cumsum()
    runs = (
        priced.assign(run_id=run_id)
        .groupby(["contract_id", "run_id"], as_index=False)
        .agg(
            settlement_price=("settlement_price", "first"),
            run_start=("trade_date", "min"),
            run_end=("trade_date", "max"),
            run_length=("trade_date", "count"),
            max_open_interest=("open_interest", "max"),
        )
    )
    long_runs = runs.loc[runs["run_length"] >= config.STALE_PRICE_RUN_LENGTH]
    report.add("stale_price_runs", len(long_runs))
    if not long_runs.empty:
        report.add_table(
            "stale_price_runs",
            long_runs.sort_values("run_length", ascending=False)
            .drop(columns="run_id")
            .head(200),
        )


def check_expiration_convention(panel: pd.DataFrame, report: QualityReport) -> None:
    """Verify parsed contract months against the exchange's expiration dates.

    This is the check that catches the SR3 contract-month convention being
    implemented backwards: if `EXPIRY_MONTH_OFFSET` were wrong, essentially
    every SR3 row would land here.
    """
    dated = panel.dropna(subset=["expiration"])
    if dated.empty:
        report.add("expiration_convention_mismatches", 0)
        return

    actual = dated["expiration"].dt.to_period("M")
    expected = dated["expected_expiration_month"].dt.to_period("M")
    mismatch = actual != expected

    report.add("expiration_convention_mismatches", int(mismatch.sum()))
    report.add(
        "expiration_convention_mismatch_pct",
        round(100.0 * mismatch.mean(), 4),
    )
    report.add("expiry_month_offset_used", dict(EXPIRY_MONTH_OFFSET))
    if mismatch.any():
        report.add_table(
            "expiration_convention_mismatches",
            dated.loc[mismatch]
            .groupby(["root", "contract_id"], as_index=False)
            .agg(
                expiration=("expiration", "first"),
                expected_expiration_month=("expected_expiration_month", "first"),
                rows=("trade_date", "count"),
            )
            .head(200),
        )


def check_chain_depth(panel: pd.DataFrame, report: QualityReport) -> None:
    """Summarize how many contracts carry a settlement on each trade date.

    A day with far fewer priced legs than usual means a partial pull, which
    would distort any curve fitted on that date.
    """
    priced = panel.dropna(subset=["settlement_price"])
    rows = []
    thin_frames = []
    for root, group in priced.groupby("root"):
        depth = group.groupby("trade_date")["contract_id"].nunique()
        median = float(depth.median())
        threshold = max(1.0, 0.5 * median)
        thin = depth.loc[depth < threshold]
        rows.append(
            {
                "root": root,
                "min_legs": int(depth.min()),
                "median_legs": median,
                "max_legs": int(depth.max()),
                "thin_days": int(len(thin)),
            }
        )
        if not thin.empty:
            thin_frames.append(
                thin.rename("legs_priced").reset_index().assign(root=root)
            )

    report.add_table("chain_depth", pd.DataFrame(rows))
    if thin_frames:
        report.add_table(
            "thin_trading_days",
            pd.concat(thin_frames, ignore_index=True).head(200),
        )


def check_intra_life_gaps(panel: pd.DataFrame, report: QualityReport) -> None:
    """Flag trading days with no settlement between a contract's first and last.

    Scoped to each contract's own observed life, so contracts that were simply
    not yet listed are not counted as gaps.
    """
    priced = panel.dropna(subset=["settlement_price"])
    rows = []
    for contract_id, group in priced.groupby("contract_id"):
        observed = pd.DatetimeIndex(group["trade_date"].unique()).normalize()
        if len(observed) < 2:
            continue
        expected = expected_trading_days(observed.min(), observed.max())
        gaps = expected.difference(observed)
        if len(gaps):
            rows.append(
                {
                    "contract_id": contract_id,
                    "root": group["root"].iloc[0],
                    "gap_days": len(gaps),
                    "first_gap": gaps[0].date(),
                    "last_gap": gaps[-1].date(),
                }
            )

    gap_table = pd.DataFrame(rows)
    report.add("contracts_with_intra_life_gaps", len(gap_table))
    report.add(
        "total_intra_life_gap_days",
        int(gap_table["gap_days"].sum()) if not gap_table.empty else 0,
    )
    if not gap_table.empty:
        report.add_table(
            "intra_life_gaps",
            gap_table.sort_values("gap_days", ascending=False).head(200),
        )


def run_checks(panel: pd.DataFrame, extra: dict[str, Any] | None = None) -> QualityReport:
    """Run every check and return the assembled report."""
    report = QualityReport()
    report.add("rows", len(panel))
    report.add("contracts", int(panel["contract_id"].nunique()) if len(panel) else 0)
    report.add(
        "settlements", int(panel["settlement_price"].notna().sum()) if len(panel) else 0
    )
    for key, value in (extra or {}).items():
        report.add(key, value)

    if panel.empty:
        return report

    for check in (
        check_coverage,
        check_duplicates,
        check_missing_settlements,
        check_price_bounds,
        check_rate_jumps,
        check_stale_prices,
        check_expiration_convention,
        check_chain_depth,
        check_intra_life_gaps,
    ):
        check(panel, report)
    return report


def _table_to_markdown(table: pd.DataFrame) -> str:
    """Render a DataFrame as a markdown table.

    Hand-rolled rather than `DataFrame.to_markdown`, which needs `tabulate`;
    this keeps the project's dependencies to what Databento already pulls in.
    """
    header = [str(c) for c in table.columns]
    rows = [["" if pd.isna(v) else str(v) for v in row] for row in table.to_numpy()]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def render_markdown(report: QualityReport) -> str:
    """Render the report as markdown."""
    lines = [
        "# SOFR futures data quality report",
        "",
        f"Generated {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    lines += [f"| {k} | {v} |" for k, v in report.summary.items()]

    for name, table in report.tables.items():
        lines += ["", f"## {name.replace('_', ' ')}", ""]
        if table.empty:
            lines.append("None.")
        else:
            lines.append(_table_to_markdown(table))
    return "\n".join(lines) + "\n"


def write_report(report: QualityReport) -> None:
    """Write the markdown and JSON forms of the report to `reports/`."""
    config.ensure_dirs()
    config.QUALITY_REPORT.write_text(render_markdown(report))
    config.QUALITY_JSON.write_text(json.dumps(report.summary, indent=2, default=str))
