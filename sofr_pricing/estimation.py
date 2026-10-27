"""Estimate the market-implied FOMC path from SR1 and SR3 prices (Issue #4).

Issue #3 goes FORWARD: rate path -> theoretical futures prices.
This module goes BACKWARD: observed futures prices -> the rate moves at each
upcoming FOMC meeting that best explain them.

The fit, for one observation date t (docs/METHODOLOGY.md, Sections 2 and 5):

    choose moves m_1, ..., m_K (one per upcoming meeting, in percent) to minimize

        sum over contracts of (market_price - model_price(m))**2  +  ridge * sum(m**2)

where model_price(m) prices each contract with the #3 pricer on the path

    SOFR(day) = anchor + basis + known moves + sum of m_j from each effective date on

and, if published SOFR is supplied, the days already known come from it.

How the minimization works (regularized Gauss-Newton)
-----------------------------------------------------
1. Measure how each contract price reacts to a 1 bp move at each meeting.
   This table is the Jacobian J (contracts x meetings).
2. Treat the prices as linear in the moves and solve the small linear system
       (J'J + ridge * I) step = J' residual - ridge * m
3. Update the moves, re-price, and repeat until the moves stop changing.
SR1 prices are exactly linear in the moves and SR3 prices almost are, so this
converges in a few steps. The ridge term keeps the system solvable when two
meetings affect the contracts in nearly the same way.

Units: rates and moves are in percent inside this module. The output tables
also report basis points (bp), since #5 (PR #15) works in bp.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sofr_pricing.fixing_calendar import effective_date, fixing_dates, last_known_fixing_date
from sofr_pricing.paths import splice_realized, step_fixings
from sofr_pricing.pricing import price_contracts

# A small ridge penalty. Price residuals are in index points and moves in
# percent, so 1e-6 only matters for meetings that the contracts barely see.
DEFAULT_RIDGE = 1e-6

# Size of the test move used to measure sensitivities: 0.01 percent = 1 bp.
BUMP = 0.01

# FOMC meetings are at most about 8 weeks apart. If the schedule stops more
# than this many days before the last contract ends, meetings are missing.
MAX_SCHEDULE_GAP_DAYS = 63

CONTRACT_COLUMNS = ["root", "reference_start", "reference_end", "settlement_price"]
DECISION_COLUMNS = ["meeting_date", "target_lower_before", "target_upper_before",
                    "target_lower_after", "target_upper_after"]


# ---------------------------------------------------------------------------
# The policy-rate anchor and the SOFR basis
# ---------------------------------------------------------------------------


def _check_columns(table, required, name):
    missing = [column for column in required if column not in table.columns]
    if missing:
        raise ValueError(f"{name} is missing columns {missing}")


def policy_level_on(day, decisions, after_announcement=True):
    """Return the target-range midpoint (percent) in force on `day`.

    `decisions` is the meeting table from #2 (`fomc_meetings.csv`), with the
    target bounds before and after each meeting.

    after_announcement=True:
        a meeting announced ON `day` already counts, so on a decision day this
        is the post-announcement level. The cumulative changes that #5 scores
        start from this level.
    after_announcement=False:
        only meetings announced BEFORE `day` count, because a decision takes
        effect the business day after it is announced. This is the level in
        force on `day`, and the one to compare with SOFR on `day`.

    `fit_many` anchors the fit with after_announcement=False and adds a
    decision announced on the observation date as a KNOWN move from its
    effective date. Do not combine a post-announcement anchor with that known
    move: the decision would be counted twice.
    """
    _check_columns(decisions, DECISION_COLUMNS, "decisions")
    day = pd.Timestamp(day)
    table = decisions.copy()
    table["meeting_date"] = pd.to_datetime(table["meeting_date"])
    table = table.sort_values("meeting_date")

    if after_announcement:
        past = table[table["meeting_date"] <= day]
    else:
        past = table[table["meeting_date"] < day]

    if len(past) == 0:
        first = table.iloc[0]
        return (first["target_lower_before"] + first["target_upper_before"]) / 2
    last = past.iloc[-1]
    return (last["target_lower_after"] + last["target_upper_after"]) / 2


def estimate_basis(sofr_fixings, decisions, end_date, n_fixings=20):
    """Average gap SOFR minus policy rate over the last `n_fixings` fixings up to `end_date`.

    This is the "recent realized spread" that METHODOLOGY.md Section 2 uses to
    fix the basis. It needs published daily SOFR, such as data/processed/sofr_daily.csv
    written by fomc_data (Issue #2).
    """
    end_date = pd.Timestamp(end_date)
    recent = sofr_fixings[sofr_fixings.index <= end_date].tail(n_fixings)
    if len(recent) == 0:
        raise ValueError(f"no SOFR fixings on or before {end_date.date()}")

    gaps = []
    for day, rate in recent.items():
        gaps.append(rate - policy_level_on(day, decisions, after_announcement=False))
    return float(np.mean(gaps))


# ---------------------------------------------------------------------------
# Which meetings are unknowns
# ---------------------------------------------------------------------------


def upcoming_meetings(obs_date, meeting_dates, dates, last_day):
    """Meetings announced strictly after `obs_date` that take effect by `last_day`.

    A meeting announced ON the observation date is not an unknown: futures
    settle after the announcement, so that decision is already known.

    Returns:
        A DataFrame with columns meeting_date, effective_date.

    Raises:
        ValueError: if the schedule stops long before `last_day`, which means
            future meetings are missing and their effect would be wrongly
            spread over the meetings that are listed.
    """
    obs_date = pd.Timestamp(obs_date)
    last_day = pd.Timestamp(last_day)
    schedule = sorted(pd.Timestamp(d) for d in meeting_dates)

    if len(schedule) == 0 or (last_day - schedule[-1]).days > MAX_SCHEDULE_GAP_DAYS:
        last = schedule[-1].date() if schedule else "nothing"
        raise ValueError(
            f"meeting schedule ends at {last}, but contracts run to {last_day.date()}: "
            "add the announced future meeting dates, or use contracts closer in"
        )

    rows = []
    for meeting in schedule:
        if meeting <= obs_date:
            continue  # already announced: not an unknown
        if meeting >= last_day:
            break  # takes effect after every contract has ended
        effective = effective_date(meeting, dates)
        if effective > last_day:
            break
        rows.append({"meeting_date": meeting, "effective_date": effective})

    return pd.DataFrame(rows, columns=["meeting_date", "effective_date"])


# ---------------------------------------------------------------------------
# The fit for one observation date
# ---------------------------------------------------------------------------


@dataclass
class FitResult:
    """Everything the fit produces for one observation date."""

    obs_date: pd.Timestamp
    meetings: pd.DataFrame  # one row per upcoming meeting: implied moves in bp
    contracts: pd.DataFrame  # one row per contract: market vs model price
    diagnostics: dict = field(default_factory=dict)
    # Price change (bp) of each contract (rows) for a 1 bp move at each meeting
    # (columns). This is the Jacobian, in a readable table.
    sensitivities: pd.DataFrame = field(default_factory=pd.DataFrame)


def fit_meeting_moves(obs_date, contracts, meeting_dates, anchor, basis=0.0,
                      known_moves=None, realized_fixings=None, holidays=(),
                      ridge=DEFAULT_RIDGE, max_iterations=20, tolerance_bps=1e-6):
    """Fit the rate move at each upcoming FOMC meeting to one day's futures prices.

    Args:
        obs_date: the trading day the prices were observed.
        contracts: that day's contracts, with columns root, reference_start,
            reference_end and settlement_price (the shape of
            `sofr_data.settlement_curve(panel, obs_date)` from #1).
        meeting_dates: FOMC ANNOUNCEMENT dates. Must reach past the last contract.
        anchor: policy rate (percent) in force on obs_date, before any meeting
            announced that day takes effect.
        basis: SOFR minus policy rate, in percent, held fixed.
        known_moves: optional {effective_date: change in percent} for decisions
            already announced but not yet in force (for example a decision
            announced on obs_date itself). Applied, not estimated.
        realized_fixings: optional published SOFR (percent, indexed by date).
            If given, every day up to the last published fixing uses it. If not,
            the model path is used for past days too, which can bias contracts
            whose month or quarter has already started.
        holidays: SOFR holidays for the fixing calendar.
        ridge: strength of the penalty that shrinks poorly identified moves to 0.
        max_iterations, tolerance_bps: when to stop the Gauss-Newton loop.

    Returns:
        A FitResult.
    """
    obs_date = pd.Timestamp(obs_date)
    if ridge < 0:
        raise ValueError("ridge must be zero or positive")
    _check_columns(contracts, CONTRACT_COLUMNS, "contracts")

    # --- Step 1: clean the contract table ----------------------------------
    table = contracts.copy()
    for column in ("reference_start", "reference_end"):
        table[column] = pd.to_datetime(table[column])
    table = table[table["settlement_price"].notna()]
    # A contract whose period is already over says nothing about future meetings.
    table = table[table["reference_end"] >= obs_date].reset_index(drop=True)
    if len(table) == 0:
        raise ValueError(f"no usable contracts on {obs_date.date()}")
    market = table["settlement_price"].to_numpy(dtype=float)

    # --- Step 2: calendar, meetings and the price function -----------------
    first_day = table["reference_start"].min() - pd.Timedelta(days=10)
    last_day = table["reference_end"].max()
    dates = fixing_dates(first_day, last_day + pd.Timedelta(days=10), holidays)

    meetings = upcoming_meetings(obs_date, meeting_dates, dates, last_day)
    n_meetings = len(meetings)
    known_moves = {} if known_moves is None else dict(known_moves)

    cutoff = None
    if realized_fixings is not None:
        cutoff = last_known_fixing_date(obs_date, dates)

    def model_prices(moves):
        # Build the SOFR path for these moves and price every contract on it.
        all_moves = dict(known_moves)
        for effective, move in zip(meetings["effective_date"], moves):
            all_moves[effective] = all_moves.get(effective, 0.0) + move
        path = step_fixings(dates, anchor, all_moves, basis)
        if realized_fixings is not None:
            path = splice_realized(realized_fixings, path, cutoff)
        return price_contracts(path, table).to_numpy(dtype=float)

    # --- Step 3: sensitivities (the Jacobian J) ----------------------------
    moves = np.zeros(n_meetings)
    base_prices = model_prices(moves)
    jacobian = np.zeros((len(table), n_meetings))
    for j in range(n_meetings):
        bumped = np.zeros(n_meetings)
        bumped[j] = BUMP
        jacobian[:, j] = (model_prices(bumped) - base_prices) / BUMP

    # --- Step 4: regularized Gauss-Newton ----------------------------------
    prices = base_prices
    iterations = 0
    converged = n_meetings == 0
    for iterations in range(1, max_iterations + 1):
        if n_meetings == 0:
            break
        residual = market - prices
        left = jacobian.T @ jacobian + ridge * np.eye(n_meetings)
        right = jacobian.T @ residual - ridge * moves
        if ridge > 0:
            step = np.linalg.solve(left, right)
        else:
            step = np.linalg.lstsq(jacobian, residual, rcond=None)[0]
        moves = moves + step
        prices = model_prices(moves)
        if np.max(np.abs(step)) * 100 < tolerance_bps:
            converged = True
            break

    # --- Step 5: diagnostics -----------------------------------------------
    residual_bps = (market - prices) * 100
    if n_meetings > 0:
        singular_values = np.linalg.svd(jacobian, compute_uv=False)
        rank = int(np.sum(singular_values > 1e-9 * singular_values[0]))
        smallest = singular_values[-1] if len(singular_values) == n_meetings else 0.0
        condition_number = float(singular_values[0] / smallest) if smallest > 0 else float("inf")
    else:
        rank, condition_number = 0, float("nan")

    diagnostics = {
        "n_contracts": len(table),
        "n_meetings": n_meetings,
        "rmse_bps": float(np.sqrt(np.mean(residual_bps ** 2))),
        "max_abs_residual_bps": float(np.max(np.abs(residual_bps))),
        "jacobian_rank": rank,
        # False means some moves are NOT pinned down by the prices: a price
        # residual near 0 then does not mean the moves were recovered.
        "fully_identified": bool(n_meetings > 0 and rank == n_meetings),
        "condition_number": condition_number,
        "iterations": iterations,
        "converged": bool(converged),
        "used_realized_fixings": realized_fixings is not None,
    }

    meeting_table = meetings.copy()
    meeting_table["implied_move_bps"] = moves * 100
    meeting_table["implied_cum_change_bps"] = np.cumsum(moves) * 100
    # How strongly the prices react to this meeting (sum over contracts, per 1 bp).
    meeting_table["sensitivity"] = np.abs(jacobian).sum(axis=0)

    contract_table = table.copy()
    contract_table["model_price"] = prices
    contract_table["residual_bps"] = residual_bps

    # Prices are in index points and moves in percent, so this ratio is already
    # "bp of price per bp of move".
    labels = table["contract_id"] if "contract_id" in table.columns else table.index
    sensitivities = pd.DataFrame(jacobian, index=list(labels),
                                 columns=[m.date().isoformat() for m in meetings["meeting_date"]])

    return FitResult(obs_date, meeting_table, contract_table, diagnostics, sensitivities)


# ---------------------------------------------------------------------------
# Many observation dates -> the table #5 consumes
# ---------------------------------------------------------------------------


def fit_many(panel, obs_dates, decisions, meeting_dates=None, basis=0.0,
             realized_fixings=None, months_ahead=18, holidays=(),
             ridge=DEFAULT_RIDGE, skip_errors=False):
    """Run the fit for every observation date.

    Args:
        panel: settlement panel in the shape of #1 (one row per contract per
            trade_date, with root, reference_start, reference_end, settlement_price).
        obs_dates: the trading days to fit.
        decisions: the meeting table from #2 (target bounds before/after).
            It gives the anchor and, on decision days, the move just announced.
            Only meetings announced on or before each obs_date are used, so
            there is no look-ahead.
        meeting_dates: ANNOUNCEMENT dates of all scheduled meetings, including
            announced future ones beyond the realized table. Defaults to the
            meeting dates in `decisions`.
        basis: SOFR minus policy rate (percent), held fixed.
        realized_fixings: optional published daily SOFR.
        months_ahead: only use contracts whose period ends within this many months.
        skip_errors: if True, a date that fails is recorded in the diagnostics
            instead of stopping the run.

    Returns:
        (implied, diagnostics):
        implied: one row per (obs_date, meeting) with columns obs_date,
            meeting_date, effective_date, implied_move_bps, implied_cum_change_bps.
            These are the column names PR #15 expects.
        diagnostics: one row per obs_date.
    """
    _check_columns(panel, ["trade_date", *CONTRACT_COLUMNS], "panel")
    _check_columns(decisions, DECISION_COLUMNS, "decisions")

    panel = panel.copy()
    for column in ("trade_date", "reference_start", "reference_end"):
        panel[column] = pd.to_datetime(panel[column])
    decisions = decisions.copy()
    decisions["meeting_date"] = pd.to_datetime(decisions["meeting_date"])
    if meeting_dates is None:
        meeting_dates = decisions["meeting_date"].tolist()

    implied_rows = []
    diagnostic_rows = []

    for obs_date in pd.to_datetime(list(obs_dates)):
        try:
            horizon_end = obs_date + pd.DateOffset(months=months_ahead)
            day = panel[(panel["trade_date"] == obs_date)
                        & (panel["reference_end"] <= horizon_end)]

            # Anchor: the level in force today, before any decision announced today.
            anchor = policy_level_on(obs_date, decisions, after_announcement=False)

            # A decision announced today is known at settlement: apply it, don't fit it.
            known = {}
            today = decisions[decisions["meeting_date"] == obs_date]
            if len(today) > 0:
                post = policy_level_on(obs_date, decisions, after_announcement=True)
                calendar = fixing_dates(obs_date, obs_date + pd.Timedelta(days=10), holidays)
                known = {effective_date(obs_date, calendar): post - anchor}

            result = fit_meeting_moves(obs_date, day, meeting_dates, anchor, basis=basis,
                                       known_moves=known, realized_fixings=realized_fixings,
                                       holidays=holidays, ridge=ridge)
        except ValueError as error:
            if not skip_errors:
                raise
            diagnostic_rows.append({"obs_date": obs_date, "error": str(error)})
            continue

        rows = result.meetings.assign(obs_date=obs_date)
        implied_rows.append(rows[["obs_date", "meeting_date", "effective_date",
                                  "implied_move_bps", "implied_cum_change_bps"]])
        diagnostic_rows.append({"obs_date": obs_date, **result.diagnostics, "error": None})

    columns = ["obs_date", "meeting_date", "effective_date", "implied_move_bps", "implied_cum_change_bps"]
    implied = pd.concat(implied_rows, ignore_index=True) if implied_rows else pd.DataFrame(columns=columns)
    return implied, pd.DataFrame(diagnostic_rows)
