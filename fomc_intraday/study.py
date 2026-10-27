"""Fit the implied meeting path on intraday snapshots.

The fit itself is `sofr_pricing.fit_meeting_moves`. This module only
chooses the prices, the anchor and the meeting list.

Anchor. The policy rate is the target-range midpoint in force on the
morning of the announcement, from the team's decision table
(`policy_level_on(..., after_announcement=False)`). That is the same
anchor `fit_many` uses. When the team's daily SOFR series is available,
the SOFR-minus-policy basis is `estimate_basis` on the fixings the
market could already have seen (SOFR is published the next business
morning), and those fixings are spliced into the path.

Today's meeting. The daily estimator drops a meeting announced ON the
observation date, because the settlement is after the statement. Here
both the 13:55 book and the post-statement book are asked what move
they imply for today, so today's meeting stays in the unknown list.
See `estimator_meeting_dates`. The announced decision is NOT inserted
as a known move: the change from pre to post is the market's repricing,
not the mechanical substitution of the decision.

Contract set. Only contracts that have already traded by the 13:55
snapshot are used at every later time. A contract that prints for the
first time after the statement would change which meetings the strip
can see, and that would look like a repricing. Quiet contracts keep
their last pre-statement trade (see `select_snapshot`).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fomc_intraday.events import estimator_meeting_dates, estimator_obs_date
from fomc_intraday.snapshots import select_snapshot, to_contract_table
from fomc_intraday.windows import announcement_window, minute_grid, snapshot_label
from sofr_pricing import (
    estimate_basis,
    fit_meeting_moves,
    fixing_dates,
    last_known_fixing_date,
    policy_level_on,
)

# The minute path reported for the talk: this meeting and the two after it.
MINUTE_HORIZONS = (1, 2, 3)


def _sofr_series(sofr):
    """A Series of SOFR percent, indexed by date, from a Series or a date/sofr frame."""
    if isinstance(sofr, pd.Series):
        series = sofr.copy()
    else:
        frame = sofr.copy()
        if "date" not in frame.columns or "sofr" not in frame.columns:
            raise ValueError("SOFR table needs columns date and sofr")
        series = frame.set_index("date")["sofr"]
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series.sort_index().astype(float)


def market_anchor(announcement_date, decisions, sofr=None, n_fixings=20, holidays=()):
    """Pre-announcement policy anchor and, if SOFR is passed, the basis.

    Returns `(anchor_percent, basis_percent)`. Without `sofr` the basis
    is 0, which is what the synthetic check uses.

    The basis window ends at the last fixing published by the announcement
    morning, not at the announcement date itself. The announcement-day
    SOFR print is not out yet at 14:00.
    """
    day = pd.Timestamp(announcement_date).normalize()
    anchor = float(policy_level_on(day, decisions, after_announcement=False))
    if sofr is None:
        return anchor, 0.0

    fixings = _sofr_series(sofr)
    calendar = fixing_dates(day - pd.Timedelta(days=14), day, holidays)
    known = last_known_fixing_date(day, calendar)
    basis = float(estimate_basis(fixings, decisions, known, n_fixings=n_fixings))
    return anchor, basis


def _price_key(table):
    """Identity of a price snapshot. Equal keys share one fit."""
    ordered = table.sort_values("contract_id")
    return tuple(
        (row.contract_id, round(float(row.settlement_price), 10))
        for row in ordered.itertuples(index=False)
    )


def _meetings_table(result, anchor):
    """Fit meetings with horizon 1 = the nearest meeting (the announcement)."""
    meetings = result.meetings.copy()
    meetings["meeting_date"] = pd.to_datetime(meetings["meeting_date"]).dt.normalize()
    meetings["effective_date"] = pd.to_datetime(meetings["effective_date"]).dt.normalize()
    meetings = meetings.sort_values("meeting_date").reset_index(drop=True)
    meetings["horizon"] = np.arange(1, len(meetings) + 1)
    meetings["implied_rate_percent"] = anchor + meetings["implied_cum_change_bps"] / 100.0
    return meetings


@dataclass
class EventStudy:
    """Tables for one announcement.

    snapshots: one row per (snapshot, meeting), levels and the change
        from the 13:55 snapshot.
    minutes: one row per (minute, horizon) for the next few meetings.
    diagnostics: one row per snapshot (fit quality, contract count).
    """

    snapshots: pd.DataFrame
    minutes: pd.DataFrame
    diagnostics: pd.DataFrame


def run_event_study(
    bars,
    announcement_date,
    meeting_dates,
    anchor,
    basis=0.0,
    realized_fixings=None,
    holidays=(),
    minute_horizons=MINUTE_HORIZONS,
    label=None,
):
    """Pre/post paths and a minute path for one announcement.

    `bars` are minute bars for this announcement (see `prepare_bars` for
    the columns). `anchor` is in percent. `meeting_dates` must include
    the announcement and every later meeting the strip can reach; pass
    the team calendar.
    """
    day = pd.Timestamp(announcement_date).normalize()
    if day not in {pd.Timestamp(meeting).normalize() for meeting in meeting_dates}:
        raise ValueError(f"{day.date()} is not in meeting_dates; today's move would be missed")

    window = announcement_window(day)
    day_bars = bars
    if "announcement_date" in bars.columns:
        dates = pd.to_datetime(bars["announcement_date"]).dt.tz_localize(None).dt.normalize()
        day_bars = bars.loc[dates == day]
    if day_bars.empty:
        raise ValueError(f"no minute bars for {day.date()}")

    pre_rows = select_snapshot(day_bars, window["pre_snapshot"])
    if pre_rows.empty:
        raise ValueError(f"no trades at or before 13:55 Eastern on {day.date()}")
    universe = set(pre_rows["contract_id"])

    obs_date = estimator_obs_date(day)
    schedule = estimator_meeting_dates(day, meeting_dates)
    cache = {}

    def fit_at(when):
        # None means the 13:55 strip is not all printed yet. Later minutes
        # carry those prices forward, so this only happens before 13:55.
        snapshot = select_snapshot(day_bars, when)
        snapshot = snapshot.loc[snapshot["contract_id"].isin(universe)]
        if set(snapshot["contract_id"]) != universe:
            return None
        table = to_contract_table(snapshot)
        key = _price_key(table)
        if key not in cache:
            try:
                result = fit_meeting_moves(
                    obs_date,
                    table,
                    schedule,
                    anchor,
                    basis=basis,
                    realized_fixings=realized_fixings,
                    holidays=holidays,
                )
            except ValueError as error:
                raise ValueError(f"{day.date()}: {error}") from error
            cache[key] = (result, len(table))
        return cache[key]

    snapshot_times = [window["pre_snapshot"], *window["post_snapshots"]]
    fitted = []
    diagnostic_rows = []
    for when in snapshot_times:
        fitted_one = fit_at(when)
        if fitted_one is None:
            raise ValueError(f"{day.date()}: the 13:55 contracts have no price at {when}")
        result, n_contracts = fitted_one
        label_name = snapshot_label(when, window["statement"])
        meetings = _meetings_table(result, anchor)
        meetings.insert(0, "snapshot", label_name)
        meetings.insert(0, "snapshot_time", pd.Timestamp(when))
        fitted.append(meetings)
        diagnostic_rows.append({
            "announcement_date": day,
            "label": label,
            "snapshot": label_name,
            "n_contracts": n_contracts,
            **result.diagnostics,
        })

    snapshots = pd.concat(fitted, ignore_index=True)
    pre = snapshots.loc[snapshots["snapshot"] == snapshot_label(window["pre_snapshot"], window["statement"])]
    pre_cum = pre.set_index("meeting_date")["implied_cum_change_bps"]
    snapshots["delta_cum_bps"] = [
        float(cum - pre_cum.loc[meeting])
        for meeting, cum in zip(snapshots["meeting_date"], snapshots["implied_cum_change_bps"])
    ]
    snapshots.insert(0, "label", label)
    snapshots.insert(0, "announcement_date", day)
    snapshots.insert(0, "anchor_percent", float(anchor))
    snapshots.insert(0, "basis_percent", float(basis))

    minute_rows = []
    horizon_limit = max(minute_horizons) if minute_horizons else 0
    for when in minute_grid(window):
        fitted_one = fit_at(when)
        if fitted_one is None:
            continue
        result, _ = fitted_one
        meetings = _meetings_table(result, anchor)
        kept = meetings.loc[meetings["horizon"] <= horizon_limit]
        minutes_from = int(round((pd.Timestamp(when) - window["statement"]).total_seconds() / 60.0))
        for row in kept.itertuples(index=False):
            minute_rows.append({
                "announcement_date": day,
                "label": label,
                "timestamp_et": pd.Timestamp(when),
                "minutes_from_statement": minutes_from,
                "horizon": int(row.horizon),
                "meeting_date": row.meeting_date,
                "implied_move_bps": float(row.implied_move_bps),
                "implied_cum_change_bps": float(row.implied_cum_change_bps),
                "implied_rate_percent": float(row.implied_rate_percent),
            })

    minutes = pd.DataFrame(minute_rows)
    diagnostics = pd.DataFrame(diagnostic_rows)
    return EventStudy(snapshots, minutes, diagnostics)


# splice_realized / the pricer raise these when the published SOFR series
# does not reach back to the front contract's first day. The team's SOFR
# file starts on 2022-01-03, and the January 2022 SR1 month starts on
# 2022-01-01, so 2022-01-26 hits the first of these.
_UNCOVERED_FIXINGS = (
    "fixings start",
    "no realized fixings on or before",
)


def fit_announcement(
    bars,
    announcement_date,
    meeting_dates,
    anchor,
    basis=0.0,
    realized_fixings=None,
    **kwargs,
):
    """Fit one announcement, and drop the SOFR splice when it cannot cover the strip.

    The intraday change is read from futures prices. Published SOFR only
    fills the days of an in-progress contract that are already fixed. If
    that series starts after the front contract's first day, splicing it
    makes the pricer refuse the strip. This fits the same snapshots again
    with no splice. The basis the caller passed is unchanged. A failure
    for any other reason is raised.
    """
    try:
        return run_event_study(
            bars,
            announcement_date,
            meeting_dates,
            anchor,
            basis=basis,
            realized_fixings=realized_fixings,
            **kwargs,
        )
    except ValueError as error:
        uncovered = realized_fixings is not None and any(
            phrase in str(error) for phrase in _UNCOVERED_FIXINGS
        )
        if not uncovered:
            raise
        return run_event_study(
            bars,
            announcement_date,
            meeting_dates,
            anchor,
            basis=basis,
            realized_fixings=None,
            **kwargs,
        )


def load_team_rates(processed_dir=None):
    """Read the daily SOFR series and FOMC decisions the team already collects.

    Those files are written by `scripts/fetch_rate_data.py` (New York Fed
    and FRED, no Databento key) into `data/processed/`. Returns
    `(decisions, sofr_series)`. Raises FileNotFoundError if either file
    is missing, so a real-data run fails with a pointer at the fetch
    script instead of a stack trace about a column.
    """
    from fomc_data.config import FOMC_CSV, SOFR_CSV

    if processed_dir is None:
        fomc_path, sofr_path = FOMC_CSV, SOFR_CSV
    else:
        directory = Path(processed_dir)
        fomc_path = directory / "fomc_meetings.csv"
        sofr_path = directory / "sofr_daily.csv"
    missing = [str(path) for path in (fomc_path, sofr_path) if not path.exists()]
    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(
            f"Daily SOFR and FOMC decisions are not on disk ({joined}). "
            "Run python scripts/fetch_rate_data.py first. That pull does not need a Databento key."
        )
    decisions = pd.read_csv(fomc_path)
    decisions["meeting_date"] = pd.to_datetime(decisions["meeting_date"])
    sofr = pd.read_csv(sofr_path)
    sofr["date"] = pd.to_datetime(sofr["date"])
    series = sofr.set_index("date")["sofr"].astype(float).sort_index()
    return decisions, series


def stack_studies(studies):
    """Concatenate a list of `EventStudy` into three tables."""
    return (
        pd.concat([study.snapshots for study in studies], ignore_index=True),
        pd.concat([study.minutes for study in studies], ignore_index=True),
        pd.concat([study.diagnostics for study in studies], ignore_index=True),
    )
