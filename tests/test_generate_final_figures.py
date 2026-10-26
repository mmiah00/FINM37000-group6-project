
"""
Integration test for the Issue #7 figure-generation script.
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
from pathlib import Path

from scripts.generate_final_figures import generate_figures


def test_generate_all_figures(tmp_path, request):
    """
    Generate every figure and table using synthetic inputs.
    """

    decisions = pd.DataFrame({"meeting_date": ["2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30",],
                              "target_lower_after": [4.25, 4.00, 3.75, 3.75, 3.50],
                              "target_upper_after": [4.50, 4.25, 4.00, 4.00, 3.75]})

    meeting_dates = ["2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30",]

    rows = []
    for meeting in meeting_dates:
        for obs_date, error in [("2025-02-03", 5.0), ("2025-02-10", -5.0), ("2025-02-17", 10.0),]:
            rows.append({"obs_date": obs_date,
                         "meeting_date": meeting,
                         "horizon": 1,
                         "error_bps": error,
                         "implied_cum_bps": -25.0,
                         "realized_cum_bps": -30.0})

    errors = pd.DataFrame(rows)

    comparison = pd.DataFrame({"rate_change_at_meeting": [True, True, False, False],
                               "full_model_error_bps": [5.0, -5.0, 2.0, -2.0],
                               "simple_curve_error_bps": [20.0, -20.0, 4.0, -4.0]})

    #use a persistent folder when manually inspecting figures.
    #otherwise, use pytest's temporary directory.
    if request.config.getoption("-s", default = False):
        output_dir = Path("figures/synthetic")
    else:
        output_dir = tmp_path

    generate_figures(errors, decisions, comparison, "2025-02-03", output_dir)

    expected = ["01_fed_paths.png",
                "01_fed_paths.pdf",
                "02_forecast_errors_by_horizon.png",
                "02_forecast_errors_by_horizon.pdf",
                "03_model_comparison.png",
                "03_model_comparison.pdf",
                "04_notable_meetings.png",
                "04_notable_meetings.pdf",
                "forecast_accuracy_by_horizon.csv",
                "model_comparison_summary.csv",
                "notable_meetings.csv"]

    for filename in expected:
        assert (output_dir / filename).exists()
