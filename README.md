# Pricing the Fed with SOFR Futures

## Project Members

- **Ivy Chan** – Communication Leader
- **Theo Li** – Design Leader
- **Maisha Miah** – Tech Leader
- **Sankalp Yadav** – Design Leader

## Project Overview

This project studies how accurately SOFR futures prices reflect the market's expectations for future Federal Reserve interest rate decisions.

Using historical one-month and three-month SOFR futures settlement prices, we will reconstruct the path of the federal funds rate that the futures market was pricing before each FOMC meeting. We will then compare these implied rate paths with the Federal Reserve's actual policy decisions.

The main goal is to answer:

> **How accurately do SOFR futures predict the path of Federal Reserve policy rates?**

### Project Scope

The core objective is to have a complete and reproducible analysis of SOFR-implied Federal Reserve expectations. The core analysis will be completed first, while the intraday FOMC announcement study will serve as an optional extension if time permits.

## Data

The analysis will use daily market data from approximately 2022 through September 2026.

The main data sources will include:

- One-month SOFR futures settlements
- Three-month SOFR futures settlements
- FOMC meeting dates
- Effective Federal Funds Rate (EFFR)
- Realized Federal Reserve rate decisions

The core data source is Databento's CME Globex dataset (`GLBX.MDP3`): daily settlement prices for One-Month (SR1) and Three-Month (SR3) SOFR futures, accessed with the course-provided Databento API key. Daily SOFR and EFFR from the New York Fed and the FOMC meeting calendar are free public supplements.

The SOFR futures data will be used to estimate the market-implied policy path, while the FOMC and realized rate data will provide the benchmark against which those expectations are evaluated.

## Methodology

A key challenge is that SOFR futures contracts do not directly report the expected federal funds rate at individual FOMC meetings.

The contracts have different settlement conventions:

- **One-month SOFR futures** settle based on the average SOFR rate during a calendar month.
- **Three-month SOFR futures** settle based on compounded SOFR over a three-month period.

We will build a curve-fitting procedure that converts these futures prices into an implied path for short-term interest rates. The model will estimate the sequence of Federal Reserve rate changes that best reproduces the observed futures prices while respecting the settlement conventions of each contract.

This allows us to recover the market-implied expected Fed policy path on each trading day in the sample.

## Evaluation

After estimating the implied Fed path, we will compare the market's predictions with what the Federal Reserve actually did.

Forecast accuracy will be evaluated across approximately **38 FOMC meetings**, with forecasts measured at horizons of **1 to 6 meetings ahead**.

For each horizon, we can calculate measures such as:

- Forecast error in basis points
- Mean absolute error (MAE)
- Bias in market expectations
- Changes in forecast accuracy as the FOMC meeting approaches

As an additional validation exercise, we can compare futures-implied rates with the final realized settlement values of expired contracts.

## Comparison with a Simplified Approach

We will also compare our methodology with a simplified SOFR curve-building approach similar to the one described in the course materials.

This comparison will help measure the importance of correctly accounting for the timing of FOMC meetings and the exact settlement conventions of SOFR futures.

In particular, we will examine whether a simplified smooth curve fails to capture the **step-like behavior of policy rates around FOMC meetings**.

## Potential Extension: FOMC Announcement Reactions

If time permits, we will extend the analysis using intraday SOFR futures data around FOMC announcements.

This extension would examine how the market-implied Fed path changes minute-by-minute immediately before and after an FOMC decision.

The analysis could measure:

- The size of the market reaction to an announcement
- Which future FOMC meetings experience the largest repricing
- How quickly SOFR futures incorporate new monetary policy information

This extension will be treated as optional so that the core historical analysis can be completed independently.

## Expected Output

The final project will produce:

1. A historical series of market-implied Fed rate paths.
2. Visualizations comparing implied and realized Fed policy rates.
3. Forecast-error statistics for different forecast horizons.
4. A comparison between the full methodology and a simplified SOFR curve approach.
5. If completed, an intraday analysis of market reactions to FOMC announcements.

## Project Roadmap

The project will be developed in the following stages, with detailed tasks and progress tracked through GitHub Issues:

1. Collect and clean SOFR futures data. ([#1](https://github.com/mmiah00/FINM37000-group6-project/issues/1))
2. Collect FOMC meeting and realized rate data. ([#2](https://github.com/mmiah00/FINM37000-group6-project/issues/2))
3. Build the SOFR futures pricing framework. ([#3](https://github.com/mmiah00/FINM37000-group6-project/issues/3))
4. Estimate market-implied Fed rate paths. ([#4](https://github.com/mmiah00/FINM37000-group6-project/issues/4))
5. Evaluate Fed-path forecast accuracy. ([#5](https://github.com/mmiah00/FINM37000-group6-project/issues/5))
6. Compare the full model with a simplified curve methodology. ([#6](https://github.com/mmiah00/FINM37000-group6-project/issues/6))
7. Create final visualizations and analysis. ([#7](https://github.com/mmiah00/FINM37000-group6-project/issues/7))
8. If time permits, analyze intraday FOMC announcement reactions. ([#8](https://github.com/mmiah00/FINM37000-group6-project/issues/8))

## Team and Issue Ownership

| Member | Role | Issues |
| --- | --- | --- |
| Maisha Miah | Tech Leader | [#1](https://github.com/mmiah00/FINM37000-group6-project/issues/1) (Databento data and repo setup) |
| Ivy Chan | Communication Leader | [#2](https://github.com/mmiah00/FINM37000-group6-project/issues/2), [#7](https://github.com/mmiah00/FINM37000-group6-project/issues/7) |
| Theo Li | Design Leader | [#3](https://github.com/mmiah00/FINM37000-group6-project/issues/3), [#4](https://github.com/mmiah00/FINM37000-group6-project/issues/4) |
| Sankalp Yadav | Design Leader | [#5](https://github.com/mmiah00/FINM37000-group6-project/issues/5), [#6](https://github.com/mmiah00/FINM37000-group6-project/issues/6) |

[#8](https://github.com/mmiah00/FINM37000-group6-project/issues/8) is optional and unassigned; whoever is ahead after October 20 can pick it up.

## How to Run

*Planned: no code exists yet. These steps describe how the project is intended to run once each stage is implemented.*

1. Use Python 3.12 or newer.
2. Install the project dependencies, including the course package [`finm37000`](https://github.com/pattersonem/finm37000-autumn-2026).
3. Save the course-provided Databento API key in `~/.databento_api_key`, the location the course package reads it from.
4. Run the stages in roadmap order: data collection, pricing, path estimation, evaluation, and figures.

Check the cost of any Databento request before downloading. Raw Databento data is not committed to the repository.
