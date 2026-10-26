
"""
Tests for final forecast accuracy summary tables (Issue #7).
"""

import numpy as np
import pandas as pd

from final_visualizations.summary_tables import (summarize_forecast_horizons, format_summary_table, export_summary_tables)


def test_summarize_forecast_horizons():
    """
    Check MAE, RMSE, bias, and counts.
    """
    errors = pd.DataFrame({"horizon": [1, 1, 2, 2],
                           "error_bps": [10.0, -10.0, 20.0, -20.0]})

    summary = summarize_forecast_horizons(errors)

    assert summary.loc[1, "n_obs"] == 2
    assert summary.loc[1, "mae_bps"] == 10.0
    assert summary.loc[1, "rmse_bps"] == 10.0
    assert summary.loc[1, "bias_bps"] == 0.0

    assert summary.loc[2, "mae_bps"] == 20.0
    assert summary.loc[2, "bias_bps"] == 0.0


def test_format_summary_table():
    """
    Verify presentation formatting.
    """
    summary = pd.DataFrame({"n_obs": [10],
                            "mae_bps": [12.345],
                            "rmse_bps": [15.678],
                            "bias_bps": [-2.345]}, index = pd.Index([1], name = "horizon"))

    table = format_summary_table(summary, "horizon")

    assert table.loc[0, "Horizon"] == 1
    assert table.loc[0, "N"] == 10
    assert table.loc[0, "MAE (bp)"] == "12.35"
    assert table.loc[0, "RMSE (bp)"] == "15.68"
    assert table.loc[0, "Bias (bp)"] == "-2.35"


def test_export_summary_tables(tmp_path):
    """
    Verify all four CSV files are generated.
    """
    errors = pd.DataFrame({"horizon": [1, 1], "error_bps": [10.0, -10.0],})

    comparison = pd.DataFrame({"full_model_error_bps": [5.0, -5.0],
                               "simple_curve_error_bps": [15.0, -15.0]})

    export_summary_tables(errors, comparison, output_dir=tmp_path)

    expected = ["forecast_accuracy_by_horizon.csv",
                "model_comparison_summary.csv",
                "forecast_accuracy_by_horizon_formatted.csv",
                "model_comparison_summary_formatted.csv",]

    for filename in expected:
        assert (tmp_path / filename).exists()
