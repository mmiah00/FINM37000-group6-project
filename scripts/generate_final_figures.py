
"""
Generate Issue #7 figures and tables from prepared input datasets.

Usage:
    python -m scripts.generate_final_figures \
        --errors path/to/forecast_errors.csv \
        --decisions path/to/fomc_meetings.csv \
        --comparison path/to/model_comparison.csv \
        --obs-date 2025-02-03 \
        --output-dir figures

The script consumes outputs from Issues #2, #5, and #6.
It does not refit models or collect market data.
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from final_visualizations.fed_paths import plot_fed_paths
from final_visualizations.forecast_errors import (plot_forecast_errors_by_horizon)
from final_visualizations.model_comparison import plot_model_comparison
from final_visualizations.summary_tables import export_summary_tables
from final_visualizations.historical_examples import (identify_notable_meetings, plot_notable_meetings)
from final_visualizations.style import apply_style


def save_figure(fig, output_dir, name):
    """
    Save a figure as both PNG and PDF.
    """
    for extension in ("png", "pdf"):
        fig.savefig(output_dir / f"{name}.{extension}", dpi = 300, bbox_inches = "tight")
    plt.close(fig)


def generate_figures(errors, decisions, comparison, obs_date, output_dir):
    """
    Generate the available final figures and summary tables.
    """
    apply_style()
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents = True, exist_ok = True)

    #figure 1: Market-implied vs. realized policy paths.
    fig = plot_fed_paths(errors, decisions, obs_date)
    save_figure(fig, output_dir, "01_fed_paths")

    #figure 2: Forecast errors by horizon.
    fig = plot_forecast_errors_by_horizon(errors)
    save_figure(fig, output_dir, "02_forecast_errors_by_horizon")

    #figure 3: Full vs. simplified methodology.
    fig = plot_model_comparison(comparison)
    save_figure(fig, output_dir, "03_model_comparison")

    #figure 4: Notable historical forecasting episodes.
    notable = identify_notable_meetings(errors)
    fig = plot_notable_meetings(notable)
    save_figure(fig, output_dir, "04_notable_meetings")

    #summary tables.
    export_summary_tables(errors, comparison, output_dir)

    #preserve the selected episodes for interpretation.
    notable.to_csv(output_dir / "notable_meetings.csv")

    print(f"Generated figures and tables in: {output_dir.resolve()}")


def main():
    parser = argparse.ArgumentParser(description = "Generate final SOFR futures analysis figures.")
    parser.add_argument("--errors", required = True)
    parser.add_argument("--decisions", required = True)
    parser.add_argument("--comparison", required = True)
    parser.add_argument("--obs-date", required = True)
    parser.add_argument("--output-dir", default = "figures")

    args = parser.parse_args()

    errors = pd.read_csv(args.errors)
    decisions = pd.read_csv(args.decisions)
    comparison = pd.read_csv(args.comparison)

    generate_figures(errors, decisions, comparison, args.obs_date, args.output_dir,)


if __name__ == "__main__":
    main()
