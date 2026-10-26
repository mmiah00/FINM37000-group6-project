# Intraday study, in plain language

This is the optional piece: what happens to the market's picture of the Fed in the two hours around a statement, not where the path sat at the settlement.

SOFR futures are quoted as a price, and the price is 100 minus the rate the contract implies. The team already has a fitter that turns a strip of those prices into a move at each upcoming FOMC meeting. The intraday study runs that same fitter at every minute, and again at four snapshots: the last trades before 13:55 Eastern, then 14:15, 14:45, and 16:00. The difference from the 13:55 book is the repricing. Horizon 1 is today's meeting. Horizon 2 is the next one. A cumulative number adds those moves up, so it is the change in the expected policy rate from this morning through that meeting.

We do not type in the decision the Fed just announced. If we did, the "surprise" would be our input, not the market's. Both the before book and the after book are asked what move they imply for today. The gap between those two answers is the surprise, including whatever the statement did to meetings further out.

Two sets of charts are committed, and they answer different questions.

`reports/intraday/` is a drill. We built fake minute bars with a jump we chose, at 14:00, and checked that the fitter gives that jump back. It does, to about a hundred-thousandth of a basis point. The September panel ends at −50 bp on the front meeting because we typed −50. The titles say "Synthetic check".

`reports/intraday/real/` is the downloaded book. Databento `GLBX.MDP3` `ohlcv-1m` for the 33 announcements the estimator can cover, 13:00 to 16:00 Eastern. `metadata.get_cost` on that exact request quoted **$0.0000** before the download. The file has 40,355 bars. The figures there are market prices run through the team's fitter.

For the talk: one sentence of method, then `reports/intraday/real/repricing_paths.png`. The three lines are the fully identified afternoons with the largest horizon-1 move from 13:55 to 16:00: 18 September 2024 (−11.12 bp), 29 October 2025 (+4.49 bp), and 15 June 2022 (+3.77 bp). Leave the synthetic September panel out of the talk.

## Questions a TA is likely to ask

### 1. The daily fit drops today's meeting. Why is it still in your unknown list?

Daily settlements print after the statement, so on a decision day the daily fitter treats today's move as already known and starts the forecast at the next meeting. These snapshots are at 13:55 and 14:15. At 13:55 the decision is not out. At 14:15 we still want the market's number for today, not the number from the Fed's sentence. The observation date passed into the fitter is midnight. Today's meeting is stamped 14:00, which is after midnight, so the fitter still treats it as a meeting to estimate. Meetings on earlier days stay in the past. The policy rate we anchor on is the target midpoint from this morning, before the decision. We never paste the announced move in as a known step.

### 2. Why 13:55, and why is the minute labeled 0 still the old book?

The statement is 14:00 Eastern and the press conference is 14:30. 13:55 is the last clean book before people start leaning on the release. 14:15 is fifteen minutes after the statement. 14:45 is fifteen minutes after the press conference. 16:00 is the end of the two-hour window.

The data are one-minute bars stamped at the start of the minute. The close is the last trade in that minute, so it is not known until the minute ends. "At or before 13:55" means bars that have finished by 13:55, which is the bar that started at 13:54. The same rule shifts the jumps by one minute on the chart. The point labeled 0 (exactly 14:00) still uses the 13:59 bar, which traded before the statement. The statement book shows up at minute 1. The press-conference book shows up at minute 31, not at minute 30. Summer and winter are not the same UTC hour: in June, 14:00 Eastern is 18:00 UTC, and in December it is 19:00 UTC. The code uses the New York timezone for that date rather than a fixed offset of 4 or 5.

### 3. How do you tell today's surprise from a markdown of later meetings? And why only 8 SR1 and 3 SR3?

Different contracts cover different days. An SR1 is a calendar-month average. An SR3 is the compounded rate from one IMM date to the next. A move at today's meeting lands in every contract that still has fixing days after today's effective date. A move at a meeting three months out lands only in the contracts that reach that far. That overlap is what the fitter untangles. The Jacobian has to be full rank for the split to be unique. We report the rank and the condition number on every snapshot.

The daily project fits 13 SR1 months and 6 SR3 quarters. On 18 September 2024 and 18 December 2024 that strip has 12 meetings and rank 11, and the condition number is on the order of 1e17. A planted path can still come back, because the unidentified direction happens not to be the one we planted, but the fit is not identified. Eight SR1 and three SR3 are the strip this study uses. The window is fixed at 60 minutes before the statement and 120 minutes after. There is no command-line switch for a longer strip or a different window.

