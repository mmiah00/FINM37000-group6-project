# Fed-Path Forecast Accuracy (Issue #5)

The `forecast_eval` package measures how well the SOFR-futures-implied Fed path predicted the
FOMC decisions that followed: forecast errors in basis points, bias, MAE, RMSE and direction hit
rate at horizons of 1 to 6 meetings ahead, how accuracy changes as a meeting approaches, and a
split by policy regime.

**Status:** the synthetic evaluation runs here. Historical real-data evaluation runs through
the Issue #7 workflow in [final_visualizations/VISUALIZATIONS.md](final_visualizations/VISUALIZATIONS.md).
That rerun passes `estimate_basis` into `fit_many`. At the next meeting it has 44 observations
and 30 meetings: full-model bias -0.09 bp, MAE 6.15 bp, RMSE 8.20 bp; simplified curve bias
-7.06 bp, MAE 14.34 bp, RMSE 21.76 bp. Horizons 1 through 6 each have those same two counts
on this sample. The daily SR1 bootstrap is a different test; its real-data table is in
[CURVE_COMPARE.md](CURVE_COMPARE.md).

## Definitions

These follow the evaluation section of `docs/METHODOLOGY.md` (Section 9, PR #11). Changes are
compared instead of levels, so a steady SOFR-policy-rate basis cancels out.

- **Horizon h**: for observation date *t*, the *h*-th scheduled FOMC meeting **strictly after** *t*.
  On a meeting's own decision day that meeting is not forecast: SOFR futures settle after the
  announcement, so that day's price is a nowcast. Horizon 1 is then the next meeting.
- **Forecast**: implied cumulative change in the policy rate from *t* through the *h*-th meeting
  (the methodology's Ĉ = sum of the implied moves Δr̂₁ … Δr̂ₕ).
- **Realized**: the sum of the realized target-midpoint changes at every scheduled meeting after
  *t* up to and including the *h*-th one. This equals the methodology's L(after mₕ) − L(t) when
  L(t) is the policy level in force after any meeting on or before *t*.
- **Error** = forecast − realized, in bp. Positive means the market expected a higher rate than
  the Fed delivered.
- **Bias** = mean error; **MAE** = mean absolute error; **RMSE** = root mean squared error.
- **Direction hit**: the *h*-th meeting's own implied move (implied cumulative through *h* minus
  through *h* − 1) and its realized move are each labelled hike (> +12.5 bp), cut (< −12.5 bp) or
  hold; a hit is when the labels agree. 12.5 bp is half a standard 25 bp move, the point where a
  move becomes more likely than no move. The threshold is a parameter.
  `hit_rate_sensitivity` reports the hit rate at 5, 12.5 and 20 bp as a check, since a risk premium
  in futures prices can push implied moves away from pure expectations.
- **Days to meeting**: calendar days from *t* to the meeting, bucketed (1-7, 8-14, 15-21, 22-28,
  29-42, 43+ by default) for horizon 1. The chart for #7 (`plot_error_by_days_to_meeting`) uses evenly spaced
  7-day buckets instead, which are easier to read on an axis.
- **Regimes** (parameters): 2022-23 hikes, 2024-25 cuts, 2026, assigned by the date of the meeting
  being forecast, not the observation date. At 6 meetings ahead the two can fall in different
  regimes (a late-2023 forecast of a 2024 cut counts as a cut-regime forecast).

Each table also reports `n_meetings`, the number of distinct target meetings. Forecasts made on
different days for the same meeting share one outcome, so their errors are strongly correlated and
the effective sample size is closer to `n_meetings` (about 38 in total) than to `n_obs`.

## Input contract

Rate changes are in basis points (25 = a 25 bp hike).

**Implied paths** (from #4): one row per (observation date, meeting).

| column | meaning |
| --- | --- |
| `obs_date` | trading day the futures were observed |
| `meeting_date` | FOMC announcement date of an upcoming meeting |
| `implied_cum_change_bps` | implied cumulative change from the policy rate on `obs_date` through this meeting |

Rows with `meeting_date` on or before `obs_date` are dropped (decision-day nowcasts), as are rows
for meetings outside the realized schedule's date range. A meeting date inside that range that is
not a scheduled meeting raises an error: it almost always means one table uses the effective date
(the day after the announcement) instead of the announcement date.

**Realized decisions** (from #2): one row per scheduled meeting.

| column | meaning |
| --- | --- |
| `meeting_date` | FOMC announcement date |
| `change_bps` | realized change in the target-range midpoint at that meeting |

These are the column names of #2's `data/processed/fomc_meetings.csv`
(`fomc_data.dataset.build_fomc_decisions`), so that table can be passed in unchanged; its other
columns are ignored. The table must include every scheduled meeting, holds included, since
horizons are counted on it.

## Usage

```python
from forecast_eval import (build_forecast_errors, summarize_by_horizon, error_by_days_to_meeting,
                           summarize_by_regime, hit_rate_sensitivity, plot_error_by_horizon,
                           plot_error_by_days_to_meeting)

errors = build_forecast_errors(implied, realized)   # one row per (obs_date, horizon)
summarize_by_horizon(errors)                        # n_obs, n_meetings, bias, MAE, RMSE, hit rate
error_by_days_to_meeting(errors, horizon=1)         # accuracy as the meeting approaches
summarize_by_regime(errors)                         # same statistics by (regime, horizon)
hit_rate_sensitivity(errors)                        # hit rate at 5, 12.5 and 20 bp
plot_error_by_horizon(errors).savefig("forecast_error_by_horizon.png")   # chart for #7
plot_error_by_days_to_meeting(errors).savefig("error_by_week.png")    # weekly bins, for #7
```

`make_synthetic_decisions` and `make_synthetic_implied_paths` (in `forecast_eval/synthetic.py`) are
**placeholders** for #2 and #4: the fake implied path is the realized path plus a chosen bias and
seeded noise, so the tests can check that the evaluation recovers exactly what was injected.

## How to run

From the repository root, with Python 3.12 and `pip install -r requirements.txt`:

```bash
python -m pytest tests/test_forecast_eval.py -v                 # unit tests
python -m scripts.run_forecast_eval_demo                        # tables on synthetic data
python -m scripts.run_forecast_eval_demo --plot error_by_horizon.png   # also save both charts
```

No network access or data files are needed.

## Pending

- **#4**: replace `make_synthetic_implied_paths` with #4's implied-path table (rename its columns
  onto the three above if needed). #4's anchor L(t) on a decision day should be the post-announcement
  level, so that its cumulative changes start after that day's decision.
- **#2**: replace `make_synthetic_decisions` with `fomc_meetings.csv` from PR #13 once merged.
  Unscheduled meetings are not in that calendar; a move at one would be counted at the next
  scheduled meeting.
- The per-meeting comparison suggested in the methodology (Δr̂ₕ against that meeting's realized
  change) is available as the `implied_move_bps` and `realized_move_bps` columns of
  `build_forecast_errors`, but is summarized only through the hit rate so far.
- Real-data tables and the final chart go to #7.
