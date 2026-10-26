# Intraday FOMC Announcement Reactions (Issue #8)

The `fomc_intraday` package measures how SOFR futures reprice in the minutes around an FOMC statement. It takes the outright contracts the team's estimator needs, fits the implied meeting path on the book just before 14:00 US Eastern, fits it again after the statement and after the press conference, and reports the change in the implied cumulative policy rate by meeting horizon.

The fit is `sofr_pricing.fit_meeting_moves`. Contract months come from `sofr_pricing.contract_strip`. The meeting list is `fomc_data`'s calendar. This package does not reimplement pricing, the estimator, contract metadata, or the calendar.

**Status:** the study runs on **synthetic minute bars**. Those bars are built by the same pricer the fit inverts, with a jump planted at 14:00, so a noiseless recovery is a check of the wiring (methodology section 12 calls this an inverse crime). It is not a historical market reaction. Real `ohlcv-1m` bars were not downloaded in this checkout: there is no Databento key here, and `data/processed/` is empty. The numbers in the committed figures are the planted jumps, recovered.

## Question

On an announcement afternoon, how fast and how far does the market's implied path for this meeting and the meetings after it move, between the last trades before the statement and the book after the statement and the press conference?

The object is the change in the implied cumulative policy rate, in basis points, from the 13:55 Eastern snapshot to each later snapshot. Horizon 1 is the meeting being announced. Horizon 2 is the next scheduled meeting, and so on.

## Data

**Clock.** The statement is treated as 14:00 US Eastern and the press conference as 14:30 US Eastern. `zoneinfo` (`America/New_York`) applies the daylight-saving offset for that calendar date. 14:00 on 2024-06-12 is 18:00 UTC (EDT, UTC−4). 14:00 on 2024-12-18 is 19:00 UTC (EST, UTC−5). The window is not a fixed UTC offset.

**Window.** The window is 60 minutes before the statement through 120 minutes after: 13:00 to 16:00 Eastern. The Databento request starts one minute earlier, because a bar is stamped at its start and the close is known at the end of the minute. The request end is exclusive and equals the window end, so the last included bar is the one that closes at 16:00.

**Snapshots.**

| label | clock (Eastern) | what it is |
| --- | --- | --- |
| `pre_1355` | 13:55 | last trade at or before 13:55, the pre-statement book |
| `post_1415` | 14:15 | fifteen minutes after the statement |
| `post_1445` | 14:45 | fifteen minutes after the 14:30 press conference |
| `post_1600` | 16:00 | end of the window |

Databento `ohlcv-1m` `ts_event` is the bar start, in UTC. The close is the last trade of that minute, so a snapshot "at or before 13:55" uses bars whose end is at or before 13:55 (the bar that started at 13:54). The bar that starts at 13:55 is not in yet. On the minute path, minute 0 (exactly 14:00) is still the pre-statement book. Minute 1 is the first close from the statement minute. Minute 30 (exactly 14:30) is still the statement book. Minute 31 is the first close from the press-conference minute.

A volume of zero is not a trade. A missing volume with a close is treated as a trade. A contract that did not trade in the latest minute keeps its last earlier trade (carry-forward). A contract with no trade yet is left out.

**Contract universe.** Every fit on that afternoon uses only the contracts that had already traded by 13:55. A contract that prints for the first time after the statement is left out of every fit, so a new symbol cannot look like a repricing. Minutes before that whole set has printed are skipped on the path. A required snapshot with an incomplete set raises, rather than fitting a shorter strip.

**Which contracts.** The strip is 8 SR1 months and 3 quarterly SR3 contracts (11 outrights). Raw CME symbols (`SR3U4`) come from `sofr_data.contracts.Contract`. The daily estimator uses 13 SR1 and 6 SR3. That longer strip reaches meetings a three-hour window barely trades, and on the dates checked here the Jacobian is one rank short (12 meetings, rank 11, condition number around 1e17 on 2024-09-18 and 2024-12-18). Eight and three stay full rank on those dates (condition numbers about 16, 15, and 9). Serial SR3 months are not used: `contract_strip` builds quarterly SR3 only.

**Which announcements.** Dates come from the team's FOMC calendar inside the futures sample (2022-01-01 through 2026-09-30). The estimator refuses a strip whose last reference day sits more than about nine weeks past the last scheduled meeting. The published calendar ends on 2026-09-16, so the latest dates drop out. With the fixed strip, 33 of 38 calendar dates are covered: 2022-01-26 through 2026-01-28. The five dropped dates are 2026-03-18, 2026-04-29, 2026-06-17, 2026-07-29, and 2026-09-16. The fetch script refuses those dates instead of paying for bars the fit cannot use.

**Anchor.** The policy rate is the target-range midpoint in force that morning, `policy_level_on(..., after_announcement=False)`, the same anchor `fit_many` uses. When `data/processed/sofr_daily.csv` is present, the SOFR-minus-policy basis is `estimate_basis` through `last_known_fixing_date`. SOFR for the announcement day is published the next morning, so it is not in the anchor or the basis. The synthetic check passes no SOFR series, so the basis is zero and the scenario supplies the anchor.

**Today's meeting stays unknown.** Daily settlements are end-of-day, so `fit_meeting_moves` treats a meeting on the observation date as already announced. An intraday snapshot is around 14:00, and the study wants today's expected move out of prices both before and after the statement. The observation date stays at midnight. Today's meeting is stamped 14:00, which is after midnight, so the estimator still treats it as unknown. The announced decision is not inserted as a known move. The pre-to-post change is the market's repricing.

## How to run

Synthetic check, no key and no network. Writes figures and tables under `reports/intraday/`:

