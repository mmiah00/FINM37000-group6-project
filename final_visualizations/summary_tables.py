
"""
Publication-ready forecast accuracy tables for Issue #7.

Uses forecast-error outputs from Issue #5 and comparison outputs from Issue #6.
All forecast errors and accuracy statistics are in basis points.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from final_visualizations.model_comparison import summarize_model_comparison


def summarize_forecast_horizons(errors):
    """
    Summarize n_obs, n_meetings, bias, MAE, and RMSE by forecast horizon.

    ``n_meetings`` is the number of distinct meeting dates behind the rows
    that enter the three error statistics. Issue #5 reports the same count
    beside bias, MAE, and RMSE, because forecasts of one meeting share one
    realized outcome.

    Args:
    - errors (pd.DataFrame): Output of Issue #5's build_forecast_errors().
      Required columns: horizon, meeting_date, error_bps.

    Returns (pd.DataFrame): One row per horizon with accuracy statistics.
    """
    if "meeting_date" not in errors.columns:
        raise ValueError("forecast errors need meeting_date so the summary can report n_meetings")

    rows = []

    for horizon, group in errors.groupby("horizon", sort = True):
        scored = group.dropna(subset = ["error_bps"])

        rows.append({"horizon": int(horizon),
                     "n_obs": int(len(scored)),
                     "n_meetings": int(scored["meeting_date"].nunique()),
                     "bias_bps": scored["error_bps"].mean(),
                     "mae_bps": scored["error_bps"].abs().mean(),
                     "rmse_bps": np.sqrt((scored["error_bps"]**2).mean())})

    return pd.DataFrame(rows).set_index("horizon")


def format_summary_table(summary, index_name):
    """
    Format an accuracy summary for presentation.

    Keeps the numerical summary separate from the formatted output.
    Meetings sits beside N, bias, MAE, and RMSE when the summary has it.
    """
    table = summary.copy().reset_index()
    label = "Horizon" if index_name == "horizon" else "Method"

    table = table.rename(columns = {index_name: label,
                                    "n_obs": "N",
                                    "n_meetings": "Meetings",
                                    "mae_bps": "MAE (bp)",
                                    "rmse_bps": "RMSE (bp)",
                                    "bias_bps": "Bias (bp)"})

    preferred = [label, "N", "Meetings", "Bias (bp)", "MAE (bp)", "RMSE (bp)"]
    ordered = [column for column in preferred if column in table.columns]
    extras = [column for column in table.columns if column not in ordered]
    table = table[ordered + extras]

    for column in ["MAE (bp)", "RMSE (bp)", "Bias (bp)"]:
        table[column] = table[column].map(lambda value: f"{value:.2f}")

    return table


def export_summary_tables(errors, comparison_results, output_dir="figures"):
    """
    Generate and save final forecast accuracy tables.

    Saves both machine-readable CSVs and formatted CSVs.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    horizon_summary = summarize_forecast_horizons(errors)
    model_summary = summarize_model_comparison(comparison_results)

    #numerical versions for reproducibility.
    horizon_summary.to_csv(output_dir / "forecast_accuracy_by_horizon.csv")
    model_summary.to_csv(output_dir / "model_comparison_summary.csv")

    #presentation versions with rounded statistics.
    format_summary_table(horizon_summary, "horizon").to_csv(output_dir / "forecast_accuracy_by_horizon_formatted.csv", index = False)
    format_summary_table(model_summary, "method").to_csv(output_dir / "model_comparison_summary_formatted.csv",index = False)

    return horizon_summary, model_summary
