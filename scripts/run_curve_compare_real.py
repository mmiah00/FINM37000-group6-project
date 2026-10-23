"""Run the Issue #6 comparison on the team's processed data.

The synthetic demo (`python -m scripts.run_curve_compare_demo`) stays the
default and does not need these files. This script only reads them:

    python -m scripts.fetch_sofr_futures    # SR1 settlements, needs a Databento key
    python -m scripts.fetch_rate_data       # NY Fed SOFR and FRED target range

Then, from the repository root:

    python -m scripts.run_curve_compare_real

No key is read here. If a processed file is missing, the script says which
command builds it and exits. Tests never call this script.
"""

import sys

import pandas as pd

from curve_compare import (
    method_difference_bps,
    run_comparison,
    summarize_by_days_to_meeting,
    summarize_by_regime,
    summarize_errors,
    worst_periods,
)
from curve_compare.real_data import load_real_world


def main():
    try:
        world = load_real_world()
    except FileNotFoundError as err:
        print(err)
        print(
            "\nThe real-data path is optional. Synthetic tests do not need these files,\n"
            "a Databento key, or a network connection.\n"
            "    python -m scripts.run_curve_compare_demo"
        )
        sys.exit(1)

    results = run_comparison(world)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.float_format", "{:.2f}".format)

    print("REAL DATA: next-meeting comparison (SR1 only)\n")
    print("SR1 strip: sofr_data.load_settlements, roots=('SR1',)")
    print("         data/processed/sofr_futures_settlements.parquet")
    print("         (Databento GLBX.MDP3 settlements from scripts/fetch_sofr_futures.py)")
    print("Daily SOFR: data/processed/sofr_daily.csv (NY Fed), used as the anchor")
    print("         and as the elapsed fixings inside the current SR1 month.")
    print("Truth:    data/processed/fomc_meetings.csv change_bps, the FRED")
    print("         target-range midpoint change at each announcement.")
    print("Calendar: fomc_data.fomc_calendar.fetch_fomc_calendar")
    print("Basis:    sofr_pricing.estimate_basis (fixed before scoring)")
    print("Scores:   forecast_eval.build_forecast_errors, horizon 1\n")
    print(f"Meetings scored: {len(world.meeting_dates)}")
    print(f"Observation dates: {len(results)}\n")

    print("Next-meeting-horizon accuracy, full model vs. simplified curve:")
    print(summarize_errors(results), "\n")

    print("Accuracy by whether the next meeting changed the target rate:")
    print(summarize_by_regime(results), "\n")

    print("Accuracy by calendar days before the next meeting (weekly buckets):")
    print(summarize_by_days_to_meeting(results), "\n")

    diff = method_difference_bps(results)
    print(f"Mean (simplified - full model) error: {diff.mean():.2f} bp")
    print(f"Mean |simplified - full model| error: {diff.abs().mean():.2f} bp\n")

    print("Worst target meetings by simplified-curve MAE:")
    print(worst_periods(results), "\n")


if __name__ == "__main__":
    main()
