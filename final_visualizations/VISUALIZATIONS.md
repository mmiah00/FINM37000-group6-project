# Final Visualizations and Analysis

## Overview

This module produces the figures and summary analyses for Issue #7 of the *Pricing the Fed with SOFR Futures* project. It compares market-implied Federal Reserve policy paths with realized FOMC decisions, evaluates forecast errors across meeting horizons, and compares the full SOFR futures methodology with a simplified curve approach.

The figures are intended for the final report and presentation. The visualization pipeline consumes outputs from the preceding data, estimation, and evaluation modules; it does not independently retrieve futures prices or estimate market-implied policy paths.

The pipeline supports both synthetic examples for testing and historical analysis using actual SOFR futures settlement data.

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

Of 56 attempted monthly observation dates, 45 produced successful estimations, generating 356 implied forecasts. Restricting the evaluation to the first six upcoming FOMC meetings produces 270 forecast-error observations across 36 distinct FOMC meetings.

All six forecast horizons are represented, with 45 observations per horizon.

The remaining 11 estimation dates were excluded because the available contract or FOMC-calendar coverage did not support estimation under the model's selection rules.

### Historical Full versus Simplified Comparison

The historical comparison evaluates the full FOMC-aware model against a simplified SR1 futures curve at the next-meeting horizon.

The simplified methodology bootstraps a zero-rate curve from observed SR1 settlements without explicitly modeling FOMC meeting dates. Its implied forward SOFR rates are converted into estimated policy-rate changes using a historical SOFR baseline.

The baseline follows the Issue #6 convention of averaging up to five recent available SOFR fixings following the previous FOMC meeting.

This historical adaptation assumes that the SOFR–policy spread remains approximately constant over the forecast horizon. When an FOMC meeting results in a hold and therefore has no new policy effective date, the simplified curve is evaluated on the next business day after the announcement.

Both methodologies are evaluated against the same 45 historical observation dates.

| Metric | Full Model | Simplified Curve |
|---|---:|---:|
| Bias (bps) | -7.33 | -7.34 |
| MAE (bps) | 10.31 | 13.92 |
| RMSE (bps) | 12.53 | 20.67 |

The full model exhibits lower MAE and RMSE over this sample, suggesting that explicitly incorporating FOMC meeting dates may improve forecast accuracy. However, the results are descriptive and do not establish a causal advantage from the modeling approach.

## Reproducing the Figures

All commands should be executed from the repository root.

### Automated Tests

Run the visualization unit tests:

```bash
python -m pytest tests/test_fed_paths.py tests/test_model_comparison.py tests/test_summary_tables.py tests/test_historical_examples.py -v
```

Run the synthetic figure-generation test:

```bash
python -m pytest tests/test_generate_final_figures.py -v -s
```

### Historical Data Preparation

The historical workflow requires processed SOFR futures settlements, daily SOFR fixings, realized FOMC decisions, and market-implied forecasts generated by the upstream pricing model.

The historical estimation results are saved to:

- `data/processed/visualizations/implied_forecasts.csv`
- `data/processed/visualizations/estimation_diagnostics.csv`

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

Historical validation completed to date includes:

- 45 successful monthly market-implied rate estimations.
- 270 evaluated forecasts across six meeting horizons.
- 45 matched full-versus-simplified model comparisons.
- No missing or non-finite errors in the historical model-comparison dataset.
- Successful execution of the historical figure-generation pipeline.

These checks establish that the integrated workflow produces historical outputs. They do not independently establish that the forecasting methodology is economically optimal or that the results are statistically significant.

Visual inspection of the generated historical figures remains pending.

## Integration with Forecast Evaluation

The final figures depend on the upstream SOFR futures estimation, forecast-evaluation, and model-comparison pipelines.

Forecast comparisons use information available before each relevant FOMC announcement to avoid look-ahead bias. The historical horizon analysis covers one through six upcoming FOMC meetings.

The full-versus-simplified comparison uses the same next-meeting forecast targets and observation dates for both methodologies.

The historical comparison extends Issue #6's simplified-curve approach to actual SR1 futures settlements while retaining its distinction between FOMC-aware and non-FOMC-aware rate paths.

## Limitations

- **Monthly sampling:** The historical analysis uses approximately monthly observation dates rather than every trading day. Results may differ under denser sampling.
- **Estimation coverage:** Eleven attempted dates did not produce successful estimations, including dates affected by the September 2026 sample boundary.
- **SOFR–policy spread:** The historical simplified-curve comparison assumes an approximately constant spread between SOFR and the federal funds policy rate.
- **Contract conventions:** The simplified bootstrap does not explicitly model FOMC meeting timing or fully adjust for the already-realized portion of active front-month futures contracts.
- **Effective dates:** For FOMC holds, the next business day after the announcement is used as the simplified-curve evaluation date.
- **Notable meetings:** Some historical meetings have only one available horizon-1 forecast, limiting the interpretation of meeting-level averages.
- **Statistical inference:** Differences in historical forecast accuracy are descriptive; formal significance testing has not been performed.
- **Figure review:** Generated historical figures should be visually inspected before inclusion in the final report or presentation.

Synthetic examples remain available for testing and demonstration and must be clearly distinguished from the historical results.