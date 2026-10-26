
"""
Tests for market-implied vs. realized Fed policy paths (Issue #7).
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from final_visualizations.fed_paths import plot_fed_paths


@pytest.fixture
def sample_decisions():
    """
    Synthetic FOMC decisions with a known policy-rate path.
    """
    return pd.DataFrame({"meeting_date": ["2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",],
                         "target_lower_after": [4.25, 4.00, 3.75, 3.75],
                         "target_upper_after": [4.50, 4.25, 4.00, 4.00]})


@pytest.fixture
def sample_errors():
    """
    Synthetic forecast results with known cumulative changes.
    """
    return pd.DataFrame({"obs_date": ["2025-02-03"] * 3,
                         "meeting_date": ["2025-03-19", "2025-05-07", "2025-06-18"],
                         "implied_cum_bps": [-25.0, -50.0, -50.0],
                         "realized_cum_bps": [-25.0, -50.0, -50.0]})


def test_plot_returns_figure(sample_errors, sample_decisions):
    """
    The function should return a Matplotlib figure.
    """
    fig = plot_fed_paths(sample_errors, sample_decisions, "2025-02-03")

    assert isinstance(fig, matplotlib.figure.Figure)


def test_plot_rate_levels(sample_errors, sample_decisions):
    """
    Cumulative bp changes should convert into policy-rate levels.
    """
    fig = plot_fed_paths(sample_errors, sample_decisions, "2025-02-03")

    ax = fig.axes[0]
    realized = ax.lines[0].get_ydata()
    implied = ax.lines[1].get_ydata()

    #starting midpoint: (4.25 + 4.50) / 2 = 4.375%.
    assert list(realized) == [4.375, 4.125, 3.875, 3.875]
    assert list(implied) == [4.375, 4.125, 3.875, 3.875]


def test_missing_observation_date(sample_errors, sample_decisions):
    """
    Missing forecasts should raise an informative error.
    """
    with pytest.raises(ValueError, match="No forecasts available"):
        plot_fed_paths(sample_errors, sample_decisions, "2025-02-04")


def test_missing_policy_anchor(sample_errors, sample_decisions):
    """
    An observation date before the first decision has no anchor.
    """
    earlier = sample_errors.copy()
    earlier["obs_date"] = "2025-01-01"

    with pytest.raises(ValueError, match="No realized policy rate"):
        plot_fed_paths(earlier, sample_decisions, "2025-01-01")


def test_mixed_hikes_cuts_and_unsorted_dates(sample_decisions):
    """
    Forecasts should be sorted and preserve positive/negative moves.
    """
    errors = pd.DataFrame({"obs_date": ["2025-02-03"] * 3,
                           "meeting_date": ["2025-06-18", "2025-03-19", "2025-05-07"],
                           "implied_cum_bps": [-25.0, 25.0, 0.0],
                           "realized_cum_bps": [-50.0, 25.0, -25.0]})

    fig = plot_fed_paths(errors, sample_decisions, "2025-02-03")

    ax = fig.axes[0]
    implied = list(ax.lines[1].get_ydata())
    realized = list(ax.lines[0].get_ydata())

    #starting midpoint = 4.375%.
    assert implied == [4.375, 4.625, 4.375, 4.125]
    assert realized == [4.375, 4.625, 4.125, 3.875]
