
"""
Identify notable FOMC forecast episodes for Issue #7.

Consumes forecast-error results from Issue #5.
Errors are in basis points (implied minus realized).
"""

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from final_visualizations.style import COLORS


def identify_notable_meetings(errors, horizon = 1, min_observations = 1):
    """
    Identify notable meetings using average forecast errors.

    Args:
    - errors (pd.DataFrame): Output of build_forecast_errors().
    - horizon (int): Number of meetings ahead to analyze.
    - min_observations (int): Minimum daily forecasts per meeting.

    Returns (pd.DataFrame): One row per selected notable meeting.
    """
    data = errors.loc[errors["horizon"] == horizon].copy()
    data["meeting_date"] = pd.to_datetime(data["meeting_date"])

    summary = (data.groupby("meeting_date")["error_bps"]
                   .agg(n_obs = "count", mean_error_bps = "mean", mae_bps = lambda x: x.abs().mean()))

    summary = summary[summary["n_obs"] >= min_observations]

    if summary.empty:
        raise ValueError("No meetings have enough forecasts")

    selections = {"Largest average absolute error": summary["mae_bps"].idxmax(),
                  "Smallest average absolute error": summary["mae_bps"].idxmin()}

    positive = summary[summary["mean_error_bps"] > 0]
    negative = summary[summary["mean_error_bps"] < 0]

    if not positive.empty:
        selections["Largest positive bias"] = (positive["mean_error_bps"].idxmax())

    if not negative.empty:
        selections["Largest negative bias"] = (negative["mean_error_bps"].idxmin())

    rows = []

    for label, meeting in selections.items():
        row = summary.loc[meeting].to_dict()
        row["meeting_date"] = meeting
        row["example"] = label
        rows.append(row)

    return pd.DataFrame(rows).set_index("example")


def plot_notable_meetings(notable):
    """
    Plot selected meeting-level forecast-error summaries.

    This summary plot is retained for compatibility with the
    existing figure-generation pipeline.
    """
    categories = [("Largest average absolute error", "mae_bps"),
                  ("Smallest average absolute error", "mae_bps"),
                  ("Largest positive bias", "mean_error_bps"),
                  ("Largest negative bias", "mean_error_bps"),]

    labels = []
    values = []
    dates = []

    for category, metric in categories:
        if category not in notable.index:
            continue

        row = notable.loc[category]

        labels.append(category)
        values.append(float(row[metric]))
        dates.append(pd.Timestamp(row["meeting_date"]).strftime("%b %d, %Y"))

    if not labels:
        raise ValueError("No notable meetings available to plot")

    #each bar now uses the statistic described by its label.
    colors = [COLORS["orange"] if value < 0 else COLORS["blue"] for value in values]

    fig, ax = plt.subplots(figsize = (11, 5))

    positions = range(len(labels))

    bars = ax.barh(positions, values, color = colors, height = 0.55,)

    ax.set_yticks(list(positions))
    ax.set_yticklabels([f"{label}\n({date})" for label, date in zip(labels, dates)])

    ax.invert_yaxis()
    ax.axvline(0, color = COLORS["gray"], linewidth = 1)

    ax.set_xlabel("Forecast error (bp)")
    ax.set_title("Notable FOMC Forecasting Episodes")
    ax.grid(axis = "x", alpha = 0.3)

    #display the numeric value at the end of each bar.
    for bar, value in zip(bars, values):
        x = bar.get_width()

        ax.annotate(f"{value:+.2f} bp" if value < 0 else f"{value:.2f} bp",
                    xy = (x, bar.get_y() + bar.get_height() / 2),
                    xytext = (5 if value >= 0 else -5, 0),
                    textcoords = "offset points",
                    ha = "left" if value >= 0 else "right",
                    va = "center",
                    fontsize = 9)

    ax.text(0.5, -0.15, "Historical forecasts; categories may refer to the same meeting. " "Some meetings have only one forecast.", 
            transform = ax.transAxes, ha = "center", fontsize = 9, color = COLORS["gray"])

    fig.tight_layout()

    return fig


def plot_meeting_event_study(errors, meeting_date, horizon = 1):
    """
    Plot forecast evolution before a selected FOMC meeting.

    Uses the cumulative implied and realized changes from Issue #5.
    """
    data = errors.copy()

    data["obs_date"] = pd.to_datetime(data["obs_date"])
    data["meeting_date"] = pd.to_datetime(data["meeting_date"])

    meeting_date = pd.Timestamp(meeting_date)

    data = data[(data["meeting_date"] == meeting_date) 
                & (data["horizon"] == horizon) 
                & (data["obs_date"] < meeting_date)].sort_values("obs_date")

    if data.empty:
        raise ValueError(f"No pre-meeting forecasts for {meeting_date.date()}")

    fig, ax = plt.subplots(figsize = (9, 5))

    ax.plot(data["obs_date"], data["implied_cum_bps"], color = COLORS["blue"], linewidth = 2, marker = "o", markersize = 4, label = "Market-implied cumulative change")

    realized = data["realized_cum_bps"]

    if realized.nunique() == 1:
        ax.axhline(realized.iloc[0], color = COLORS["navy"], linestyle = "--", linewidth = 2, label = "Realized cumulative change")
    else:
        ax.plot(data["obs_date"], realized, color = COLORS["navy"], linestyle = "--", linewidth = 2, label = "Realized cumulative change")

    ax.set_title(f"Market Expectations Before {meeting_date:%B %d, %Y}", fontsize = 14, fontweight = "semibold")

    ax.set_xlabel("Forecast observation date")
    ax.set_ylabel("Cumulative policy change (bp)")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    ax.grid(axis = "y", alpha = 0.3)
    ax.legend()

    fig.autofmt_xdate()
    fig.tight_layout()

    return fig
