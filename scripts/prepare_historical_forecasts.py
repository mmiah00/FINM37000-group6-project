"""
Generate historical SOFR futures-implied FOMC forecasts for Issue #7.

Uses the full estimation methodology from Issue #4.
Selects the first available futures trading day of each month.
"""

import argparse
from pathlib import Path

import pandas as pd

from sofr_pricing.estimation import fit_many


def prepare_historical_forecasts(futures_path, sofr_path, decisions_path, output_dir, 
                                 start_date = "2022-02-01", months_ahead = 12):
    """
    Estimate historical FOMC forecasts and export diagnostics.
    """
    #load historical inputs.
    panel = pd.read_parquet(futures_path)
    fixings = pd.read_csv(sofr_path)
    decisions = pd.read_csv(decisions_path)

    #convert historical SOFR fixings to a date-indexed Series.
    fixings["date"] = pd.to_datetime(fixings["date"])
    fixings = (fixings.set_index("date")["sofr"].astype(float).sort_index())

    panel["trade_date"] = pd.to_datetime(panel["trade_date"])
    decisions["meeting_date"] = pd.to_datetime(decisions["meeting_date"])

    if "effective_date" in decisions.columns:decisions["effective_date"] = pd.to_datetime(decisions["effective_date"], errors = "coerce")

    #use the first available futures trading date in each calendar month.
    dates = (panel.loc[panel["trade_date"] >= pd.Timestamp(start_date), "trade_date"]
                  .drop_duplicates()
                  .sort_values())

    obs_dates = (dates.groupby(dates.dt.to_period("M")).first().tolist())

    #use the full scheduled FOMC announcement calendar.
    meeting_dates = (decisions["meeting_date"].dropna().drop_duplicates().sort_values().tolist())

    #estimate market-implied FOMC paths.
    implied, diagnostics = fit_many(panel = panel, 
                                    obs_dates = obs_dates,
                                    decisions = decisions,
                                    meeting_dates = meeting_dates,
                                    realized_fixings = fixings,
                                    months_ahead = months_ahead,
                                    skip_errors = True)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents = True, exist_ok = True)

    implied.to_csv(output_dir / "implied_forecasts.csv", index = False)
    diagnostics.to_csv(output_dir / "estimation_diagnostics.csv", index = False)

    print(f"Attempted observation dates: {len(obs_dates)}")
    print(f"Implied forecast rows: {len(implied)}")
    print(f"Diagnostics rows: {len(diagnostics)}")
    print(f"Saved outputs to: {output_dir.resolve()}")

    return implied, diagnostics


def main():
    parser = argparse.ArgumentParser(description = "Prepare historical FOMC-implied forecasts.")

    parser.add_argument("--futures", default = "data/processed/sofr_futures_settlements.parquet")
    parser.add_argument("--sofr", default = "data/processed/sofr_daily.csv")
    parser.add_argument("--decisions", default = "data/processed/fomc_meetings.csv")
    parser.add_argument("--output-dir", default = "data/processed/visualizations")
    parser.add_argument("--start-date", default = "2022-02-01")
    parser.add_argument("--months-ahead", type = int, default = 12)

    args = parser.parse_args()

    prepare_historical_forecasts(futures_path = args.futures,
                                 sofr_path = args.sofr,
                                 decisions_path = args.decisions,
                                 output_dir = args.output_dir,
                                 start_date = args.start_date,
                                 months_ahead = args.months_ahead)


if __name__ == "__main__":
    main()