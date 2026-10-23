"""Real SR1 settlements, daily SOFR, and realized policy decisions.

Nothing here contacts Databento or the network, and nothing here reads an
API key. The files are the ones the team's own scripts already write:

- SR1 settlements: `sofr_data.load_settlements` on
  `data/processed/sofr_futures_settlements.parquet`, built by
  `python -m scripts.fetch_sofr_futures` (that script is what reads
  `DATABENTO_API_KEY` or `~/.databento_api_key`).
- Daily SOFR: `data/processed/sofr_daily.csv`, the NY Fed fixings written by
  `python -m scripts.fetch_rate_data`. This is the anchor and the elapsed
  part of each SR1 month. It is not the forecast target.
- Realized policy: `data/processed/fomc_meetings.csv` from the same script.
  The target-range midpoint (FRED DFEDTARL / DFEDTARU) is the policy path,
  and `change_bps` is what `forecast_eval` treats as the truth.
- Meeting dates: `fomc_data`'s bundled calendar, checked against that file.

Tests build a `RealWorld` from in-memory frames via `world_from_frames` and
do not need these files.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from curve_compare.calendar import meeting_calendar
from fomc_data.clean import validate_fomc_decisions, validate_sofr
from fomc_data.config import FOMC_CSV, SOFR_CSV
from sofr_data.config import SETTLEMENTS_PARQUET
from sofr_data.dataset import load_settlements
from sofr_pricing.fixing_calendar import MAX_CARRY_DAYS

_SR1_BUILD = "python -m scripts.fetch_sofr_futures"
_RATES_BUILD = "python -m scripts.fetch_rate_data"


@dataclass
class RealWorld:
    """One real sample, shaped so `curve_compare.compare` can score it.

    `fix_basis` tells the scorer to subtract `sofr_pricing.estimate_basis`
    instead of a known synthetic spread. `obs_dates` are the trade dates that
    have an SR1 strip and a next meeting with a realized outcome.
    """

    meeting_dates: list
    decisions: pd.DataFrame
    daily_sofr: pd.Series
    sr1_panel: pd.DataFrame
    true_policy: pd.Series
    obs_dates: pd.DatetimeIndex
    fix_basis: bool = True

    def move_at(self, meeting_date):
        """Realized target-midpoint change at `meeting_date`, in bp, or 0."""
        moves = self.decisions.set_index("meeting_date")["change_bps"]
        key = pd.Timestamp(meeting_date).normalize()
        if key not in moves.index:
            return 0.0
        value = moves.loc[key]
        return float(value)


def _missing(path, command):
    return FileNotFoundError(f"{path} not found.\nBuild it with:\n    {command}")


def _read_settlements(path):
    """SR1 rows from the team panel. The default path goes through `sofr_data`."""
    if path is None:
        return load_settlements(roots=("SR1",))
    path = Path(path)
    if not path.exists():
        raise _missing(path, _SR1_BUILD)
    panel = pd.read_parquet(path)
    if "root" in panel.columns:
        panel = panel.loc[panel["root"] == "SR1"].copy()
    return panel


def _read_sofr(path):
    path = SOFR_CSV if path is None else Path(path)
    if not Path(path).exists():
        raise _missing(path, _RATES_BUILD)
    return validate_sofr(pd.read_csv(path))


def _read_decisions(path):
    path = FOMC_CSV if path is None else Path(path)
    if not Path(path).exists():
        raise _missing(path, _RATES_BUILD)
    frame = pd.read_csv(path)
    for column in ("meeting_date", "effective_date"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column])
    return validate_fomc_decisions(frame)


def load_real_world(settlements_path=None, sofr_path=None, decisions_path=None):
    """Load a `RealWorld` from processed files.

    Pass a path to read that file instead of the team default. Missing files
    raise `FileNotFoundError` naming the script that builds them. Every
    missing input is reported together. This function does not fetch.
    """
    problems = []
    panel = sofr = decisions = None
    try:
        panel = _read_settlements(settlements_path)
    except FileNotFoundError as err:
        problems.append(str(err))
    try:
        sofr = _read_sofr(sofr_path)
    except FileNotFoundError as err:
        problems.append(str(err))
    try:
        decisions = _read_decisions(decisions_path)
    except FileNotFoundError as err:
        problems.append(str(err))
    if problems:
        raise FileNotFoundError("\n\n".join(problems))
    return world_from_frames(panel, sofr, decisions)


def _sr1_panel(settlements):
    """Map the PR #16 settlement columns onto the strip the fitter expects.

    `reference_start` / `reference_end` are kept as the contract window. Those
    columns already follow the SR1 calendar month, the same window
    `sofr_pricing.sr1_reference_period` uses. They are not recomputed here.
    """
    required = {"trade_date", "reference_start", "reference_end", "settlement_price"}
    missing = required - set(settlements.columns)
    if missing:
        raise ValueError(f"SR1 settlements are missing columns {sorted(missing)}")
    panel = settlements.copy()
    panel["trade_date"] = pd.to_datetime(panel["trade_date"]).dt.normalize()
    panel["month_start"] = pd.to_datetime(panel["reference_start"]).dt.normalize()
    panel["month_end"] = pd.to_datetime(panel["reference_end"]).dt.normalize()
    panel["price"] = pd.to_numeric(panel["settlement_price"], errors="coerce")
    panel = panel.dropna(subset=["trade_date", "month_start", "month_end", "price"])
    sort_columns = ["trade_date", "month_start"]
    if "settlement_is_final" in panel.columns:
        sort_columns.append("settlement_is_final")
    panel = panel.sort_values(sort_columns).drop_duplicates(
        ["trade_date", "month_start"], keep="last"
    )
    if panel.empty:
        raise ValueError("SR1 settlement panel has no priced contracts")
    return panel[["trade_date", "month_start", "month_end", "price"]].reset_index(drop=True)


def _policy_path(decisions, start, end):
    """Daily target-range midpoint. A meeting's new level applies on its announcement date."""
    ordered = decisions.sort_values("meeting_date")
    days = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D")
    first = ordered.iloc[0]
    level = (float(first["target_lower_before"]) + float(first["target_upper_before"])) / 2.0
    path = pd.Series(level, index=days, dtype=float)
    for row in ordered.itertuples(index=False):
        after = (float(row.target_lower_after) + float(row.target_upper_after)) / 2.0
        path.loc[path.index >= pd.Timestamp(row.meeting_date)] = after
    return path


