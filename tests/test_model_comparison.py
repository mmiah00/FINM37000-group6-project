
"""
Tests for full-vs-simplified model comparison (Issue #7).
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from final_visualizations.model_comparison import (summarize_model_comparison, plot_model_comparison,)


@pytest.fixture
def sample_comparison():
    """
    Synthetic model-comparison results with known errors.
    """
    return pd.DataFrame({"obs_date": ["2025-01-10", "2025-01-17", "2025-02-07", "2025-02-14"],
                         "next_meeting": ["2025-01-29", "2025-01-29", "2025-03-19", "2025-03-19"],
                         "days_to_meeting": [19, 12, 40, 33],
                         "rate_change_at_meeting": [True, True, False, False],
                         "full_model_error_bps": [5.0, -5.0, 2.0, -2.0],
                         "simple_curve_error_bps": [20.0, -20.0, 4.0, -4.0]})


def test_model_comparison_summary(sample_comparison):
    """
    Verify MAE, bias, and observation counts.
    """
    summary = summarize_model_comparison(sample_comparison)

    assert summary.loc["Full model", "n_obs"] == 4
    assert summary.loc["Simplified curve", "n_obs"] == 4

    assert summary.loc["Full model", "bias_bps"] == 0
    assert summary.loc["Simplified curve", "bias_bps"] == 0

    assert summary.loc["Full model", "mae_bps"] == 3.5
    assert summary.loc["Simplified curve", "mae_bps"] == 12.0


def test_model_comparison_figure(sample_comparison):
    """
    Verify that the comparison chart is created.
    """
    fig = plot_model_comparison(sample_comparison)

    assert isinstance(fig, matplotlib.figure.Figure)
    assert len(fig.axes) == 2



def test_model_comparison_by_regime(sample_comparison):
    """
    Check the dumbbell plot's model-specific MAE values.
    """
    fig = plot_model_comparison(sample_comparison)

    ax = fig.axes[1]

    #each regime has one full-model and one simplified-model point.
    full_values = [ax.collections[i].get_offsets()[0, 0] for i in [0, 2]]

    simple_values = [ax.collections[i].get_offsets()[0, 0] for i in [1, 3]]

    assert full_values == [5.0, 2.0]
    assert simple_values == [20.0, 4.0]

