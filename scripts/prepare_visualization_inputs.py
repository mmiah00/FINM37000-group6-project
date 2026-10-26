
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


def main():
    parser = argparse.ArgumentParser(description = "Prepare historical forecast data for final visualizations.")
    parser.add_argument("--implied", required = True)
    parser.add_argument("--decisions", default = "data/processed/fomc_meetings.csv")
    parser.add_argument("--output-dir", default = "data/processed/visualizations")
    args = parser.parse_args()

    implied = pd.read_csv(args.implied, parse_dates = ["obs_date", "meeting_date"])
    decisions = pd.read_csv(args.decisions, parse_dates = ["meeting_date"])

    errors = build_forecast_errors(implied = implied, realized = decisions, max_horizon = 6)

    if errors.empty:
        raise ValueError("No forecast errors generated. Check that implied forecasts "
                         "overlap with realized FOMC meetings.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents = True, exist_ok = True)

    errors.to_csv(output_dir / "forecast_errors.csv", index = False)

    summarize_by_horizon(errors).to_csv(output_dir / "accuracy_by_horizon.csv")
    hit_rate_sensitivity(errors).to_csv(output_dir / "hit_rate_sensitivity.csv")
    summarize_by_regime(errors).to_csv(output_dir / "accuracy_by_regime.csv")

    print(f"Processed {len(errors)} forecast observations.")
    print(f"Saved results to {output_dir.resolve()}")


if __name__ == "__main__":
    main()
