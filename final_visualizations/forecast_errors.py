
"""
Final forecast-error visualizations for Issue #7.

Consumes the forecast-error DataFrame produced by Issue #5.
Rates and forecast errors are expressed in basis points.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from final_visualizations.style import COLORS


def plot_forecast_errors_by_horizon(errors):
    """
    Plot forecast-error distributions and accuracy by horizon.

    Args:
    - errors (pd.DataFrame): Output of forecast_eval.metrics.build_forecast_errors().
        Note: required columns: horizon, error_bps.

    Returns (matplotlib.figure.Figure): Two-panel forecast accuracy figure.
    """
    data = errors.copy()

    #summarize forecast accuracy at each horizon.
    summary = (data.groupby("horizon")["error_bps"]
                   .agg(bias_bps = "mean", mae_bps = lambda x: x.abs().mean(), rmse_bps = lambda x: np.sqrt((x**2).mean()),)
                   .sort_index())

    horizons = summary.index.to_numpy()

    fig, (ax_dist, ax_stats) = plt.subplots( 1, 2, figsize = (12, 4.5))

    #panel A: Distribution of forecast errors.
    samples = [data.loc[data["horizon"] == h, "error_bps"].dropna().to_numpy() for h in horizons]

    bp = ax_dist.boxplot(samples, 
                         positions = horizons,
                         whis = (5, 95),
                         showfliers = False,
                         patch_artist = True, 
                         widths = 0.5,
                         medianprops = {"color": COLORS["orange"], "linewidth": 2},
                         boxprops = {"color": COLORS["navy"], "linewidth": 1.5},
                         whiskerprops = {"color": COLORS["navy"]},
                         capprops = {"color": COLORS["navy"]})

    for box in bp["boxes"]:
        box.set_facecolor(COLORS["blue"])
        box.set_alpha(0.25)

    ax_dist.axhline(0, color = COLORS["gray"], linestyle = "--", linewidth = 1)
    ax_dist.set_xlabel("FOMC meetings ahead")
    ax_dist.set_ylabel("Forecast error (bp)")
    ax_dist.set_title("Forecast Error Distribution")
    ax_dist.grid(axis = "y", alpha = 0.3)

    #panel B: Forecast accuracy statistics.
    ax_stats.plot(horizons, summary["mae_bps"], color = COLORS["navy"], marker = "o", linewidth = 2, label = "MAE")
    ax_stats.plot(horizons, summary["rmse_bps"], color = COLORS["orange"], marker = "s", linewidth = 2, label = "RMSE")
    ax_stats.plot(horizons, summary["bias_bps"], color = COLORS["gray"], marker = "^", linestyle = "--", linewidth = 1.5, label = "Bias")

    ax_stats.axhline(0, color = COLORS["gray"], linewidth = 0.8)
    ax_stats.set_xlabel("FOMC meetings ahead")
    ax_stats.set_ylabel("Error metric (bp)")
    ax_stats.set_title("Forecast Accuracy Metrics by Horizon")
    ax_stats.set_xticks(horizons)
    ax_stats.legend()
    ax_stats.grid(axis = "y", alpha = 0.3)

    fig.suptitle("SOFR Futures: Forecast Errors by FOMC Horizon", fontsize = 14, fontweight = "semibold")
    fig.tight_layout()

    return fig
