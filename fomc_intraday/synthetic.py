"""Deterministic minute bars with a known policy surprise at 14:00 Eastern.

The prices are built with `sofr_pricing.synthetic.make_synthetic_market`,
which uses the same pricer as the fit. A noiseless fit should therefore
recover the moves that were put in. That checks the event-study wiring.
It does not check the model against the real market (the prices were
made by the model). No network and no Databento key.

Three regimes, all constant inside the regime so the clock of the jump
is the only thing that changes:

- bars that start before 14:00 use `pre_moves_bps` (the book before the statement)
- bars that start at or after 14:00 and before 14:30 use `statement_moves_bps`
- bars that start at or after 14:30 use `press_moves_bps` (the book after
  the press conference). If `press_moves_bps` is omitted, the statement
  book stays in place through the end of the window.

A bar is stamped at its start. The 13:59 bar is still the pre-statement
book, because those trades happened before 14:00. The first
post-statement bar starts at 14:00.
"""

import pandas as pd

from fomc_intraday.events import contracts_for
from fomc_intraday.windows import (
    PRESS_CONFERENCE_TIME,
    STATEMENT_TIME,
    announcement_window,
    eastern_on,
    minute_grid,
    to_utc,
)
from sofr_pricing.synthetic import make_synthetic_market


# Round numbers a person can check by eye. These are not historical
# market moves. Each dict is one synthetic announcement.
DEMO_SCENARIOS = [
    {
        "announcement_date": "2024-09-18",
        "label": "Synthetic two-step cut (summer, EDT)",
        "anchor": 5.375,
        # 15 bp of the front-meeting surprise at the statement, 10 bp more
        # at the press conference, and a further markdown of later meetings.
        "pre_moves_bps": {"2024-09-18": -25.0, "2024-11-07": -25.0, "2024-12-18": -10.0},
        "statement_moves_bps": {"2024-09-18": -40.0, "2024-11-07": -25.0, "2024-12-18": -15.0},
        "press_moves_bps": {"2024-09-18": -50.0, "2024-11-07": -30.0, "2024-12-18": -20.0},
    },
    {
        "announcement_date": "2024-12-18",
        "label": "Synthetic path markdown (winter, EST)",
        "anchor": 4.625,
        # Today's move is already priced. The statement marks down the
        # meetings after it. No second jump at 14:30.
        "pre_moves_bps": {"2024-12-18": -25.0, "2025-01-29": -10.0, "2025-03-19": -10.0},
        "statement_moves_bps": {"2024-12-18": -25.0, "2025-01-29": -25.0, "2025-03-19": -20.0},
        "press_moves_bps": None,
    },
    {
        "announcement_date": "2023-06-14",
        "label": "Synthetic hike priced out (summer, EDT)",
        "anchor": 5.125,
        # A full further hike was in the pre-statement book and is gone
        # as soon as the statement is out.
        "pre_moves_bps": {"2023-06-14": 25.0, "2023-07-26": 25.0, "2023-09-20": 25.0},
        "statement_moves_bps": {"2023-06-14": 0.0, "2023-07-26": 0.0, "2023-09-20": 0.0},
        "press_moves_bps": None,
    },
]


def _move_table(moves_bps):
    """Copy a {date: bp} map onto normalized timestamps. None stays None."""
    if moves_bps is None:
        return None
    return {pd.Timestamp(day).normalize(): float(bp) for day, bp in moves_bps.items()}


def _regime_prices(announcement_date, contracts, moves_bps, anchor, basis, holidays):
    """One settlement-style price per contract for a fixed move map."""
    priced = make_synthetic_market(
        pd.Timestamp(announcement_date).normalize(),
        contracts,
        {day.date().isoformat(): bp for day, bp in moves_bps.items()},
        anchor,
        basis,
        noise_bps=0.0,
        seed=0,
        holidays=holidays,
    )
    return priced.set_index("contract_id")["settlement_price"]


def make_synthetic_minutes(
    announcement_date,
    pre_moves_bps,
    statement_moves_bps,
    press_moves_bps=None,
    anchor=5.375,
    basis=0.0,
    holidays=(),
    label=None,
):
    """Minute bars and the moves that generated them.

    Returns `(bars, truth)`. `bars` has one row per contract per minute
    in the window, including the minute that ends at the window start so
    the first snapshot has a price. Every row has volume 1 (a trade).

    `truth` records the three move maps, the anchor, the basis and the
    label. Meetings that are not in a map were set to no change.
    """
    day = pd.Timestamp(announcement_date).normalize()
    pre_moves = _move_table(pre_moves_bps)
    statement_moves = _move_table(statement_moves_bps)
    press_moves = _move_table(press_moves_bps)
    if press_moves is None:
        press_moves = dict(statement_moves)

    contracts = contracts_for(day)
    pre_px = _regime_prices(day, contracts, pre_moves, anchor, basis, holidays)
    statement_px = _regime_prices(day, contracts, statement_moves, anchor, basis, holidays)
    press_px = _regime_prices(day, contracts, press_moves, anchor, basis, holidays)

    window = announcement_window(day)
    statement_utc = to_utc(eastern_on(day, STATEMENT_TIME))
    press_utc = to_utc(eastern_on(day, PRESS_CONFERENCE_TIME))

    # One minute before the window, so a snapshot exactly at the open
    # still has a last trade (the bar that ends at the open).
    bar_starts = [window["window_start"] - pd.Timedelta(minutes=1)]
    bar_starts.extend(minute_grid(window))
    # The grid includes the window end. A bar STARTING at the window end
    # is the minute after the study. Drop it. Keep the extra leading bar.
    bar_starts = [stamp for stamp in bar_starts if stamp < window["window_end"]]

    rows = []
    for bar_start in bar_starts:
        bar_utc = to_utc(bar_start)
        if bar_utc < statement_utc:
            prices = pre_px
        elif bar_utc < press_utc:
            prices = statement_px
        else:
            prices = press_px
        for contract in contracts.itertuples(index=False):
            rows.append({
                "announcement_date": day,
                "label": label,
                "contract_id": contract.contract_id,
                "root": contract.root,
                "raw_symbol": contract.raw_symbol,
                "reference_start": contract.reference_start,
                "reference_end": contract.reference_end,
                "ts_utc": bar_utc,
                "close": float(prices.loc[contract.contract_id]),
                "volume": 1,
            })

    bars = pd.DataFrame(rows)
    truth = {
        "announcement_date": day,
        "label": label,
        "anchor": float(anchor),
        "basis": float(basis),
        "pre_moves_bps": pre_moves,
        "statement_moves_bps": statement_moves,
        "press_moves_bps": press_moves,
    }
    return bars, truth


def make_demo_bars(holidays=()):
    """Stack the three demo scenarios into one bar table and a list of truths.

    Prices are fully determined by the scenario maps. The fit, which the
    demo runs separately, is what needs the FOMC calendar.
    """
    frames = []
    truths = []
    for scenario in DEMO_SCENARIOS:
        bars, truth = make_synthetic_minutes(
            scenario["announcement_date"],
            scenario["pre_moves_bps"],
            scenario["statement_moves_bps"],
            press_moves_bps=scenario["press_moves_bps"],
            anchor=scenario["anchor"],
            label=scenario["label"],
            holidays=holidays,
        )
        frames.append(bars)
        truths.append(truth)
    return pd.concat(frames, ignore_index=True), truths
