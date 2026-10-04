# SOFR futures data

Stage 1 of the roadmap: the SOFR futures settlement prices the pricing model is
fitted to. Source is Databento (`GLBX.MDP3`, CME Globex).

## Quick start

```bash
pip install -r requirements.txt

# One-time: save your Databento key where the course package expects it.
printf '%s' 'db-YOUR_KEY_HERE' > ~/.databento_api_key
chmod 600 ~/.databento_api_key

python scripts/fetch_sofr_futures.py --dry-run   # estimated cost, no charge
python scripts/fetch_sofr_futures.py             # the real pull
```

Then, from anywhere in the project:

```python
from sofr_data import load_settlements, settlement_curve

panel = load_settlements()                       # whole sample
curve = settlement_curve(panel, "2024-05-30")    # one day's chain, ready to fit
```

## What gets pulled, and why from `statistics`

| | |
| --- | --- |
| Dataset | `GLBX.MDP3` |
| Products | `SR1` (One-Month SOFR), `SR3` (Three-Month SOFR) |
| Schemas | `statistics` for settlements, `definition` for expirations |
| Symbology | `parent` (`SR1.FUT`, `SR3.FUT`), which returns the whole chain |
| Sample | 2022-01-01 to 2026-09-30 |

Settlement prices come from the `statistics` schema, **not** `ohlcv-1d`. The
daily OHLCV close is the last trade of the session, and back-month SOFR
contracts frequently do not trade at all — the close would be stale or absent
exactly where the curve needs a price. The exchange's official settlement is
published as a separate statistics record.

Only *final, actual* settlements are kept, identified by bits 0 and 1 of CME
MDP3 tag 715 (`SettlPriceType`). Preliminary and intraday settlements are
discarded. See `SETTLEMENT_FINAL_ACTUAL_MASK` in `sofr_data/clean.py`.

Requests are chunked by quarter and cached as parquet under `data/raw/`.
Databento bills per request, so re-running after a crash, or rebuilding the
processed files after a change to the cleaning code, costs nothing while the
cache is intact. `--offline` rebuilds from cache without contacting Databento
at all; `--refresh` forces a re-fetch.

## Output files

| File | Contents |
| --- | --- |
| `data/processed/sofr_futures_settlements.parquet` | The panel: one row per contract per trade date |
| `data/processed/sofr_futures_contracts.parquet` | One row per contract: identifiers, reference period, sample span |
| `reports/data_quality_sofr_futures.md` | The quality checks, in readable form |
| `reports/data_quality_sofr_futures.json` | The same summary numbers, for programmatic use |

CSV copies of both tables sit alongside the parquet files for eyeballing.

### Panel schema

| Column | Type | Meaning |
| --- | --- | --- |
| `trade_date` | datetime64 | Session the settlement refers to (from `ts_ref`) |
| `root` | str | `SR1` or `SR3` |
| `contract_id` | str | Standardized identifier, e.g. `SR3-2024-12` |
| `raw_symbol` | str | CME raw symbol, e.g. `SR3Z4` |
| `contract_month` | datetime64 | First day of the contract's named month |
| `reference_start` | datetime64 | First day of the SOFR window it settles against |
| `reference_end` | datetime64 | Last day of that window, inclusive |
| `expiration` | datetime64 | Exchange last trading day |
| `settlement_price` | float64 | Official final settlement |
| `implied_rate` | float64 | `100 - settlement_price`, in percent |
| `cleared_volume` | Int64 | Cleared volume for the session |
| `open_interest` | Int64 | Open interest for the session |

`reference_start` and `reference_end` are the point of this table. The two
products settle on different windows, and the whole project rests on respecting
that difference, so the window is attached to every row rather than being
re-derived downstream.

## Contract conventions

Implemented in `sofr_data/contracts.py`.

**SR1 — One-Month SOFR.** Settles on the *arithmetic average* of daily SOFR over
the contract month. The reference period is the whole calendar month, and
trading terminates on the last business day of it, so the expiration month
equals the contract month.

> `SR1M4` → `SR1-2024-06`, reference period 2024-06-01 to 2024-06-30,
> expiration 2024-06-28.

**SR3 — Three-Month SOFR.** Settles on *compounded* daily SOFR over a reference
quarter running from the third Wednesday of the contract month up to, but not
including, the third Wednesday three months later. Trading terminates at the
*end* of that quarter, so the expiration month is the contract month **plus
three**.

> `SR3Z4` → `SR3-2024-12`, reference period 2024-12-18 to 2025-03-18,
> expiration 2025-03-18.

That offset is the easy thing to get backwards, so nothing trusts it blindly.
The pipeline re-derives each expiration month from the parsed symbol and
compares it against the exchange's own `expiration` field;
`expiration_convention_mismatches` in the quality report counts the
disagreements. **If that number is not zero, read it before trusting the
reference periods** — a systematic SR3 mismatch means `EXPIRY_MONTH_OFFSET` in
`sofr_data/contracts.py` needs to change, not that the data is bad.

Raw CME symbols carry only a one-digit year, which is ambiguous over a sample
this long (`SR3Z1` is both Dec 2021 and Dec 2031, and both are listed within our
window). The year is resolved against each contract's own expiration date
rather than against the trade date.

## Quality checks

Run automatically; written to `reports/`. Thresholds are in `sofr_data/config.py`.

| Check | Flags |
| --- | --- |
| Coverage | Trade dates missing against a CME calendar (US federal holidays plus Good Friday) |
| Duplicates | Repeated `(trade_date, contract_id)` |
| Missing settlements | No final settlement on a day the contract had open interest |
| Price bounds | Settlements outside 80–102, i.e. implied rates outside −2% to 20% |
| Rate jumps | Day-over-day implied-rate moves above 50bp |
| Stale prices | Settlements unchanged for 10 or more consecutive trading days |
| Expiration convention | Parsed contract month disagreeing with the exchange expiration |
| Chain depth | Dates with fewer than half the usual number of priced legs |
| Intra-life gaps | Trading days with no settlement inside a contract's own observed life |

Stale runs and thin days are expected in the back months — SOFR futures five
years out barely trade, and the exchange carries settlements forward. These are
reported rather than removed, because whether to use an illiquid leg is a
modelling decision. The checks that indicate a genuine *data* problem are
`duplicate_rows`, `implausible_prices`, `live_rows_without_settlement` and
`expiration_convention_mismatches`.

## A note on committing data

`data/` is gitignored. Raw pulls are large, and Databento's licence restricts
redistribution of their data, so `data/processed/` is ignored too. If the group
decides the derived settlement series is fine to share, drop that line from
`.gitignore` and commit it — otherwise each of us spends credits re-pulling the
same thing.

## Tests

```bash
python -m pytest tests/ -q
```

The Databento request layer is not covered: the tests drive the cleaning and
quality code with synthetic records shaped like Databento's output, so they run
without an API key or any spend.
