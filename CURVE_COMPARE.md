# Full Model vs. Simplified SOFR Curve (Issue #6)

The `curve_compare` package asks: does explicitly modeling FOMC meeting timing and
SR1 settlement conventions give a more accurate market-implied Fed rate path than a
generic smooth curve that ignores FOMC timing?

**Status:** the default run is still **synthetic prices** on a seeded policy path, so
the tests need no data files and no network. Three inputs now come from the rest of
the project:

- Meeting dates come from `fomc_data`'s FOMC calendar.
- Next-meeting errors are scored by `forecast_eval` (horizon 1 only).
- SR1 month averages use `sofr_pricing`. On a calendar-day series this matches a
  plain sum. On business-day SOFR (the NY Fed file has no weekend rows), Friday's
  fixing covers the weekend, which is `sofr_pricing`'s rule.

A separate script reads the team's processed SR1 settlements, daily SOFR, and
target-rate decisions when those files are already on disk. It does not fetch
them. See "Real data" below. That section's accuracy table is from a run of
`python -m scripts.run_curve_compare_real` on those files. SR3, horizons 2-6,
and replacing this bootstrap with `sofr_pricing.fit_meeting_moves` are still open.

## Which result this is

`final_visualizations/VISUALIZATIONS.md` (Issue #7) also compares a full model
with this simplified curve, and it answers a different question. That page fits
`sofr_pricing.fit_many` on the SR1 and SR3 strip once a month, scores cumulative
errors out to six meetings, and at the next meeting compares that path with the
simplified SR1 curve. This document compares a daily SR1 bootstrap with the
simplified curve at the next meeting only. Quote this document for the
bootstrap. Quote the Issue #7 page for the monthly full-strip path. The two
tables are not the same test.

## Scope

Issue #6 covers a large space (SR1 vs. SR3, several forecast horizons, real vs. synthetic
data). Following the professor's check-in feedback to focus on a single contract and a
single horizon, this comparison is scoped to:

- **SR1 only** (one-month SOFR futures), not SR3.
- **Next-meeting horizon only** (horizon 1 in `forecast_eval`), not horizons 2-6.
- **Synthetic prices by default** (seeded moves, SOFR, and SR1 prices). The meeting
  dates are the real calendar. The processed Databento / NY Fed / FRED files are
  an optional second entry point, not something the tests require.

SR3 and multi-horizon comparisons are natural follow-ups once this scope is validated; see
"Pending" below. They are not implemented here.

## The two methods

