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

An earlier run of this pipeline called `fit_many` with its default basis of 0. That run reported 56 attempted monthly dates and 45 successful estimations. The other 11 dates failed because the contract strip or the FOMC calendar did not cover the fit. Those two counts describe that run. They are not a property the code promises for every sample.

Horizon h is kept only when the implied path has the h-th meeting after the observation date and that meeting is still in `fomc_meetings.csv`. A date near the end of the calendar can contribute to horizon 1 and drop out before horizon 6. `python -m scripts.prepare_visualization_inputs` prints `n_obs` and `n_meetings` for each horizon that is actually present, and writes them to `accuracy_by_horizon.csv`. The figure step writes the same counts to `forecast_accuracy_by_horizon.csv`. This note does not claim that every horizon has the same number of observations. The earlier draft's "45 observations at each of six horizons" (270 errors) is not repeated. That equality is not something the scoring code guarantees, and those error rows were not rebuilt for this follow-up.

### Historical Full versus Simplified Comparison

The historical comparison evaluates the full FOMC-aware model against a simplified SR1 futures curve at the next-meeting horizon.

The simplified methodology bootstraps a zero-rate curve from observed SR1 settlements without explicitly modeling FOMC meeting dates. Its implied forward SOFR rates are converted into estimated policy-rate changes using a historical SOFR baseline.

The baseline follows the Issue #6 convention of averaging up to five published SOFR fixings after the previous FOMC meeting. If none are available yet, it averages up to five pre-meeting fixings and adds that meeting's realized policy change.

This historical adaptation assumes that the SOFR–policy spread remains approximately constant over the forecast horizon. The simplified forward is read on the meeting's effective date, not on the announcement date. When a hold has no effective date, that date is the next business day after the announcement.

Both methodologies are scored on the same horizon-1 rows. The earlier basis-0 run described those rows as 45 dates. Read `n_obs` and `n_meetings` from the summary table before quoting a count.

The bias, MAE, and RMSE below are from that basis-0 run. They were not regenerated after the basis change. See Limitations.

| Metric | Full Model | Simplified Curve |
|---|---:|---:|
| Bias (bps) | -7.33 | -7.34 |
| MAE (bps) | 10.31 | 13.92 |
| RMSE (bps) | 12.53 | 20.67 |

On that basis-0 run, the full model had lower MAE and RMSE than the simplified curve. The comparison is descriptive. It does not establish a causal advantage, and it is not the daily SR1 bootstrap in `CURVE_COMPARE.md`.

The saved summary places `n_meetings` (distinct meeting dates behind the row) beside bias, MAE, and RMSE. The table above is the earlier run's comparison and does not include that count.

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
  --obs-date 2022-02-01 \
  --output-dir figures/historical
```

The pipeline generates PNG and PDF versions of the four figures, together with supporting summary tables and selected notable-meeting data.

The figure-generation entry point is `scripts/generate_final_figures.py`. Plotting functions are implemented in `final_visualizations/`, with shared Matplotlib formatting defined in `final_visualizations/style.py`.

## Validation

The visualization functions have been exercised using synthetic forecast and comparison data. The automated tests cover figure creation, rate-level construction, model-comparison summaries, notable-meeting selection, and figure generation.

The historical pipeline has also been executed using actual SOFR futures settlements and realized FOMC decisions.

What the earlier basis-0 run reported, and what this follow-up checked:

- That run reported 45 successful monthly estimations out of 56 attempts. Per-horizon counts were not rebuilt here. Use the printed `n_obs` column.
- The comparison metrics in the table above come from that same run, at basis 0.
- Synthetic tests cover figure creation, the basis passed into `fit_many`, horizon counts that stop at the end of the meeting file, `n_meetings` beside bias, MAE, and RMSE, and the notable-meetings axis label.

These checks establish that the integrated workflow produces historical outputs. They do not independently establish that the forecasting methodology is economically optimal or that the results are statistically significant.

Visual inspection of the generated historical figures remains pending.

## Integration with Forecast Evaluation

The final figures depend on the upstream SOFR futures estimation, forecast-evaluation, and model-comparison pipelines.

Forecast comparisons use information available before each relevant FOMC announcement to avoid look-ahead bias. The historical horizon analysis asks for one through six upcoming FOMC meetings. A horizon is omitted when the meeting file does not contain it.

The full-versus-simplified comparison uses the same next-meeting forecast targets and observation dates for both methodologies.

The historical comparison extends Issue #6's simplified-curve approach to actual SR1 futures settlements while retaining its distinction between FOMC-aware and non-FOMC-aware rate paths.

## Limitations

- **Basis.** Methodology Section 2 fixes the SOFR-minus-policy basis at a recent realized spread before the meeting moves are fit. For each observation date, `estimate_basis` averages SOFR minus the target-range midpoint over up to the last 20 fixings published before that date. A fixing is treated as known on the next business day, so the observation date's own fixing is left out. The script passes that basis into `fit_many`. The call is once per date, because `fit_many` takes a single basis and a later date should not inherit an early-sample spread. `sofr_pricing` does not include a holiday list, so `holidays` is empty and the fixing calendar is weekdays only.

  The basis changes the scored cumulative changes. On a synthetic strip where SOFR sits 6 bp below the policy rate, and published SOFR is supplied to the fit, fitting at basis 0 instead of that spread moves the first meeting's cumulative change by about 6.8 bp (about -2 bp becomes about -8.8 bp). Section 9 says the basis cancels when the error is a policy change rather than a SOFR level. That is true once the meeting moves themselves are right. A wrong basis is absorbed into those moves, mostly the nearest meeting.

  The historical bias, MAE, and RMSE on this page were produced with basis 0, which is the default this script used before this change. They were not regenerated here. This checkout has no `data/processed/` futures panel, and no Databento key was available to build one with `scripts/fetch_sofr_futures.py`. Do not quote those figures as the result of the methodology's basis.

- **Horizon counts.** A horizon is missing when the meeting file runs out. Quote `n_obs` and `n_meetings` from the pipeline output. Do not quote 45 observations at each of six horizons unless that output says so.

- **Monthly sampling:** The historical analysis uses approximately monthly observation dates rather than every trading day. Results may differ under denser sampling.
- **Estimation coverage:** The basis-0 run reported eleven attempted dates that did not produce successful estimations, including dates affected by the September 2026 sample boundary. That split was not rebuilt here.
- **SOFR–policy spread:** The simplified-curve leg still converts a SOFR forward into a policy change with a short trailing SOFR anchor (up to five fixings). That window is separate from the full model's 20-fixing `estimate_basis` window.
- **Contract conventions:** The simplified bootstrap does not explicitly model FOMC meeting timing or fully adjust for the already-realized portion of active front-month futures contracts.
- **Effective dates:** The simplified forward is read on the meeting's effective date, not on the announcement date. For a hold with no effective date, that date is the next business day after the announcement.
- **Notable meetings:** Some historical meetings have only one available horizon-1 forecast, limiting the interpretation of meeting-level averages.
- **Statistical inference:** Differences in historical forecast accuracy are descriptive; formal significance testing has not been performed.
- **Figure review:** Generated historical figures should be visually inspected before inclusion in the final report or presentation.

Synthetic examples remain available for testing and demonstration and must be clearly distinguished from the historical results.