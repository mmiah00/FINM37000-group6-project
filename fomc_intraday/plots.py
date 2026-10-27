"""Figures for the intraday event study.

(a) The implied cumulative path, minute by minute, for a few
    announcements. A vertical line marks the 14:00 statement and a
    dashed line marks the 14:30 press conference.
(b) The announcement-day change by meeting horizon: window-end path
    minus the 13:55 path, for every announcement in the sample.
(c) Fitted repricing against the announced surprise, one point per
    announcement: a check that the fit recovers the news (real runs only).
(d) Mean absolute change in each clock window around the statement, by
    horizon: how fast and how large the repricing is across the sample.

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


def plot_surprise_check(summary, tolerance_bps=2.0):
    """Fitted repricing against the announced surprise, one point per afternoon.

    The x axis is the news with no fit on the announced side: the announced move
    minus what the 13:55 book had priced. The y axis is what the study reports,
    the fitted level at 16:00 minus the fitted level at 13:55. Points on the
    diagonal are afternoons where the fit recovered the news. A point off the
    band is fit error, not a market reaction, and is labelled.
    """
    fig, axis = plt.subplots(figsize=(6.8, 6.2))
    usable = summary.loc[summary["flag"] == ""]
    flagged = summary.loc[summary["flag"] != ""]

    span = max(float(summary["surprise"].abs().max()), float(summary["repricing"].abs().max()), 1.0) * 1.1
    axis.plot([-span, span], [-span, span], color="0.3", linewidth=1.0, label="fit equals the surprise")
    axis.fill_between(
        [-span, span], [-span - tolerance_bps, span - tolerance_bps], [-span + tolerance_bps, span + tolerance_bps],
        color="0.5", alpha=0.15, label=f"within {tolerance_bps:g} bp",
    )
    axis.scatter(usable["surprise"], usable["repricing"], s=36, color="tab:blue", zorder=3, label="usable afternoon")
    axis.scatter(
        flagged["surprise"], flagged["repricing"], s=52, facecolors="none", edgecolors="tab:red",
        linewidths=1.6, zorder=3, label="flagged (fit error or not identified)",
    )
    for index, row in enumerate(flagged.sort_values("surprise").itertuples(index=False)):
        #alternate above and below so labels of nearby points do not overlap.
        offset = (6, 8) if index % 2 else (6, -12)
        axis.annotate(str(row.label), (row.surprise, row.repricing), textcoords="offset points", xytext=offset, fontsize=7)
    axis.axhline(0, color="0.7", linewidth=0.6)
    axis.axvline(0, color="0.7", linewidth=0.6)
    axis.set_xlim(-span, span)
    axis.set_ylim(-span, span)
    axis.set_aspect("equal")
    axis.set_xlabel("Surprise: announced move minus the 13:55 book (bp)")
    axis.set_ylabel("Fitted repricing: 16:00 minus 13:55 (bp)")
    axis.set_title("Does the fitted repricing recover the announced surprise?")
    axis.grid(alpha=0.3)
    axis.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    return fig


def plot_repricing_windows(window_table, synthetic=False):
    """Mean absolute change in each clock window, by horizon: how fast and how large.

    `window_table` is `fomc_intraday.evaluation.window_summary`. Absolute values, so
    afternoons that move in opposite directions are not averaged away.
    """
    if window_table.empty:
        raise ValueError("no window rows to plot")
    windows = list(dict.fromkeys(window_table["window"]))
    horizons = sorted(window_table["horizon"].unique())
    height = 0.8 / len(horizons)

    fig, axis = plt.subplots(figsize=(9.5, 4.6))
    for offset, horizon in enumerate(horizons):
        rows = window_table.loc[window_table["horizon"] == horizon].set_index("window").reindex(windows)
        positions = [index + offset * height for index in range(len(windows))]
        bars = axis.barh(positions, rows["mean_abs_bps"], height=height * 0.92, label=f"Horizon {int(horizon)}")
        axis.bar_label(bars, fmt="%.1f", padding=2, fontsize=7)
    axis.set_yticks([index + height * (len(horizons) - 1) / 2 for index in range(len(windows))])
    axis.set_yticklabels(windows, fontsize=8)
    axis.invert_yaxis()
    axis.set_xlim(0, float(window_table["mean_abs_bps"].max()) * 1.18)  # room for the value label of the longest bar
    axis.set_xlabel("Mean absolute change in the implied cumulative path (bp)")
    n_events = int(window_table["n_events"].max())
    title = f"Where the repricing happens, around the 14:00 statement ({n_events} announcements)"
    if synthetic:
        title = "Synthetic check: " + title
    axis.set_title(title, fontsize=10)
    axis.grid(axis="x", alpha=0.3)
    axis.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    return fig
