"""
Generate historical SOFR futures-implied FOMC forecasts for Issue #7.

Uses the full estimation methodology from Issue #4.
Selects the first available futures trading day of each month.

The basis is not left at ``fit_many``'s default of 0. Methodology Section 2
fixes it at a recent SOFR-minus-policy spread. For each observation date this
script computes that spread with ``estimate_basis`` from the daily SOFR file
it already loads, using only fixings published before that date, and passes
the result into ``fit_many``. ``fit_many`` takes one basis for the whole call,
so the script calls it once per date.

``sofr_pricing.fixing_calendar`` does not ship a holiday list. Callers pass
holiday dates themselves. This script passes none, so the fixing calendar is
weekdays only.
"""

import argparse
from pathlib import Path

import pandas as pd

from sofr_pricing.estimation import estimate_basis, fit_many


# Trailing window inside estimate_basis. Twenty fixings is that function's default.
BASIS_N_FIXINGS = 20


def trailing_basis(fixings, decisions, obs_date, n_fixings = BASIS_N_FIXINGS):
    """SOFR minus the policy midpoint over the last ``n_fixings`` published fixings.

    The pricing package treats a day's SOFR as published on the next business
    day (``last_known_fixing_date``). The window therefore ends strictly before
    ``obs_date``, so the observation date's own fixing is not used even when
    the file already contains it.
    """
    obs_date = pd.Timestamp(obs_date)
    known = fixings.loc[fixings.index < obs_date]
    return float(estimate_basis(known, decisions, obs_date, n_fixings = n_fixings))


def prepare_historical_forecasts(futures_path, sofr_path, decisions_path, output_dir,
                                 start_date = "2022-02-01", months_ahead = 12):
    """
    Estimate historical FOMC forecasts and export diagnostics.

    Returns the implied-path table, the diagnostics table, and one basis per
    observation date that had enough published SOFR to compute one.
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

    if "effective_date" in decisions.columns:
        decisions["effective_date"] = pd.to_datetime(decisions["effective_date"], errors = "coerce")

    #use the first available futures trading date in each calendar month.
    dates = (panel.loc[panel["trade_date"] >= pd.Timestamp(start_date), "trade_date"]
                  .drop_duplicates()
                  .sort_values())

    obs_dates = (dates.groupby(dates.dt.to_period("M")).first().tolist())

    #use the full scheduled FOMC announcement calendar.
    meeting_dates = (decisions["meeting_date"].dropna().drop_duplicates().sort_values().tolist())

    # No holiday calendar is provided by sofr_pricing. Weekdays only.
    holidays = ()

    implied_frames = []
    diagnostic_frames = []
    basis_rows = []

    for obs_date in obs_dates:
        try:
            basis = trailing_basis(fixings, decisions, obs_date)
        except ValueError as error:
            diagnostic_frames.append(pd.DataFrame([{
                "obs_date": pd.Timestamp(obs_date),
                "error": f"basis: {error}",
                "basis": pd.NA,
            }]))
            continue

        implied, diagnostics = fit_many(panel = panel,
                                        obs_dates = [obs_date],
                                        decisions = decisions,
                                        meeting_dates = meeting_dates,
                                        basis = basis,
                                        realized_fixings = fixings,
                                        months_ahead = months_ahead,
                                        holidays = holidays,
                                        skip_errors = True)
        diagnostics = diagnostics.copy()
        diagnostics["basis"] = basis
        diagnostic_frames.append(diagnostics)
        basis_rows.append({"obs_date": pd.Timestamp(obs_date),
                           "basis": basis,
                           "n_fixings": BASIS_N_FIXINGS})
        if not implied.empty:
            implied_frames.append(implied)

    implied_columns = ["obs_date", "meeting_date", "effective_date",
                       "implied_move_bps", "implied_cum_change_bps"]
    implied_out = (pd.concat(implied_frames, ignore_index = True)
                   if implied_frames else pd.DataFrame(columns = implied_columns))
    diagnostics_out = (pd.concat(diagnostic_frames, ignore_index = True)
                       if diagnostic_frames else pd.DataFrame())
    basis_out = pd.DataFrame(basis_rows)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents = True, exist_ok = True)

    implied_out.to_csv(output_dir / "implied_forecasts.csv", index = False)
    diagnostics_out.to_csv(output_dir / "estimation_diagnostics.csv", index = False)
    basis_out.to_csv(output_dir / "basis_by_date.csv", index = False)

    print(f"Attempted observation dates: {len(obs_dates)}")
    print(f"Dates with a basis: {len(basis_out)}")
    print(f"Implied forecast rows: {len(implied_out)}")
    print(f"Diagnostics rows: {len(diagnostics_out)}")
    if not basis_out.empty:
        print(f"Basis window: up to {BASIS_N_FIXINGS} SOFR fixings published before each observation date")
        print("Basis is SOFR minus the target-range midpoint, in percent.")
        print(f"Basis min {basis_out['basis'].min():.4f}, "
              f"median {basis_out['basis'].median():.4f}, "
              f"max {basis_out['basis'].max():.4f}")
    print(f"Saved outputs to: {output_dir.resolve()}")

    return implied_out, diagnostics_out, basis_out


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
