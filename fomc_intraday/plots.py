"""Figures for the intraday event study.

(a) The implied cumulative path, minute by minute, for a few
    announcements. A vertical line marks the 14:00 statement and a
    dashed line marks the 14:30 press conference.
(b) The announcement-day change by meeting horizon: window-end path
    minus the 13:55 path, for every announcement in the sample.

The caller saves the figure (`fig.savefig(...)`). Titles say "synthetic
check" when the bars were generated rather than observed, so a chart
cannot be read as a historical market reaction by accident.
"""

import matplotlib.pyplot as plt


def _name_column(frame):
    if "label" in frame.columns and frame["label"].notna().any():
        return "label"
    return "announcement_date"


def plot_repricing_paths(
    minutes,
    synthetic=False,
    horizons=(1, 2, 3),
):
    """One panel per announcement: cumulative implied change (bp) vs minutes."""
    frame = minutes.copy()
    frame = frame.loc[frame["horizon"].isin(horizons)]
    if frame.empty:
        raise ValueError("no minute rows to plot")

    name = _name_column(frame)
    panels = list(frame.groupby(name, sort=False))
    fig, axes = plt.subplots(
        len(panels), 1, figsize=(10.5, 3.3 * len(panels)), sharex=True, squeeze=False,
    )

    for axis, (panel_name, panel) in zip(axes[:, 0], panels):
        for horizon, group in panel.groupby("horizon"):
            ordered = group.sort_values("minutes_from_statement")
            axis.plot(
                ordered["minutes_from_statement"],
                ordered["implied_cum_change_bps"],
                linewidth=1.6,
                label=f"Horizon {int(horizon)}",
            )
        axis.axvline(0, color="black", linewidth=0.9)
        axis.axvline(30, color="0.45", linewidth=0.9, linestyle="--")
        axis.axhline(0, color="0.6", linewidth=0.6)
        axis.set_ylabel("Implied cumulative change (bp)")
        axis.set_title(str(panel_name))
        axis.grid(axis="y", alpha=0.3)
        axis.legend(loc="best", fontsize=8)
        top = axis.get_ylim()[1]
        axis.text(0.4, top, "statement", va="top", ha="left", fontsize=8, color="black")
        axis.text(30.4, top, "press conf.", va="top", ha="left", fontsize=8, color="0.35")

    axes[-1, 0].set_xlabel("Minutes from the 14:00 Eastern statement")
    title = "Implied policy path around the FOMC statement"
    if synthetic:
        title = "Synthetic check: " + title
    fig.suptitle(title)
    fig.tight_layout()
    return fig


def plot_change_by_horizon(
    snapshots,
    snapshot="post_1600",
    synthetic=False,
    max_horizon=6,
):
    """Announcement-day change in the cumulative path, by horizon.

    `snapshot` is the post time the change is measured to. The default,
    `post_1600`, is the end of the two-hour window (after the press
    conference). The change is already on the snapshot table as
    `delta_cum_bps` (that snapshot minus 13:55).
    """
    frame = snapshots.copy()
    frame = frame.loc[frame["snapshot"] == snapshot]
    frame = frame.loc[frame["horizon"] <= max_horizon]
    if frame.empty:
        raise ValueError(f"no rows for snapshot {snapshot}")

    name = _name_column(frame)
    fig, axis = plt.subplots(figsize=(8.5, 4.8))
    grouped = list(frame.groupby(name, sort=False))
    # A full sample is a few dozen lines. A legend entry for each one
    # covers the chart. The table next to the figure names every date.
    label_each = len(grouped) <= 8
    for panel_name, panel in grouped:
        ordered = panel.sort_values("horizon")
        axis.plot(
            ordered["horizon"],
            ordered["delta_cum_bps"],
            marker="o",
            linewidth=1.2 if label_each else 1.0,
            alpha=1.0 if label_each else 0.75,
            label=str(panel_name) if label_each else None,
        )
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set_xlabel("Meeting horizon (1 = the meeting being announced)")
    axis.set_ylabel("Change in implied cumulative policy rate (bp)")
    axis.set_xticks(sorted(frame["horizon"].unique()))
    axis.grid(axis="y", alpha=0.3)
    if label_each:
        axis.legend(loc="best", fontsize=8)
    else:
        axis.text(
            0.01, 0.01, "Each line is one announcement. Names are in the table.",
            transform=axis.transAxes, fontsize=8, color="0.25", va="bottom",
        )
    clock = snapshot.removeprefix("post_").removeprefix("pre_")
    pretty = f"{clock[:2]}:{clock[2:]}" if len(clock) == 4 and clock.isdigit() else snapshot
    title = f"Announcement-day change by horizon ({pretty} minus 13:55 Eastern)"
    if synthetic:
        title = "Synthetic check: " + title
    axis.set_title(title)
    fig.tight_layout()
    return fig


def snapshot_change_table(snapshots, snapshot="post_1600", max_horizon=6):
    """Small table of the change by horizon, for the report next to figure (b)."""
    frame = snapshots.loc[snapshots["snapshot"] == snapshot].copy()
    frame = frame.loc[frame["horizon"] <= max_horizon]
    columns = [
        "announcement_date", "label", "horizon", "meeting_date",
        "implied_move_bps", "implied_cum_change_bps", "delta_cum_bps",
        "implied_rate_percent",
    ]
    keep = [column for column in columns if column in frame.columns]
    ordered = frame.sort_values(["announcement_date", "horizon"])
    return ordered.loc[:, keep].reset_index(drop=True)
