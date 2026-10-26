
"""
Tests for final forecast-error visualizations (Issue #7).
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd

from final_visualizations.forecast_errors import (plot_forecast_errors_by_horizon,)


def test_plot_forecast_errors_by_horizon():
    """
    The chart should use the supplied forecast-error data.
    """
    errors = pd.DataFrame({"horizon": [1, 1, 2, 2, 3, 3],
                           "error_bps": [10, -10, 20, -20, 30, -30]})

    fig = plot_forecast_errors_by_horizon(errors)

    assert isinstance(fig, matplotlib.figure.Figure)
    assert len(fig.axes) == 2

    #the summary statistics should be correct.
    stats_ax = fig.axes[1]

    mae = list(stats_ax.lines[0].get_ydata())
    rmse = list(stats_ax.lines[1].get_ydata())
    bias = list(stats_ax.lines[2].get_ydata())

    assert mae == [10, 20, 30]
    assert rmse == [10, 20, 30]
    assert bias == [0, 0, 0]