On the real sample that strip is full rank at the 16:00 snapshot on 29 of 33 afternoons. Condition numbers there are usually about 9 to 20. A few identified days are larger and still full rank; the highest is about 1600, on 2025-03-19, which has 7 meetings and rank 7. Four afternoons have 7 meetings and rank 6, so the path is not unique: 2022-03-16, 2022-09-21, 2023-03-22, and 2023-09-20. Those four stay in the tables and on the horizon fan. The three-panel path chart keeps them off. It draws only afternoons that are fully identified at 16:00, and only the three with the largest absolute horizon-1 change. If a partial run has no fully identified afternoon, it skips the path chart and still writes the horizon chart and tables.

### 4. What if a deferred contract does not trade at 14:10?

We carry the last trade forward. A zero-volume bar is not a trade, so a quote-only print does not freeze a new price. The set of contracts is chosen at 13:55 and then held fixed. If a symbol trades for the first time at 14:10, it is left out of every fit that afternoon. Otherwise the strip would grow after the statement and the new meetings it can see would look like a repricing. Minutes early in the hour, before every 13:55 contract has printed at least once, are skipped rather than fit on a shorter strip. If even the 13:55 snapshot itself is missing a contract, that snapshot fails instead of quietly dropping the contract.

The honest limitation is that "carried forward" can mean "stale." A back-month price from 11:40 is not a 14:15 view. The diagnostics show how many contracts actually entered. On a real day the far SR3 is often carried, which is another reason the strip stops at three quarters. Two afternoons had only 10 of the 11 symbols traded by 13:55: 2022-01-26 and 2024-01-31. Both are still full rank on the meetings that strip can see.

### 5. Is this the market's expected path?

It is the path implied by SOFR futures, with two things held fixed that a TA should hear out loud.

Futures prices include risk premia, and SOFR is not the policy rate. We hold the SOFR-minus-policy basis fixed across the afternoon. On the real run the basis is `estimate_basis` through the last fixing already published that morning. A basis jump would be read as a policy move. We also price one expected path, so the small convexity term is ignored, same as the daily fit.

The drill in `reports/intraday/` passes no SOFR series, so its basis is zero and its jump is the one we planted. Recovering that jump shows the clock, the carry, and the fitter are wired together. The real run is a separate directory.

## What the real book did

Sample: the 33 covered announcements, 2022-01-26 through 2026-01-28. Five later 2026 dates are outside the estimator because the published calendar ends 2026-09-16. Every one of the 132 snapshots (33 days, four clocks) converged. Root mean squared pricing error at 16:00 is about 0.09 to 0.75 bp.

The table is horizon 1, in basis points. The 14:15, 14:45, and 16:00 columns are the change in the implied cumulative policy rate versus the 13:55 book (`delta_cum_bps`). "Level at 16:00" is the implied cumulative change itself, from this morning's target midpoint through today's meeting. "Identified" is full Jacobian rank at 16:00.

| date | 14:15 | 14:45 | 16:00 | level at 16:00 | identified |
| --- | ---: | ---: | ---: | ---: | --- |
| 2022-01-26 | -0.52 | -0.96 | -1.04 | +0.14 | yes |
| 2022-03-16 | -2.06 | -1.64 | -2.05 | +26.54 | no |
| 2022-05-04 | -1.88 | -1.97 | -1.94 | +50.62 | yes |
| 2022-06-15 | +3.49 | +3.61 | +3.77 | +74.14 | yes |
| 2022-07-27 | -1.50 | -1.95 | -2.00 | +75.64 | yes |
| 2022-09-21 | -3.49 | -3.35 | -3.52 | +75.44 | no |
| 2022-11-02 | -0.28 | -0.21 | -0.18 | +76.08 | yes |
| 2022-12-14 | -0.10 | -0.08 | -0.48 | +50.93 | yes |
| 2023-02-01 | -0.72 | -0.75 | -0.69 | +25.56 | yes |
| 2023-03-22 | +3.24 | +3.77 | +3.27 | +24.91 | no |
| 2023-05-03 | +1.11 | +1.35 | +1.03 | +24.21 | yes |
| 2023-06-14 | -2.25 | -2.06 | -2.38 | +0.85 | yes |
| 2023-07-26 | +0.16 | +0.09 | +0.21 | +24.99 | yes |
| 2023-09-20 | -0.12 | +0.34 | -0.07 | +0.22 | no |
| 2023-11-01 | -0.49 | -0.32 | -0.25 | +0.27 | yes |
| 2023-12-13 | -0.52 | -0.10 | -0.50 | +1.86 | yes |
| 2024-01-31 | +0.21 | +0.26 | +0.41 | -0.31 | yes |
| 2024-03-20 | -0.11 | -0.04 | +0.30 | +1.01 | yes |
| 2024-05-01 | +0.01 | -0.11 | -0.24 | -0.39 | yes |
| 2024-06-12 | +0.25 | +0.31 | +0.73 | +0.19 | yes |
| 2024-07-31 | +0.28 | +0.31 | +0.36 | +0.40 | yes |
| 2024-09-18 | -10.98 | -11.43 | -11.12 | -48.31 | yes |
| 2024-11-07 | +0.08 | -0.31 | +0.02 | -23.51 | yes |
| 2024-12-18 | -1.04 | -1.60 | -1.52 | -26.46 | yes |
| 2025-01-29 | +0.16 | +0.40 | +0.10 | -1.55 | yes |
| 2025-03-19 | +0.06 | +0.06 | +0.03 | -1.77 | yes |
| 2025-05-07 | +0.05 | -0.01 | -0.02 | -2.34 | yes |
| 2025-06-18 | +0.09 | -0.33 | +0.06 | +1.86 | yes |
| 2025-07-30 | +0.35 | +0.40 | +0.32 | +1.15 | yes |
| 2025-09-17 | +1.23 | +1.35 | +1.45 | -24.25 | yes |
| 2025-10-29 | +3.63 | +3.67 | +4.49 | -20.19 | yes |
| 2025-12-10 | -1.40 | -2.09 | -2.33 | -24.46 | yes |
| 2026-01-28 | +0.12 | +0.04 | +0.05 | -0.75 | yes |

