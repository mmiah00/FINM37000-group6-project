
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
    Summarize MAE, RMSE, and bias by forecast horizon.

    Args:
    - errors (pd.DataFrame): Output of Issue #5's build_forecast_errors().

    Returns (pd.DataFrame): One row per horizon with accuracy statistics.
    """
    rows = []

    for horizon, group in errors.groupby("horizon", sort = True):
        values = group["error_bps"].dropna()

        rows.append({"horizon": int(horizon),
                     "n_obs": len(values),
                     "mae_bps": values.abs().mean(),
                     "rmse_bps": np.sqrt((values**2).mean()),
                     "bias_bps": values.mean()})

    return pd.DataFrame(rows).set_index("horizon")


def format_summary_table(summary, index_name):
    """
    Format an accuracy summary for presentation.

    Keeps the numerical summary separate from the formatted output.
    """
    table = summary.copy().reset_index()

    table = table.rename(columns = {index_name: "Horizon" if index_name == "horizon" else "Method",
                                    "n_obs": "N",
                                    "mae_bps": "MAE (bp)",
                                    "rmse_bps": "RMSE (bp)",
                                    "bias_bps": "Bias (bp)"})

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