```bash
python scripts/run_intraday_demo.py
python scripts/run_intraday_demo.py --out reports/intraday
```

Real minute bars, once a Databento key is in `~/.databento_api_key` or `DATABENTO_API_KEY` (the same place `sofr_data.config` reads it):

```bash
python scripts/fetch_rate_data.py
python scripts/fetch_intraday_sofr.py --dry-run
python scripts/fetch_intraday_sofr.py --dates 2024-09-18 2024-12-18
python scripts/run_intraday_demo.py --real --out reports/intraday
```

`fetch_rate_data.py` pulls the New York Fed and FRED series. It does not need a Databento key. `fetch_intraday_sofr.py` quotes `metadata.get_cost` for the exact `timeseries.get_range` arguments (dataset `GLBX.MDP3`, schema `ohlcv-1m`, `stype_in` `raw_symbol`) and does not download if the quote is above `--max-cost` (default 5 US dollars). Exit codes: 2 if the key is missing or a date is not on the covered calendar, 3 if the quote is over the cap. Nothing is downloaded on a dry run. Cached announcements are not quoted again. `--offline` rebuilds `data/processed/sofr_intraday_ohlcv_1m.parquet` from `data/raw/intraday/YYYY-MM-DD.parquet`. Both directories are gitignored. Do not commit the key or the bars.

`--real` only reads those caches. It does not download.

Tests (they monkeypatch the socket and do not open a connection):

```bash
python -m pytest tests/test_intraday.py -q
```

The tests cover synthetic recovery in summer (EDT) and winter (EST), snapshot selection and last-price carry, a contract that first trades after the statement staying out of every fit, the press-conference jump landing at 14:45 and on the minute path, the pre-announcement anchor, the cost cap refusing a download, and the calendar filter dropping the 2026 tail.

## Synthetic check

`reports/intraday/` holds the three demo scenarios. Every figure title starts with "Synthetic check". The moves below were put in by the scenario. They are not what the market did.

The anchors are the target-range midpoint that morning (5.375 on 2024-09-18, 4.625 on 2024-12-18, 5.125 on 2023-06-14). Using those levels does not make the path a reconstruction of that day.

| scenario | what was planted | change, 16:00 minus 13:55, horizons 1–3 (bp) |
| --- | --- | --- |
| 2024-09-18, two-step cut (EDT) | pre −25 / −25 / −10; statement −40 / −25 / −15; press −50 / −30 / −20 | −25 / −30 / −40, then flat. Front meeting ends at −50. |
| 2024-12-18, path markdown (EST) | pre −25 / −10 / −10; statement and press −25 / −25 / −20 | 0 / −15 / −25, then flat. Horizon 1 does not reprice. |
| 2023-06-14, hike priced out (EDT) | pre +25 / +25 / +25; statement and press all 0 | −25 / −50 / −75, then flat through horizon 5. Rate stays near 5.12. |

All twelve snapshot fits (three afternoons, four snapshots) are full rank and converged, with 11 contracts. Root mean squared pricing error is 0.00 bp at display precision. The largest gap between a recovered move and the move that built the bars prints as 0.0000 bp. The fit residual in `fit_diagnostics.csv` is on the order of 1e-5 bp.

Files:

- `reports/intraday/repricing_paths.png` — minute path for the three scenarios, horizons 1–3, with lines at the statement and the press conference.
- `reports/intraday/change_by_horizon.png` — 16:00 minus 13:55, by horizon, across the three scenarios.
- `reports/intraday/snapshot_changes.csv` — every meeting at every snapshot, level and change from 13:55.
- `reports/intraday/minute_paths.csv` — minute-by-minute implied rate for horizons 1–3.
- `reports/intraday/change_by_horizon.csv` — the window-end change table behind the second figure.
- `reports/intraday/fit_diagnostics.csv` — rank, condition number, RMSE, convergence.
- `reports/intraday/synthetic_truth.csv` — the moves that generated the bars.

## What was not regenerated here

Real minute bars, and therefore any real repricing (how many basis points the September 2024 book actually moved in the first fifteen minutes, and the same for the rest of the sample), were not produced. This machine has no `~/.databento_api_key` and no `DATABENTO_API_KEY`. The daily SOFR and FOMC files were also not fetched into `data/processed/` for this write-up; `--real` needs both. The commands above are what regenerates them.

## Limitations

- **These figures are a method check.** Do not present the September panel as the historical 50 bp cut. The −50 bp front-meeting level is a number the scenario planted.
- **Thin trading.** Deferred SR1 and SR3 often do not trade every minute. Carry-forward keeps the last trade, which can be a stale price. The 13:55 universe rule makes that explicit: a contract that has not traded before the statement never enters the fit.
- **Risk premia and the basis.** Futures-implied moves are not pure expectations. The basis is held fixed across the afternoon (zero in the synthetic check; a trailing SOFR-minus-policy average when daily SOFR is on disk). A jump in the basis would be read as a policy move.
- **One expected path.** Pricing uses the team's single-path pricer, so the small convexity adjustment is ignored, as in the daily fit.
- **The statement clock is exact.** A statement that hits the wire a minute late shows up one minute later on this path. Not every meeting's press conference moves the book; the 14:45 snapshot is there either way.
- **Identification.** The default strip stops at three SR3 quarters so the Jacobian stays full rank and the window only asks for contracts that can actually trade. The far end of the daily 13+6 strip is weakly identified even before liquidity. A rank-deficient fit can still print a path; `fully_identified` in the diagnostics is the flag.
- **Calendar tail.** Five 2026 announcements are outside the estimator until the published schedule is extended.
- **Bar schema.** The pull is `ohlcv-1m` closes, not the trades schema. A one-lot print and a deep print look the same once they are the minute's close.