Twenty-five of the 33 days move less than 2 bp at horizon 1 between 13:55 and 16:00. The statement usually confirmed a path the book already held. The three afternoons on the path chart are the exceptions worth talking through. Numbers below are the minute path, horizon by horizon. Minute 0 is still the pre-statement book. Minute 1 is the statement. Minute 31 is the press conference.

**18 September 2024.** Horizon 1 was already −37.19 bp at 13:55 and −36.00 bp at minute 0. The statement minute prints −47.97 bp. By 14:15 the change versus 13:55 is −10.98 bp, and by 16:00 it is −11.12 bp, with the level at −48.31 bp. The press conference does not take horizon 1 any further (minute 31 is −48.65, minute 120 is −48.31). Horizons 2 and 3 jump in that same first minute and then give a little back: by 16:00 they are −8.48 and −7.11 bp versus 13:55. Read it as a cut the market had mostly priced, with the statement supplying about 11 bp more on the front meeting inside the first minute. Databento flags this day as degraded quality. The fit still has 11 contracts, rank 6, and RMSE 0.33 bp, and it is the largest identified horizon-1 move in the sample, so it stays on the chart with that caveat.

**29 October 2025.** Horizon 1 was −24.68 bp at 13:55 and −24.57 at minute 0. Minute 1 is −22.14, about +2.4 bp, and the book then drifts to −20.19 by 16:00 (+4.49 bp versus 13:55). That is not a one-minute jump. The larger revision is further out, and more of it arrives after the press conference. Horizon 2 goes from −47.10 at minute 31 to −42.75 at minute 45 and −39.55 at minute 120 (+9.77 bp versus 13:55). Horizon 3 ends +10.44 bp versus 13:55.

**15 June 2022.** Horizon 1 was already +70.37 bp at 13:55. The decision that afternoon was a 75 bp hike, and most of it was in the book before the statement. Minute 1 is +73.46. By 16:00 the change versus 13:55 is +3.77 bp and the level is +74.14. Horizons 2 and 3 ease after the press conference: from minute 15 to minute 45, horizon 2 goes from +150.13 to +140.94 and horizon 3 from +215.34 to +200.92. By 16:00 those changes versus 13:55 are −4.06 and −9.26 bp.

The other identified days above about 2 bp at horizon 1 are 14 June 2023 (−2.38), 10 December 2025 (−2.33), and 27 July 2022 (−2.00). Three of the unidentified days are also large at horizon 1 (21 September 2022 −3.52, 22 March 2023 +3.27, 16 March 2022 −2.05). With rank 6 against 7 meetings those splits are one solution, so they stay in the table and on the fan, and off the path chart.

**One day without the SOFR splice.** Published daily SOFR in the team's file starts 2022-01-03. The January 2022 SR1 month starts 2022-01-01, so the pricer refuses to splice realized fixings through that front month. 2022-01-26 is fit with `realized_fixings` left empty. The basis is still the trailing estimate. The day uses 10 contracts, rank 5, and is identified, with RMSE 0.10 bp at 16:00. The other 32 days splice published SOFR. `sofr_pricing` is unchanged.

**Degraded prints.** Databento's dataset condition marks 2024-09-18 and 2025-09-17 as degraded. 17 September 2025 moves +1.45 bp at horizon 1 by 16:00. Both days are in the tables.

Files under `reports/intraday/real/`:

