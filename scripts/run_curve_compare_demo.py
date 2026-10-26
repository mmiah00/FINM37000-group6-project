"""Demo of the Issue #6 comparison on synthetic prices and the real FOMC calendar.

SR1 prices, daily SOFR, and the moves are seeded. Meeting dates come from
`fomc_data`. Scores come from `forecast_eval` at the next meeting. For the
team's processed Databento, NY Fed, and FRED files, use
`python -m scripts.run_curve_compare_real`.

Run from the repository root:
    python -m scripts.run_curve_compare_demo
    python -m scripts.run_curve_compare_demo --plot sample_paths.png

Builds one seeded synthetic world (a known hike-then-hold-then-cut policy
path, SR1 prices built from it), fits both the full FOMC-aware model and the
simplified course-style curve at every observation date, and prints the
next-meeting-horizon accuracy tables described in CURVE_COMPARE.md.
"""

import argparse

import pandas as pd

from curve_compare import (
    default_obs_dates,
    generate_synthetic_world,
    method_difference_bps,
    plot_error_by_days_to_meeting,
    plot_sample_paths,
    run_comparison,
    summarize_by_days_to_meeting,
    summarize_by_regime,
    summarize_errors,
    worst_periods,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plot", metavar="PATH", help="also save the sample-paths chart here")
    args = parser.parse_args()

    world = generate_synthetic_world(seed=0)
    obs_dates = default_obs_dates(world)
    results = run_comparison(world, obs_dates)

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.float_format", "{:.2f}".format)
    print("SYNTHETIC PRICES on the real FOMC calendar.")
    print("Meeting dates are fomc_data's. Moves, daily SOFR, and SR1 prices are seeded.")
    print("Scores go through forecast_eval at the next meeting (horizon 1).")
    print("For the processed Databento / NY Fed / FRED files, run:")
    print("    python -m scripts.run_curve_compare_real\n")
    print(f"Meeting dates: {[d.date().isoformat() for d in world.meeting_dates]}")
    print(f"Moves (bp): {world.moves_bps.tolist()}\n")

    print("Next-meeting-horizon accuracy, full model vs. simplified curve:")
    print(summarize_errors(results), "\n")

    print("Accuracy by whether the next meeting was a rate change or a hold:")
    print(summarize_by_regime(results), "\n")

    print("Accuracy by calendar days before the next meeting (weekly buckets):")
    print(summarize_by_days_to_meeting(results), "\n")

    diff = method_difference_bps(results)
    print(f"Mean (simplified - full model) error: {diff.mean():.2f} bp")
    print(f"Mean |simplified - full model| error: {diff.abs().mean():.2f} bp\n")

    print("Worst target meetings by simplified-curve MAE:")
    print(worst_periods(results))

    if args.plot:
        import matplotlib
        matplotlib.use("Agg")  # write to a file without opening a window

        sample_date = world.meeting_dates[2] + pd.Timedelta(days=3)
        plot_sample_paths(world, sample_date).savefig(args.plot, dpi=150)
        days_path = args.plot.rsplit(".", 1)[0] + "_by_days.png"
        plot_error_by_days_to_meeting(results).savefig(days_path, dpi=150)
        print(f"\nSaved charts to {args.plot} and {days_path}")


if __name__ == "__main__":
    main()