Both methods use one date's strip of SR1 settlement prices to estimate a daily
SOFR rate path. The full model also uses meeting dates, a recent SOFR anchor
based on published fixings after the latest meeting (or earlier fixings adjusted
by that meeting's known move), and published fixings carried over elapsed days
of the current contract month.

- **Full model** (`full_model.py`): a step path that can only change on a scheduled FOMC
  meeting date. The size of each step is recovered one contract month at a time (a
  bootstrap) from the day-weighted-average SR1 pricing equation in Section 3 of
  `docs/METHODOLOGY.md` (PR #11). This is a scoped-down version of the fit in that
  document's Section 5, restricted to SR1 and to meeting dates as the only step points.
- **Simplified curve** (`simple_curve.py`): a smooth curve that knows nothing about FOMC
  dates. Ported from `build_short_rate_curve` in
  [`src/finm37000/futures.py`](https://github.com/pattersonem/finm37000-autumn-2026/blob/main/src/finm37000/futures.py),
  the course package's STIR-futures curve-building method (the "simplified SOFR
  curve-building approach similar to the one described in the course materials"
  mentioned in the team README). It bootstraps a continuously-compounded zero-rate curve
  from the SR1 strip, linearly interpolated between contract maturities, and reports the
  implied daily rate as that curve's local forward rate. It is reimplemented locally
  rather than imported, since the course package depends on `databento` at import time
  and this comparison makes no network calls at runtime.

Both operate in SOFR-rate space, because an SR1 price is an average of SOFR.
`forecast_eval` wants a cumulative change in the policy rate, in basis points, so
each method's rate at the next meeting is converted before scoring:

```text
implied change (bp) = (model SOFR at the next meeting - basis - policy rate now) x 100
```

The basis is fixed first. It is not estimated jointly with the meeting moves
(those two shift almost every contract the same way). On the synthetic path the
basis is the known constant `spread_pct`. On real data it is
`sofr_pricing.estimate_basis`: the average, over recent fixings, of SOFR minus
the target-range midpoint in force that day. The policy rate "now" is the
target midpoint after any decision announced on the observation date, which is
the anchor `forecast_eval` uses, so that day's decision is not part of the
forecast. `build_forecast_errors` then subtracts the realized cumulative
change. A constant basis cancels. What remains is the error in the implied move.

## Definitions

The quantities match `forecast_eval` (#5) and `docs/METHODOLOGY.md` Section 9.
Bias, MAE, RMSE, and the weekly day buckets are computed by that package
(`build_forecast_errors`, `summarize_by_horizon`, `weekly_day_bins`,
`error_by_days_to_meeting`), at horizon 1 only. This package still chooses
which rows to show.

- **Next-meeting horizon**: for observation date `t`, the target is the first
  scheduled FOMC meeting strictly after `t`. A meeting's own decision day is never
  its own target. `forecast_eval` drops that row.
- **Error** = implied cumulative policy change through the next meeting, minus the
  realized target-midpoint change at that meeting, in bp. Positive means the method
  expected a higher rate than the Fed delivered. On the synthetic path this is the
  same number as "implied policy rate at the meeting, minus the true policy rate."
- **Bias / MAE / RMSE**: mean error / mean absolute error / root mean squared error
  across observation dates, per method.
- **Method difference**: simplified-curve error minus full-model error, in bp.
- **Days to meeting**: calendar days from the observation date to the next meeting,
  in weekly buckets from `forecast_eval`.
- **Change vs. hold**: whether that meeting's realized move was nonzero. This split
  is the headline check for Issue #6. It is not `forecast_eval`'s year-regime table,
  which answers a different question. The bias, MAE, and RMSE inside the split still
  come from `summarize_by_horizon`.
- **Worst periods**: the target meetings with the largest simplified-curve MAE.
  Many days share one outcome, so the meeting is the period, not the day.

## Synthetic data

`synthetic.py` generates, from one seed:

1. Meeting dates: the 16 real announcements from 2024-01-31 through 2025-12-10,
   read from `fomc_data.fomc_calendar.fetch_fomc_calendar`. The moves at those
   dates are still made up: five hikes (+175 bp), six holds, five cuts (-150 bp).
2. Daily SOFR = true policy rate + a small constant spread + seeded daily noise,
   one value per calendar day.
3. SR1 settlement prices: `100 - sofr_pricing.sr1_rate` for each calendar month,
   with optional seeded price noise. On this calendar-day series `sr1_rate` equals
   the plain average. The same helper, given only business days, carries Friday
   across the weekend. The bootstrap uses that second behavior when it has to
   (`observed_sofr_total`); the two agree on the synthetic series.

Because the whole path is known in advance, SR1 prices are built with perfect foresight
of each contract month (the standard way to validate a curve-fitting method: generate
prices from a known path, then check that the method recovers it — see Section 12 of
`docs/METHODOLOGY.md`). `tests/test_curve_compare.py` checks that the full model recovers
the exact true deltas when there is no noise.

## Seeded results (real calendar, synthetic prices)

`python -m scripts.run_curve_compare_demo` with seed 0, on 486 business days from
2024-01-02 through the day before 2025-12-10:

| method | n_obs | bias (bp) | MAE (bp) | RMSE (bp) |
| --- | --- | --- | --- | --- |
| full_model | 486 | -0.06 | 3.50 | 9.23 |
| simple_curve | 486 | -2.22 | 12.19 | 16.14 |

| regime | n_obs | full_model MAE (bp) | simple_curve MAE (bp) |
| --- | --- | --- | --- |
| change | 294 | 4.93 | 19.23 |
| hold | 192 | 1.31 | 1.43 |

Mean (simplified - full model) error: -2.16 bp. Mean absolute difference: 13.00 bp.

The simplified curve's MAE is about 13 times larger on meetings that move the
rate than on holds. The full model's gap is smaller (about 3.7 times) but no
longer tiny, because the real calendar puts some meetings on the last days of
the SR1 month. The five worst meetings for the simplified curve are all rate
changes (2024-05-01, 2024-01-31, 2025-09-17, 2024-06-12, 2024-07-31), with MAE
from 20 bp to 29 bp. On those same meetings the full model is under 1 bp except
where the meeting sits at month end.

## Error when the meeting is at month end

The full model's error is still concentrated on 2024-01-31. The 20 observation
dates before that meeting have MAE 14.25 bp and RMSE 16.79 bp. The other 466
dates have MAE 3.04 bp and RMSE 8.76 bp. Across all 486 dates the MAE is
3.50 bp and the RMSE is 9.23 bp. The table above includes every date.

2024-01-31 is the last day of the January contract, so the move is identified
off a single post-meeting day. The bootstrap divides the contract's rate gap by
that one day, and a 1 bp error in the month's average becomes about a 31 bp
error in the move. Later contracts do not revise it. 2024-07-31 is the same
shape (full-model MAE 19.02 bp on 33 dates). 2025-01-29 and 2025-07-30 are
only a little better: two or three post-meeting days, and on the January 2025
hold the full model (MAE 5.24 bp) is worse than the smooth curve (MAE 1.62 bp),
which never has to name a move. A real-data run should treat late-month
meetings as poorly identified, not as evidence that the smooth curve is right.

## Known limitation of the simplified curve

Plotting the simplified curve's implied path (`plot_sample_paths`) shows small jumps
at contract-month boundaries, not a perfectly smooth line. This is an inherent property of
bootstrapping a *linearly interpolated* zero-rate curve (the course method's own choice of
interpolation): the zero rate is continuous, but its slope changes at each node, so the
derived local forward rate can jump there.
It is not a bug in this port; the course package's own `build_short_rate_curve` has the
same property. A monotone-cubic interpolation would smooth it out but is not what the
course method does.

## Real data

`python -m scripts.run_curve_compare_real` scores the same two methods on the
files the team already writes. It does not call Databento, FRED, or the NY Fed,
and it does not read an API key. Build the files first, from the repository root:

```bash
python -m scripts.fetch_sofr_futures   # SR1 settlements; needs DATABENTO_API_KEY or ~/.databento_api_key
python -m scripts.fetch_rate_data      # NY Fed SOFR and the FRED target range
```

| Input | File | What it is used as |
| --- | --- | --- |
| SR1 strip | `data/processed/sofr_futures_settlements.parquet` via `sofr_data.load_settlements(roots=("SR1",))` | That session's settlement prices. The contract window is the panel's `reference_start` / `reference_end` (the SR1 calendar month). |
| Daily SOFR | `data/processed/sofr_daily.csv` | The anchor and the elapsed fixings inside the current contract month. Not the forecast target. |
| Realized policy | `data/processed/fomc_meetings.csv` | `change_bps` is the truth `forecast_eval` subtracts. The target-range midpoint is the policy path in the chart. |
| Meeting dates | `fomc_data.fomc_calendar.fetch_fomc_calendar` | The schedule. A decision file that disagrees with this calendar is rejected. |

For each settlement date, scoring and plotting use only SOFR fixings published
by that date. A fixing dated on the settlement day is published the next
business day, so that day's rate remains forecast inside the SR1 month.
On a meeting day and until a post-meeting fixing is published, the full
model's anchor uses pre-meeting fixings plus the announced policy change.
Once post-meeting fixings are published, they supply the anchor directly.
Trade dates whose in-progress contract month lacks a covering published
fixing are excluded.

If a file is missing, the script names the command that builds it and exits.
The synthetic demo keeps working. The processed files are not committed.
`python -m scripts.run_curve_compare_real` was run against them. It scored
1,166 settlement dates. The decision span covers 38 meetings. The scored rows
use 37 distinct next-meeting dates, which is the `n_meetings` count beside
the errors. Basis is `sofr_pricing.estimate_basis`, fixed before scoring.

| method | n_obs | n_meetings | bias (bp) | MAE (bp) | RMSE (bp) |
| --- | --- | --- | --- | --- | --- |
| full_model | 1166 | 37 | 0.13 | 11.34 | 20.77 |
| simple_curve | 1166 | 37 | -6.58 | 13.33 | 20.57 |

| regime | n_obs | full_model MAE (bp) | simple_curve MAE (bp) |
| --- | --- | --- | --- |
| change | 572 | 9.78 | 25.05 |
| hold | 594 | 12.83 | 2.05 |

Mean (simplified - full model) error: -6.71 bp. Mean absolute difference: 15.18 bp.

On meetings that change the target, the full model has the lower MAE. On holds,
the simplified curve has the lower MAE, and the full model's RMSE across all
1,166 dates (20.77 bp) is slightly larger than the simplified curve's (20.57 bp).
The five worst meetings for the simplified curve are 2022-07-27, 2022-09-21,
2022-06-15, 2022-11-02, and 2024-09-18, with simplified MAE from 53.71 bp down
to 34.11 bp. This table is the daily SR1 bootstrap. It is not the monthly
`fit_many` table in `final_visualizations/VISUALIZATIONS.md`.

The full model still steps on the announcement date. `sofr_pricing` prices a
move from the next business day (`effective_date`). Those two conventions
differ. Horizon 1 in `forecast_eval` is defined on the announcement date, and
the synthetic path steps on that same date, so the bootstrap follows the
announcement date. Switching it is listed under "Pending".

## Pending

- **Real script.** The accuracy table above is that run. The processed files
  stay out of git.
- **Horizons 2-6.** The implied table currently has only the next meeting.
  `build_forecast_errors` would score the later meetings if both methods wrote
  a cumulative change for each of them.
- **`fit_meeting_moves`.** This bootstrap is still a separate SR1 inversion.
  Issue #7 scores `sofr_pricing.fit_many` (SR1 and SR3, once a month) against
  the simplified curve. Scoring this package's daily SR1 bootstrap against
  `fit_meeting_moves` on the same dates is still open.
- **Effective date.** The step is the announcement date, not
  `sofr_pricing.effective_date`.
- **SR3** is out of scope.

## Usage

```python
from curve_compare import generate_synthetic_world, default_obs_dates, run_comparison, summarize_errors

world = generate_synthetic_world(seed=0)
results = run_comparison(world, default_obs_dates(world))
summarize_errors(results)   # bias / MAE / RMSE per method, at the next-meeting horizon
```

## How to run

From the repository root, with Python 3.12 and `pip install -r requirements.txt`:

```bash
python -m pytest tests/test_curve_compare.py -v        # unit tests, no network
python -m scripts.run_curve_compare_demo                # synthetic prices, real FOMC dates
python -m scripts.run_curve_compare_demo --plot sample_paths.png
python -m scripts.run_curve_compare_real                # only if the processed files exist
```

The tests and the synthetic demo need no network access and no data files.
The real script needs the three processed files and nothing else; it will not
try to download them.
