"""
Prepare historical full-versus-simplified SOFR model comparison for Issue #7.
"""

from pathlib import Path

import pandas as pd

from curve_compare.full_model import anchor_sofr_rate
from curve_compare.simple_curve import simple_curve_path


def main():
    data_dir = Path("data/processed")
    output_dir = data_dir / "visualizations"

    futures = pd.read_parquet(data_dir / "sofr_futures_settlements.parquet")
    decisions = pd.read_csv(data_dir / "fomc_meetings.csv", parse_dates = ["meeting_date", "effective_date"])
    sofr = pd.read_csv(data_dir / "sofr_daily.csv", parse_dates = ["date"])
    errors = pd.read_csv(output_dir / "forecast_errors.csv", parse_dates = ["obs_date", "meeting_date"])

    #compare both methodologies at the next-meeting horizon.
    errors = errors.loc[errors["horizon"] == 1].copy()

    futures["trade_date"] = pd.to_datetime(futures["trade_date"])

    daily_sofr = sofr.set_index("date")["sofr"].sort_index()
    meeting_dates = decisions["meeting_date"].tolist()

    rows = []

    for row in errors.itertuples(index = False):
        obs_date = row.obs_date
        meeting_date = row.meeting_date

        decision = decisions.loc[decisions["meeting_date"] == meeting_date].iloc[0]

        effective_date = decision["effective_date"]

        #holds have no new policy effective date. Evaluate the simplified curve on the next business day instead.
        if pd.isna(effective_date):
            effective_date = meeting_date + pd.offsets.BDay(1)

        #select the SR1 futures strip available on the observation date.
        sr1 = futures.loc[(futures["root"] == "SR1") & (futures["trade_date"] == obs_date)].copy()

        sr1 = sr1.rename(columns = {"reference_start": "month_start",
                                    "reference_end": "month_end",
                                    "settlement_price": "price"})

        sr1["month_start"] = pd.to_datetime(sr1["month_start"])
        sr1["month_end"] = pd.to_datetime(sr1["month_end"])

        #use only fixings known by the observation date.
        known_fixings = daily_sofr.loc[:obs_date]

        baseline = anchor_sofr_rate(known_fixings, obs_date, meeting_dates, window_days = 5)

        simple_rate = float(simple_curve_path(sr1, obs_date, [effective_date]).iloc[0])

        #both SOFR rates are in percentage points.
        simple_change_bps = (simple_rate - baseline) * 100.0

        #compare cumulative forecasts for the first upcoming meeting.
        realized_change_bps = row.realized_cum_bps

        rows.append({"obs_date": obs_date,
                     "meeting_date": meeting_date,
                     "effective_date": effective_date,
                     "full_model_error_bps": row.error_bps,
                     "simple_curve_error_bps": (simple_change_bps - realized_change_bps),
                     "rate_change_at_meeting": bool(decision["change_bps"] != 0),
                     "simple_implied_change_bps": simple_change_bps,
                     "realized_change_bps": realized_change_bps})

    comparison = pd.DataFrame(rows)

    output_path = output_dir / "model_comparison.csv"
    comparison.to_csv(output_path, index = False)

    print("Historical comparison observations:", len(comparison))
    print("Saved:", output_path)
    print(comparison[["obs_date", "meeting_date", "full_model_error_bps", "simple_curve_error_bps"]].head().to_string(index = False))


if __name__ == "__main__":
    main()