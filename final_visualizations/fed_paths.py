
"""
Plot market-implied Fed policy paths against realized policy rates.

Issue #7: Create final visualizations and analysis.

Inputs:
- errors: Output of forecast_eval.metrics.build_forecast_errors.
- decisions: Output of fomc_data.dataset.build_fomc_decisions.

Rates are in percent; cumulative changes and forecast errors are in bp.
"""

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from final_visualizations.style import COLORS


def plot_fed_paths(errors, decisions, obs_date):
    """
    Plot implied and realized policy rates for one observation date.

    Args:
    - errors (pd.DataFrame): Forecast evaluation results from Issue #5.
    - decisions (pd.DataFrame): Realized FOMC decisions from Issue #2.
    - obs_date: Date on which market forecasts were observed.

    Returns (matplotlib.figure.Figure): Implied vs. realized policy-rate chart.
    """
    obs_date = pd.Timestamp(obs_date)

    #select forecasts made on the requested observation date.
    forecasts = errors.copy()
    forecasts["obs_date"] = pd.to_datetime(forecasts["obs_date"])
    forecasts["meeting_date"] = pd.to_datetime(forecasts["meeting_date"])
    forecasts = forecasts[forecasts["obs_date"] == obs_date].copy()

    if forecasts.empty:
        raise ValueError(f"No forecasts available for {obs_date.date()}")

    forecasts = forecasts.sort_values("meeting_date")

    #identify the policy rate in force at the observation date.
    decisions = decisions.copy()
    decisions["meeting_date"] = pd.to_datetime(decisions["meeting_date"])
    decisions = decisions.sort_values("meeting_date")

    past = decisions[decisions["meeting_date"] <= obs_date]

    if past.empty:
        raise ValueError("No realized policy rate available before observation date")

    latest = past.iloc[-1]

    anchor = (latest["target_lower_after"] + latest["target_upper_after"]) / 2.0

    #convert cumulative changes (bp) into absolute policy rates (%).
    forecasts["implied_rate"] = (anchor + forecasts["implied_cum_bps"] / 100.0)

    forecasts["realized_rate"] = (anchor + forecasts["realized_cum_bps"] / 100.0)

    #include the observation-date anchor.
    dates = [obs_date] + forecasts["meeting_date"].tolist()
    implied = [anchor] + forecasts["implied_rate"].tolist()
    realized = [anchor] + forecasts["realized_rate"].tolist()

    #plot both paths.
    fig, ax = plt.subplots(figsize = (10, 5))

    ax.step(dates, realized, where = "post", color = COLORS["navy"], linewidth = 2.5, label = "Realized Fed policy rate")
    ax.step(dates, implied, where = "post", color = COLORS["blue"], linewidth = 2.2, linestyle = "--", label = "Market-implied policy rate")

    #shade the forecast discrepancy at each interval.
    ax.fill_between(dates, implied, realized, step = "post", color = COLORS["blue"], alpha = 0.12)

    ax.set_title("Market-Implied vs. Realized Fed Policy Path", fontsize = 14, fontweight = "semibold", pad = 28)
    ax.text(0.5, 1.015, f"Forecast as of {pd.Timestamp(obs_date):%B %d, %Y}", transform = ax.transAxes, ha = "center", va = "bottom", fontsize = 10, color = COLORS["gray"])

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))

    ax.set_xlabel("Date")
    ax.set_ylabel("Fed target midpoint (%)")
    ax.tick_params(axis = "x", rotation = 0)

    ax.grid(axis = "y", alpha = 0.3)
    ax.legend(loc = "upper right")

    fig.tight_layout()

    return fig
