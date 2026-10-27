"""Checks and summaries on top of the event-study tables (Issue #8).

The event study reports what the futures book implies before and after each
statement. This module answers three questions the raw tables leave open.

1. Can the fitted number be trusted on a given afternoon?
   After the statement, today's move is no longer a forecast: the Fed has just
   announced it. So the fitted horizon-1 level at 16:00 should equal the
   announced change. Any gap is fit error, most often a SOFR-minus-policy basis
   that moved during the day, because the study holds the basis fixed.
   `announcement_summary` puts the announced move beside the fitted levels and
   flags days where the fit misses it.

2. Which afternoons are worth showing?
   Ranking afternoons by the largest fitted horizon-1 change picks up fit error
   as readily as news. `select_headline_events` ranks by the true surprise
   (announced move minus what the 13:55 book had priced) and leaves out flagged
   days.

3. How fast and how large is the repricing across the whole sample?
   `window_changes` and `window_summary` split each afternoon into the minutes
   around the statement and the press conference, and `horizon_summary` gives
   the size of the change at each meeting ahead.

Minute labels follow the study: minute 0 is the last book that traded before the
statement, the statement book appears at minute 1, and the press-conference book
at minute 31 (a one-minute bar is known only when it ends).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PRE_SNAPSHOT = "pre_1355"
FINAL_SNAPSHOT = "post_1600"

# A closing error larger than this is treated as fit error, not as news. The mean
# closing error on the 2022-2026 sample is about 1 bp, so 2 bp is roughly twice
# the usual miss.
TOLERANCE_BPS = 2.0

# (name, first minute, last minute) around the 14:00 statement. The change in a
# window is the level at its last minute minus the level at its first.
WINDOWS = (
    ("pre-statement drift (13:55 to 14:00)", -5, 0),
    ("statement minute (14:00 to 14:01)", 0, 1),
    ("digesting the statement (14:01 to 14:30)", 1, 30),
    ("press conference minute (14:30 to 14:31)", 30, 31),
    ("after the press conference (14:31 to 16:00)", 31, 120),
)
WINDOW_NAMES = tuple(name for name, _, _ in WINDOWS)


def _snapshot_levels(snapshots):
    """Horizon-1 implied cumulative change at each snapshot, one row per afternoon."""
    today = snapshots.loc[snapshots["horizon"] == 1].copy()
    today["announcement_date"] = pd.to_datetime(today["announcement_date"]).dt.normalize()
    wide = today.groupby(["announcement_date", "label", "snapshot"])["implied_cum_change_bps"].first().unstack("snapshot")
    for needed in (PRE_SNAPSHOT, FINAL_SNAPSHOT):
        if needed not in wide.columns:
            raise ValueError(f"snapshots have no {needed} rows, so the closing check cannot be made")
    return wide


def announcement_summary(snapshots, diagnostics, decisions, tolerance_bps=TOLERANCE_BPS):
    """One row per afternoon: what was priced, what was announced, and how well the fit closed.

    Args:
        snapshots: The study's snapshot table (`EventStudy.snapshots`, stacked).
        diagnostics: The study's fit diagnostics (stacked), with `fully_identified`.
        decisions: Realized decisions with `meeting_date` and `change_bps`, in basis
            points. The team's `fomc_meetings.csv` has these columns.
        tolerance_bps: Closing errors larger than this are flagged.

    Returns:
        A DataFrame with these columns, all in basis points unless noted:

        - `priced_1355`: horizon-1 level at 13:55, what the book had priced for today.
        - `level_1415`, `level_1445`, `level_1600`: the same level later in the afternoon.
        - `announced`: the change the Fed announced.
        - `surprise`: `announced - priced_1355`. News, with no fit on the announced side.
        - `repricing`: `level_1600 - priced_1355`. The fitted change the study reports.
        - `closing_error`: `level_1600 - announced`. Should be near zero.
        - `identified`: whether the 16:00 fit was full rank.
        - `flag`: empty when the day is usable, otherwise the reason it is not.

    Raises:
        ValueError: If an afternoon has no announced decision in `decisions`.
    """
    wide = _snapshot_levels(snapshots)
    out = pd.DataFrame(
        {
            "priced_1355": wide[PRE_SNAPSHOT],
            "level_1415": wide.get("post_1415", np.nan),
            "level_1445": wide.get("post_1445", np.nan),
            "level_1600": wide[FINAL_SNAPSHOT],
        }
    ).reset_index()

    announced = decisions.assign(meeting_date=pd.to_datetime(decisions["meeting_date"]).dt.normalize())
    announced = announced.drop_duplicates("meeting_date").set_index("meeting_date")["change_bps"].astype(float)
    out["announced"] = out["announcement_date"].map(announced)
    missing = out.loc[out["announced"].isna(), "announcement_date"]
    if len(missing):
        shown = ", ".join(day.date().isoformat() for day in missing[:5])
        raise ValueError(f"no announced decision for {shown}")

    out["surprise"] = out["announced"] - out["priced_1355"]
    out["repricing"] = out["level_1600"] - out["priced_1355"]
    out["closing_error"] = out["level_1600"] - out["announced"]

    identified = diagnostics.loc[diagnostics["snapshot"] == FINAL_SNAPSHOT].set_index("label")["fully_identified"].astype(bool)
    out["identified"] = out["label"].map(identified).fillna(False).astype(bool)

    def reason(row):
        reasons = []
        if not row["identified"]:
            reasons.append("not fully identified")
        if abs(row["closing_error"]) > tolerance_bps:
            reasons.append(f"closing error above {tolerance_bps:g} bp")
        return "; ".join(reasons)

    out["flag"] = out.apply(reason, axis=1)
    return out.sort_values("announcement_date").reset_index(drop=True)


def noise_floor(summary):
    """Mean absolute closing error over the usable-or-not afternoons, in bp.

    A repricing smaller than this cannot be told apart from fit error.
    """
    return float(summary["closing_error"].abs().mean())


def select_headline_events(summary, n=3):
    """Labels of the afternoons with the largest true surprise among the usable ones.

    Usable means fully identified and closing within tolerance (`flag` is empty).
    Ranking by `surprise` rather than by the fitted change keeps a fit error from
    being presented as news.
    """
    usable = summary.loc[summary["flag"] == ""].copy()
    usable["size"] = usable["surprise"].abs()
    return list(usable.sort_values("size", ascending=False)["label"].head(n))


def horizon_summary(snapshots, snapshot=FINAL_SNAPSHOT, max_horizon=6):
    """Size of the change at each meeting ahead, 13:55 to the chosen snapshot.

    Returns one row per horizon with the number of afternoons, the mean change, the
    mean and median absolute change, and the largest absolute change, in bp.
    """
    frame = snapshots.loc[(snapshots["snapshot"] == snapshot) & (snapshots["horizon"] <= max_horizon)]
    grouped = frame.groupby("horizon")["delta_cum_bps"]
    return pd.DataFrame(
        {
            "n_events": grouped.size(),
            "mean_bps": grouped.mean(),
            "mean_abs_bps": grouped.apply(lambda values: values.abs().mean()),
            "median_abs_bps": grouped.apply(lambda values: values.abs().median()),
            "max_abs_bps": grouped.apply(lambda values: values.abs().max()),
        }
    )


def window_changes(minutes, horizons=(1, 2, 3)):
    """Change in each horizon's implied cumulative path inside each window, per afternoon.

    Args:
        minutes: The study's minute table (`EventStudy.minutes`, stacked) with
            `label`, `horizon`, `minutes_from_statement` and `implied_cum_change_bps`.
        horizons: Horizons to keep.

    Returns:
        A long DataFrame: `label`, `horizon`, `window`, `change_bps`. A window is
        NaN when the afternoon is missing a minute at either end of it.
    """
    frame = minutes.loc[minutes["horizon"].isin(horizons)]
    levels = frame.pivot_table(
        index=["label", "horizon"], columns="minutes_from_statement",
        values="implied_cum_change_bps", aggfunc="first",
    )
    rows = []
    for (label, horizon), path in levels.iterrows():
        for name, start, end in WINDOWS:
            change = path.get(end, np.nan) - path.get(start, np.nan)
            rows.append({"label": label, "horizon": int(horizon), "window": name, "change_bps": float(change)})
    return pd.DataFrame(rows)


def window_summary(changes):
    """Across afternoons: mean and median absolute change per window and horizon, in bp.

    Absolute values, so a statement that moves one afternoon up and another down is
    not averaged away. Windows come back in clock order.
    """
    valid = changes.dropna(subset=["change_bps"]).copy()
    valid["abs_bps"] = valid["change_bps"].abs()
    table = valid.groupby(["horizon", "window"]).agg(
        n_events=("abs_bps", "size"),
        mean_abs_bps=("abs_bps", "mean"),
        median_abs_bps=("abs_bps", "median"),
    )
    table = table.reset_index()
    order = {name: position for position, name in enumerate(WINDOW_NAMES)}
    table["_order"] = table["window"].map(order)
    return table.sort_values(["horizon", "_order"]).drop(columns="_order").reset_index(drop=True)