- `repricing_paths.png` — minute path for the three afternoons above, horizons 1–3, with lines at the statement and the press conference.
- `change_by_horizon.png` — 16:00 minus 13:55, by horizon, one line per announcement. More than eight lines, so the chart has no per-line legend. The note on the figure says the names are in the table.
- `snapshot_changes.csv` — every meeting at every snapshot, level and change from 13:55.
- `minute_paths.csv` — minute-by-minute implied rate for horizons 1–3, all 33 dates (16,800 rows). The path figure draws three of them.
- `change_by_horizon.csv` — the window-end change table behind the fan.
- `fit_diagnostics.csv` — rank, condition number, RMSE, convergence, and whether realized SOFR was spliced.

The minute bars themselves stay in gitignored `data/raw/intraday/` and `data/processed/sofr_intraday_ohlcv_1m.parquet`. The Databento key stays in `~/.databento_api_key`. Neither is committed.

## Synthetic check

`reports/intraday/` holds the three demo scenarios. Every figure title starts with "Synthetic check". The moves below were put in by the scenario.

The anchors are the target-range midpoint that morning (5.375 on 2024-09-18, 4.625 on 2024-12-18, 5.125 on 2023-06-14). Using those levels does not make the path a reconstruction of that day. The real 18 September 2024 panel, above, is a different number from this planted −50.

| scenario | what was planted | change, 16:00 minus 13:55, horizons 1–3 (bp) |
| --- | --- | --- |
| 2024-09-18, two-step cut (EDT) | pre −25 / −25 / −10; statement −40 / −25 / −15; press −50 / −30 / −20 | −25 / −30 / −40, then flat. Front meeting ends at −50. |
| 2024-12-18, path markdown (EST) | pre −25 / −10 / −10; statement and press −25 / −25 / −20 | 0 / −15 / −25, then flat. Horizon 1 does not reprice. |
| 2023-06-14, hike priced out (EDT) | pre +25 / +25 / +25; statement and press all 0 | −25 / −50 / −75, then flat through horizon 5. Rate stays near 5.12. |

All twelve snapshot fits (three afternoons, four snapshots) are full rank and converged, with 11 contracts. Root mean squared pricing error is 0.00 bp at display precision. The largest gap between a recovered move and the move that built the bars prints as 0.0000 bp.

## How to regenerate

Synthetic check, no key and no network. Writes under `reports/intraday/` and replaces that drill:

```bash
python scripts/run_intraday_demo.py --out reports/intraday
```

Real book. The daily SOFR, EFFR, and FOMC files come from `scripts/fetch_rate_data.py` (no Databento key). The minute bars come from `scripts/fetch_intraday_sofr.py`, which quotes `metadata.get_cost` and stops if the quote is above 5 dollars. `--real` only reads the caches. Point it at `reports/intraday/real` so the drill stays put:

```bash
python scripts/fetch_rate_data.py
python scripts/fetch_intraday_sofr.py --dry-run
python scripts/fetch_intraday_sofr.py
python scripts/run_intraday_demo.py --real --out reports/intraday/real
```

`fetch_rate_data.py` needs `PYTHONPATH` set to the repo root; the other two scripts insert it themselves. Tests monkeypatch the socket:

```bash
python -m pytest tests/test_intraday.py -q
```

## Limitations

- **Two figure directories.** `reports/intraday/` is the planted jump. `reports/intraday/real/` is the market. The September drill landing on −50 bp is the scenario. The real 18 September 2024 front meeting ends at −48.31 bp, of which −11.12 bp arrived after 13:55.
- **Thin trading.** Deferred SR1 and SR3 often do not trade every minute. Carry-forward keeps the last trade, which can be a stale price. The 13:55 universe rule makes that explicit: a contract that has not traded before the statement never enters the fit.
- **Risk premia and the basis.** Futures-implied moves are not pure expectations. The basis is held fixed across the afternoon. A jump in the basis would be read as a policy move.
- **One expected path.** Pricing uses the team's single-path pricer, so the small convexity adjustment is ignored, as in the daily fit.
- **The statement clock is exact.** A statement that hits the wire a minute late shows up one minute later on this path. Not every meeting's press conference moves the book; the 14:45 snapshot is there either way.
- **Identification.** Four afternoons are one rank short (7 meetings, rank 6). Their horizon-1 numbers are in the table. The path chart omits them.
- **January 2022 fixings.** The splice is off for 2022-01-26 only, because published SOFR starts after the front-month window opens. See the note above.
- **Degraded days.** Databento marks 2024-09-18 and 2025-09-17 as reduced quality. Both are still in the study.
- **Calendar tail.** Five 2026 announcements are outside the estimator until the published schedule is extended.
- **Bar schema.** The pull is `ohlcv-1m` closes, not the trades schema. A one-lot print and a deep print look the same once they are the minute's close.