def _scoreable_dates(panel, meeting_dates, sofr):
    """Trade dates with two live SR1 contracts, a covered next meeting, and a recent fixing."""
    kept = []
    last_meeting = meeting_dates[-1]
    for trade_date, day in panel.groupby("trade_date", sort=True):
        trade_date = pd.Timestamp(trade_date)
        if trade_date >= last_meeting:
            continue
        upcoming = [day_ for day_ in meeting_dates if day_ > trade_date]
        if not upcoming:
            continue
        next_meeting = upcoming[0]
        live = day.loc[day["month_end"] > trade_date]
        if len(live) < 2:
            continue
        covers = (live["month_start"] <= next_meeting) & (live["month_end"] >= next_meeting)
        if not covers.any():
            continue
        known = sofr.index[sofr.index <= trade_date]
        if len(known) == 0 or (trade_date - known[-1]).days > MAX_CARRY_DAYS - 1:
            continue
        kept.append(trade_date)
    return pd.DatetimeIndex(kept)


def world_from_frames(settlements, sofr, decisions):
    """Build a `RealWorld` from frames that already look like the processed files.

    `sofr` is a DataFrame with columns `date` and `sofr`, or a Series of
    rates indexed by date. `decisions` is a meeting table with the target
    bounds and `change_bps`. Meeting dates that are not on `fomc_data`'s
    calendar are rejected.
    """
    if isinstance(sofr, pd.Series):
        sofr_frame = sofr.rename("sofr").rename_axis("date").reset_index()
    else:
        sofr_frame = sofr
    sofr_frame = validate_sofr(sofr_frame)
    decisions = validate_fomc_decisions(decisions.copy())
    decisions["meeting_date"] = pd.to_datetime(decisions["meeting_date"]).dt.normalize()

    official = meeting_calendar()
    official_set = set(official)
    decision_dates = [pd.Timestamp(day).normalize() for day in decisions["meeting_date"]]
    unknown = [day for day in decision_dates if day not in official_set]
    if unknown:
        shown = ", ".join(day.date().isoformat() for day in unknown[:5])
        raise ValueError(f"decision table has meetings that are not on the fomc_data calendar: {shown}")
    span_start, span_end = min(decision_dates), max(decision_dates)
    meeting_dates = [day for day in official if span_start <= day <= span_end]
    missing = [day for day in meeting_dates if day not in set(decision_dates)]
    if missing:
        shown = ", ".join(day.date().isoformat() for day in missing[:5])
        raise ValueError(f"decision table is missing fomc_data meetings inside its span: {shown}")

    panel = _sr1_panel(settlements)
    daily = sofr_frame.set_index("date")["sofr"].astype(float).sort_index()
    daily.index = pd.to_datetime(daily.index).normalize()
    if daily.index.has_duplicates:
        raise ValueError("daily SOFR has duplicate dates")

    path_end = max(panel["month_end"].max(), span_end)
    true_policy = _policy_path(decisions, daily.index.min(), path_end)
    obs_dates = _scoreable_dates(panel, meeting_dates, daily)
    if len(obs_dates) == 0:
        raise ValueError("no trade date has an SR1 strip that covers a still-unrealized meeting")
    return RealWorld(
        meeting_dates=meeting_dates,
        decisions=decisions.reset_index(drop=True),
        daily_sofr=daily,
        sr1_panel=panel,
        true_policy=true_policy,
        obs_dates=obs_dates,
        fix_basis=True,
    )
