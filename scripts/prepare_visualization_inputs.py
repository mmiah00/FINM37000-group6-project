
"""
Prepare historical forecast evaluation inputs for Issue #7.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from forecast_eval.metrics import (build_forecast_errors, summarize_by_horizon, hit_rate_sensitivity, summarize_by_regime)


def build_visualization_inputs(implied, decisions):
    """
    Score implied paths and summarize each horizon the calendar can support.

    Horizon h is included only when the implied path has the h-th meeting
    after the observation date and that meeting is still in the realized
    schedule. ``n_obs`` in the returned table is that count. The table is
    not padded out to six horizons.
    """
    errors = build_forecast_errors(implied = implied, realized = decisions)

    if errors.empty:
        raise ValueError("No forecast errors generated. Check that implied forecasts "
                         "overlap with realized FOMC meetings.")

    by_horizon = summarize_by_horizon(errors)
    return errors, by_horizon


def main():
    parser = argparse.ArgumentParser(description = "Prepare historical forecast data for final visualizations.")
    parser.add_argument("--implied", required = True)
    parser.add_argument("--decisions", default = "data/processed/fomc_meetings.csv")
    parser.add_argument("--output-dir", default = "data/processed/visualizations")
    args = parser.parse_args()

    implied = pd.read_csv(args.implied, parse_dates = ["obs_date", "meeting_date"])
    decisions = pd.read_csv(args.decisions, parse_dates = ["meeting_date"])

    errors, by_horizon = build_visualization_inputs(implied, decisions)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents = True, exist_ok = True)

    errors.to_csv(output_dir / "forecast_errors.csv", index = False)

    by_horizon.to_csv(output_dir / "accuracy_by_horizon.csv")
    hit_rate_sensitivity(errors).to_csv(output_dir / "hit_rate_sensitivity.csv")
    summarize_by_regime(errors).to_csv(output_dir / "accuracy_by_regime.csv")

    print(f"Processed {len(errors)} forecast observations.")
    print("Observation count by horizon (n_obs) and distinct meetings (n_meetings):")
    print(by_horizon[["n_obs", "n_meetings"]].to_string())
    print(f"Saved results to {output_dir.resolve()}")


if __name__ == "__main__":
    main()
