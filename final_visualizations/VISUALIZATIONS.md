# Final Visualizations and Analysis

## Overview

This module produces the figures and summary analyses for Issue #7 of the *Pricing the Fed with SOFR Futures* project. It compares market-implied Federal Reserve policy paths with realized FOMC decisions, evaluates forecast errors across meeting horizons, and compares the full SOFR futures methodology with a simplified curve approach.

The figures are intended for the final report and presentation. The visualization pipeline consumes outputs from the preceding data, estimation, and evaluation modules; it does not independently retrieve futures prices or estimate market-implied policy paths.

The pipeline supports both synthetic examples for testing and historical analysis using actual SOFR futures settlement data.

## Which comparison to quote

This page and `CURVE_COMPARE.md` both compare a full model with the simplified SR1 curve. They are not two runs of the same test.

- This page (Issue #7) fits `sofr_pricing.fit_many` on the SR1 and SR3 strip, once a month, and scores cumulative policy changes out to six meetings. The next-meeting chart also scores that path against the simplified SR1 curve.
- `CURVE_COMPARE.md` (Issue #6) bootstraps an SR1-only step path on every settlement day and scores it against the same simplified curve at the next meeting only.

Quote this page for the monthly full-strip path and the multi-horizon errors. Quote `CURVE_COMPARE.md` for the daily SR1 bootstrap.

## Data Inputs

| Dataset | Source | Description |
|---|---|---|
| Realized FOMC decisions | Issue #2 (`fomc_data`) | Meeting dates, policy effective dates, target-rate bounds, and realized policy changes |
| Market-implied policy paths | Issue #4 (`sofr_pricing`) | Forecast observation dates and implied meeting-level or cumulative policy changes |
| Forecast evaluation | Issue #5 (`forecast_eval`) | Realized changes, signed forecast errors, and forecast horizons |
| Full versus simplified comparison | Issue #6 (`curve_compare`) | Simplified-curve methodology and matched forecast errors from both approaches |
| Historical SOFR futures settlements | Issue #1 (`sofr_data`) | SR1 and SR3 contract settlements and reference periods |

Forecast observations are associated with an observation date (`obs_date`) and a forecasted FOMC meeting (`meeting_date`). Forecast horizons count the number of FOMC meetings ahead. Policy-rate levels are expressed in percent, while forecast errors and policy changes are expressed in basis points (bp).

## Figure Construction

The pipeline produces four principal visualizations:

1. **Market-implied versus realized policy paths:** A step chart compares the policy-rate path implied by futures on a selected observation date with subsequent realized target-rate midpoints. The shaded area illustrates the difference between the paths; it is not a confidence interval.
2. **Forecast errors by FOMC horizon:** Boxplots show the distribution of signed errors, while an adjacent panel reports mean absolute error (MAE), root mean squared error (RMSE), and bias across available forecast horizons.
3. **Full versus simplified methodology:** Grouped bars compare overall MAE and RMSE. A dumbbell plot compares the methods' MAE separately for FOMC rate changes and holds.
4. **Notable FOMC forecasting episodes:** Meetings are selected using the largest and smallest meeting-level MAE and the largest positive and negative mean bias, where those categories exist. An additional event-study plotting function can display how forecasts evolved ahead of a selected meeting when sufficient observation-level data are available.

The notable-meetings categories are not required to identify distinct meetings. For the historical monthly sample, the minimum number of horizon-1 forecasts per meeting is set to one. Consequently, selected episodes are illustrative, and some categories may refer to the same meeting.

## Forecast Accuracy Measures

For each forecast, the signed error is defined as the market-implied cumulative policy change minus the corresponding realized cumulative policy change, in basis points.

- **MAE:** The mean absolute forecast error. Lower values indicate smaller average errors.
- **RMSE:** The square root of the mean squared forecast error. This places greater weight on large misses.
- **Bias:** The mean signed forecast error. Positive values indicate that implied changes exceed realized changes on average; negative values indicate the reverse.

Statistics are calculated from the observations in each reported group. Comparisons between the full and simplified models use matched observation dates and forecast targets to ensure consistent sample composition.

## Historical Forecast Evaluation

Historical market-implied forecasts are generated using the full SOFR futures pricing model from Issue #4 and evaluated against realized FOMC policy decisions using the Issue #5 evaluation methodology.

The analysis samples the first available futures trading date in each month, beginning in February 2022.

Each date calls `fit_many` with `estimate_basis`: up to the last 20 SOFR fixings published before the observation date, SOFR minus the target-range midpoint. The basis on the 56 dates ran from -0.1385 to 0.1180 percent, with median -0.0595.

All 56 dates, February 2022 to September 2026, produce a fit, and all 56 are fully identified (largest condition number 705). Two things make that possible:

- **A SOFR lead-in.** Daily SOFR is fetched from three months before the sample (`SOFR_FETCH_START` in `fomc_data/config.py`). A contract already running on 2022-02-01 was priced off fixings from 2021-12-15, so a file that starts on 2022-01-03 cannot price February and March 2022.
- **A strip that never reaches past the schedule.** The estimator refuses a strip that ends more than 63 days after the last scheduled meeting. The schedule now includes the two announced meetings after September 2026 (2026-10-28 and 2026-12-09, in `fomc_data.fomc_calendar.UPCOMING_FOMC_DATES`; they are scheduled, not scored), and for the last dates the strip is shortened so it fits (`strip_months_for` in `scripts/prepare_historical_forecasts.py`). The 2026-09-01 date uses a five-month strip, against twelve for most dates, so it identifies three meetings ahead rather than six. The `months_ahead` column of `estimation_diagnostics.csv` records the strip used on each date.

Horizon h is kept only when the implied path has the h-th meeting after the observation date and that meeting is still in `fomc_meetings.csv`. A date near the end of the calendar contributes to the near horizons and drops out of the far ones, so the horizons do not all have the same count: 56 observations at horizon 1 and 48 at horizon 6. `python -m scripts.prepare_visualization_inputs` prints `n_obs` and `n_meetings` for each horizon and writes them to `accuracy_by_horizon.csv`. The figure step writes the same counts to `forecast_accuracy_by_horizon.csv`.

### Historical Full versus Simplified Comparison

The historical comparison evaluates the full FOMC-aware model against a simplified SR1 futures curve at the next-meeting horizon.

The simplified methodology bootstraps a zero-rate curve from observed SR1 settlements without explicitly modeling FOMC meeting dates. Its implied forward SOFR rates are converted into estimated policy-rate changes using a historical SOFR baseline.

The baseline follows the Issue #6 convention of averaging up to five published SOFR fixings after the previous FOMC meeting. If none are available yet, it averages up to five pre-meeting fixings and adds that meeting's realized policy change.

This historical adaptation assumes that the SOFR–policy spread remains approximately constant over the forecast horizon. The simplified forward is read on the meeting's effective date, not on the announcement date. When a hold has no effective date, that date is the next business day after the announcement.

Both methodologies are scored on the same horizon-1 rows from this rerun. The formatted summary rounds to two decimals.

| Metric | Full Model | Simplified Curve |
|---|---:|---:|
| N | 56 | 56 |
| Meetings | 37 | 37 |
| Bias (bps) | 0.00 | -6.66 |
| MAE (bps) | 5.63 | 12.72 |
| RMSE (bps) | 7.60 | 19.77 |

Bias, MAE, and RMSE of the full model grow with the horizon:

| Horizon | N | Meetings | Bias (bps) | MAE (bps) | RMSE (bps) |
|---|---:|---:|---:|---:|---:|
| 1 | 56 | 37 | 0.00 | 5.63 | 7.60 |
| 2 | 54 | 36 | -6.02 | 14.14 | 18.75 |
| 3 | 53 | 35 | -17.01 | 28.62 | 37.25 |
| 4 | 51 | 34 | -30.09 | 41.51 | 55.91 |
| 5 | 50 | 33 | -42.81 | 53.32 | 73.78 |
| 6 | 48 | 32 | -53.64 | 63.54 | 90.25 |

Most of the long-horizon error is the 2022 hiking cycle. Four meetings ahead, the mean absolute error is 89 bp for the 11 forecasts made in 2022 and 28 bp for the 40 made from 2023 to 2026. When the Fed went on to hike, the four-meeting bias was -59 bp. When it went on to cut, it was -1 bp.

**Where the gain over the simplified curve comes from.** Dates within one meeting are not independent, so the comparison is made on meeting-level means (37 meetings). The full model's lower error is 7.3 bp on average (95% interval 3.3 to 12.1; lower at 26 of 37 meetings). It is concentrated at the 18 meetings that changed rates (7.4 versus 22.9 bp; a 15.5 bp gap, interval 9.1 to 23.3). At the 19 holds the two are indistinguishable (4.3 versus 3.7 bp; gap -0.6, interval -2.2 to 1.0). The full model has the lower error in every year: 6.6 versus 30.3 bp in 2022, 5.7 versus 8.2 in 2023, 6.6 versus 10.3 in 2024, 4.9 versus 8.9 in 2025, and 4.2 versus 5.6 in 2026. The gain is not extra SR3 information: fitting the same estimator on SR1 alone gives a next-meeting MAE of 5.60 bp against 5.63 bp.

On this run the full model had lower MAE and RMSE than the simplified curve at the next meeting. The comparison is descriptive, and it is not the daily SR1 bootstrap in `CURVE_COMPARE.md`.

`n_meetings` is the number of distinct meeting dates behind the row. It sits beside bias, MAE, and RMSE in the saved summary.

## Reproducing the Figures

All commands should be executed from the repository root.

### Automated Tests

Run the visualization unit tests:

```bash
python -m pytest tests/test_fed_paths.py tests/test_model_comparison.py tests/test_summary_tables.py tests/test_historical_examples.py tests/test_prepare_historical_forecasts.py -v
```

Run the synthetic figure-generation test:

```bash
python -m pytest tests/test_generate_final_figures.py -v
```

The test writes into pytest's temporary directory. It does not create `figures/synthetic/` in the repository. `figures/` is gitignored.

### Historical Data Preparation

The historical workflow requires processed SOFR futures settlements, daily SOFR fixings, and realized FOMC decisions. Build `implied_forecasts.csv` before the step that reads it:

```bash
python -m scripts.prepare_historical_forecasts \
  --futures data/processed/sofr_futures_settlements.parquet \
  --sofr data/processed/sofr_daily.csv \
  --decisions data/processed/fomc_meetings.csv \
  --output-dir data/processed/visualizations
```

That command writes:

- `data/processed/visualizations/implied_forecasts.csv`
- `data/processed/visualizations/estimation_diagnostics.csv`
- `data/processed/visualizations/basis_by_date.csv`

The basis is the trailing SOFR-minus-policy spread described under Limitations. `sofr_pricing` does not ship a holiday calendar, so the fixing calendar is weekdays only. The command prints the basis across the dates it could estimate.

Prepare the forecast-evaluation datasets:

```bash
python -m scripts.prepare_visualization_inputs \
  --implied data/processed/visualizations/implied_forecasts.csv \
  --decisions data/processed/fomc_meetings.csv \
  --output-dir data/processed/visualizations
```

Prepare the historical full-versus-simplified comparison:

```bash
python -m scripts.prepare_historical_comparison
```

Generate the final historical figures and summary tables:

```bash
python -m scripts.generate_final_figures \
  --errors data/processed/visualizations/forecast_errors.csv \
  --decisions data/processed/fomc_meetings.csv \
  --comparison data/processed/visualizations/model_comparison.csv \
  --obs-date 2022-04-01 \
  --output-dir reports/results
```

The pipeline generates PNG and PDF versions of the four figures, together with supporting summary tables and selected notable-meeting data. The path chart uses 2022-04-01, three weeks after the first hike, where the gap between the implied and realized path is plain to see; pass `--obs-date` for any other fitted date. The figures are written to `reports/results/`, which is committed. `python scripts/reproduce.py` runs this whole pipeline in order.

The figure-generation entry point is `scripts/generate_final_figures.py`. Plotting functions are implemented in `final_visualizations/`, with shared Matplotlib formatting defined in `final_visualizations/style.py`.

## Validation

The visualization functions have been exercised using synthetic forecast and comparison data. The automated tests cover figure creation, rate-level construction, model-comparison summaries, notable-meeting selection, and figure generation.

The historical pipeline has been executed on the processed SOFR futures settlements, daily SOFR, and realized FOMC decisions, with `estimate_basis` passed into `fit_many`.

What the pipeline reported:

- 56 monthly dates were attempted and 56 fits succeeded, all fully identified. The horizon-1 sample is 56 observations and 37 distinct meetings, and the far horizons have fewer, as the table above shows.
- The comparison metrics in the tables above come from this run, not the earlier basis-0 figures.
- Synthetic tests cover figure creation, the basis passed into `fit_many`, horizon counts that stop at the end of the meeting file, `n_meetings` beside bias, MAE, and RMSE, the last step of the path chart, and the notable-meetings labels.

These checks establish that the integrated workflow produces historical outputs. They do not independently establish that the forecasting methodology is economically optimal or that the results are statistically significant.

The generated figures were inspected. Two layout problems were found and fixed: the last step of the path chart had no width, so the final level drew as a vertical line at the right edge under the legend, and on the notable-meetings chart a value label ran over the axis labels while one meeting appeared twice. A meeting with a single forecast has a mean absolute error equal to the size of its bias, so it is now drawn once under both names.

## Integration with Forecast Evaluation

The final figures depend on the upstream SOFR futures estimation, forecast-evaluation, and model-comparison pipelines.

Forecast comparisons use information available before each relevant FOMC announcement to avoid look-ahead bias. The historical horizon analysis asks for one through six upcoming FOMC meetings. A horizon is omitted when the meeting file does not contain it.

The full-versus-simplified comparison uses the same next-meeting forecast targets and observation dates for both methodologies.

The historical comparison extends Issue #6's simplified-curve approach to actual SR1 futures settlements while retaining its distinction between FOMC-aware and non-FOMC-aware rate paths.

## Limitations

- **Basis.** Methodology Section 2 fixes the SOFR-minus-policy basis at a recent realized spread before the meeting moves are fit. For each observation date, `estimate_basis` averages SOFR minus the target-range midpoint over up to the last 20 fixings published before that date. A fixing is treated as known on the next business day, so the observation date's own fixing is left out. The script passes that basis into `fit_many`. The call is once per date, because `fit_many` takes a single basis and a later date should not inherit an early-sample spread. `sofr_pricing` does not include a holiday list, so `holidays` is empty and the fixing calendar is weekdays only.

  The basis changes the scored cumulative changes. On a synthetic strip where SOFR sits 6 bp below the policy rate, and published SOFR is supplied to the fit, fitting at basis 0 instead of that spread moves the first meeting's cumulative change by about 6.8 bp (about -2 bp becomes about -8.8 bp). Section 9 says the basis cancels when the error is a policy change rather than a SOFR level. That is true once the meeting moves themselves are right. A wrong basis is absorbed into those moves, mostly the nearest meeting.

  The historical bias, MAE, and RMSE on this page are from the rerun that passes that basis into `fit_many`. They replace the earlier basis-0 table.

- **Horizon counts.** A horizon is missing when the meeting file runs out. Quote `n_obs` and `n_meetings` from the pipeline output. Do not quote 45 observations at each of six horizons unless that output says so.

- **Monthly sampling:** The historical analysis uses approximately monthly observation dates rather than every trading day. Results may differ under denser sampling.
- **Estimation coverage:** All 56 dates fit. The last seven (March to September 2026) use strips shortened to stay inside the meeting schedule, so they identify fewer meetings ahead than the earlier dates. Their far-horizon errors are absent, not zero.
- **SOFR–policy spread:** The simplified-curve leg still converts a SOFR forward into a policy change with a short trailing SOFR anchor (up to five fixings). That window is separate from the full model's 20-fixing `estimate_basis` window.
- **Contract conventions:** The simplified bootstrap does not explicitly model FOMC meeting timing or fully adjust for the already-realized portion of active front-month futures contracts.
- **Effective dates:** The simplified forward is read on the meeting's effective date, not on the announcement date. For a hold with no effective date, that date is the next business day after the announcement.
- **Notable meetings:** Some historical meetings have only one available horizon-1 forecast, limiting the interpretation of meeting-level averages.
- **Statistical inference:** The comparison with the simplified curve is reported with meeting-level bootstrap intervals (above). The sample is 37 meetings, and the 2022 hiking cycle dominates the long-horizon errors, so the horizon table should not be read as a stable property of the market.

Synthetic examples remain available for testing and demonstration and must be clearly distinguished from the historical results.