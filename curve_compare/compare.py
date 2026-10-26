"""Compare the full model and the simplified curve at the next-meeting horizon (Issue #6).

"Next-meeting horizon" is horizon 1 in `forecast_eval` (PR #15, Issue #5): for
an observation date `t`, the target is the first scheduled FOMC meeting
strictly after `t`. A meeting's own decision day is not its own target.

Both methods are fit in SOFR-rate space, because an SR1 price is an average
of SOFR. `forecast_eval` scores a cumulative change in the POLICY rate, in
basis points. The conversion is

    implied change = (model SOFR at the next meeting − basis − policy rate now) × 100

`basis` is fixed before scoring, not estimated inside the bootstrap. On the
synthetic world it is the known constant `spread_pct`. On real data it is
`sofr_pricing.estimate_basis` (a trailing average of SOFR minus the target
midpoint). The realized change comes from the meeting's target-midpoint move.
`build_forecast_errors` then subtracts that realized change, so the reported
error, bias, MAE and RMSE are `forecast_eval`'s, at horizon 1 only.
"""

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from curve_compare.full_model import anchor_sofr_rate, implied_daily_path, published_sofr, recover_full_model_path
from curve_compare.simple_curve import simple_curve_path
from forecast_eval.metrics import (
    build_forecast_errors,
    error_by_days_to_meeting,
    summarize_by_horizon,
    weekly_day_bins,
)
from sofr_pricing.estimation import estimate_basis, policy_level_on

METHODS = ("full_model", "simple_curve")

# Columns a real decision table needs before `policy_level_on` can read it.
_POLICY_COLUMNS = {
    "meeting_date",
    "target_lower_before",
    "target_upper_before",
    "target_lower_after",
    "target_upper_after",
}

# Skips US federal holidays (not just weekends) so a window starting near
# January 1st does not land on New Year's Day itself.
_FEDERAL_BUSINESS_DAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def sr1_strip_as_of(sr1_contracts, obs_date, months_ahead=9):
    """The SR1 contracts still outstanding as of `obs_date`, nearest first."""
    obs_date = pd.Timestamp(obs_date)
    strip = sr1_contracts[sr1_contracts["month_end"] > obs_date]
    return strip.sort_values("month_start").head(months_ahead).reset_index(drop=True)


def strip_for(world, obs_date, months_ahead=9):
    """SR1 strip used to fit both methods on `obs_date`.

    A synthetic world stores one perfect-foresight strip (`sr1_contracts`).
    A real world stores a settlement panel (`sr1_panel`) with a `trade_date`
    column; only that session's prices are used.
    """
    obs_date = pd.Timestamp(obs_date).normalize()
    panel = getattr(world, "sr1_panel", None)
    if panel is None:
        contracts = world.sr1_contracts
    else:
        trade_dates = pd.to_datetime(panel["trade_date"]).dt.normalize()
        day = panel.loc[trade_dates == obs_date, ["month_start", "month_end", "price"]]
        if day.empty:
            raise ValueError(f"no SR1 settlements on {obs_date.date()}")
        contracts = day
    return sr1_strip_as_of(contracts, obs_date, months_ahead)


def next_meeting_after(meeting_dates, obs_date):
    """The first scheduled meeting strictly after `obs_date` (the horizon-1 target)."""
    obs_date = pd.Timestamp(obs_date)
    future = sorted(pd.Timestamp(m) for m in meeting_dates if pd.Timestamp(m) > obs_date)
    if not future:
        raise ValueError(f"no scheduled meeting after {obs_date.date()}")
    return future[0]


def default_obs_dates(world):
    """Business days from just before the first meeting to just before the last.

    A real world can set `obs_dates` to the sessions that actually have an
    SR1 settlement. Otherwise the window is every US business day on which
    the next meeting still has a known outcome.

    Stops before the last meeting so that `next_meeting_after` can always
    find a meeting to score. Uses a US-federal-holiday calendar, not just
    weekdays, so a window starting near January 1st begins on the first real
    business day rather than on New Year's Day.
    """
    custom = getattr(world, "obs_dates", None)
    if custom is not None:
        return pd.DatetimeIndex(pd.to_datetime(list(custom))).normalize()
    start = pd.Timestamp(world.meeting_dates[0]) - pd.Timedelta(days=30)
    end = pd.Timestamp(world.meeting_dates[-1]) - pd.Timedelta(days=1)
    return pd.date_range(start, end, freq=_FEDERAL_BUSINESS_DAY)


def realized_decisions(world):
    """Realized meeting moves in the shape `forecast_eval` expects.

    A real world passes the team's decision table through (`meeting_date`,
    `change_bps`, plus the target bounds used to fix the basis). A synthetic
    world has no such table; the moves are the seeded path.
    """
    decisions = getattr(world, "decisions", None)
    if decisions is not None and {"meeting_date", "change_bps"} <= set(decisions.columns):
        table = decisions[["meeting_date", "change_bps"]].copy()
        table["meeting_date"] = pd.to_datetime(table["meeting_date"]).dt.normalize()
        table["change_bps"] = pd.to_numeric(table["change_bps"])
        return table.reset_index(drop=True)
    return pd.DataFrame({
        "meeting_date": pd.to_datetime(list(world.meeting_dates)).normalize(),
        "change_bps": [float(world.move_at(day)) for day in world.meeting_dates],
    })


def policy_rate_on(world, obs_date):
    """Policy rate in force on `obs_date`, in percent, after a decision that day.

    On a decision day the post-announcement level is the anchor `forecast_eval`
    uses, so the cumulative change starts after that day's decision. Real
    tables use `sofr_pricing.policy_level_on`. The synthetic path stores the
    same step directly on `true_policy`.
    """
    decisions = getattr(world, "decisions", None)
    if decisions is not None and _POLICY_COLUMNS <= set(decisions.columns):
        return float(policy_level_on(obs_date, decisions, after_announcement=True))
    return float(world.true_policy.loc[pd.Timestamp(obs_date)])


def basis_on(world, obs_date):
    """SOFR minus the policy rate, in percent. Fixed, not fit with the moves.

    Real worlds set `fix_basis` and use `sofr_pricing.estimate_basis`. The
    synthetic spread is a known constant (`world.spread_pct`).
    """
    if getattr(world, "fix_basis", False):
        return float(estimate_basis(_available_sofr_on(world, obs_date), world.decisions, obs_date))
    return float(world.spread_pct)


def _available_sofr_on(world, obs_date):
    """Fixings available at settlement; synthetic calendar rates are fully observed."""
    if getattr(world, "fix_basis", False):
        return published_sofr(world.daily_sofr, obs_date)
    return world.daily_sofr.loc[:pd.Timestamp(obs_date).normalize()]


def _anchor_on(world, obs_date, anchor_window_days):
    moves = realized_decisions(world).set_index("meeting_date")["change_bps"]
    return anchor_sofr_rate(_available_sofr_on(world, obs_date), obs_date, world.meeting_dates, moves, anchor_window_days)


def _rates_at_next_meeting(world, obs_date, months_ahead, anchor_window_days):
    """Fit both methods and convert each rate into an implied policy change, in bp."""
    obs_date = pd.Timestamp(obs_date).normalize()
    strip = strip_for(world, obs_date, months_ahead)
    next_meeting = next_meeting_after(world.meeting_dates, obs_date)
    baseline = _anchor_on(world, obs_date, anchor_window_days)
    deltas = recover_full_model_path(
        strip, world.meeting_dates, baseline, obs_date, _available_sofr_on(world, obs_date)
    )
    if pd.Timestamp(next_meeting) not in deltas:
        raise ValueError(
            f"SR1 strip on {obs_date.date()} does not cover the next meeting "
            f"{pd.Timestamp(next_meeting).date()}"
        )
    full_sofr = float(implied_daily_path([next_meeting], baseline, deltas).iloc[0])
    simple_sofr = float(simple_curve_path(strip, obs_date, [next_meeting]).iloc[0])
    policy = policy_rate_on(world, obs_date)
    basis = basis_on(world, obs_date)
    return {
        "obs_date": obs_date,
        "next_meeting": pd.Timestamp(next_meeting),
        "full_model": (full_sofr - basis - policy) * 100.0,
        "simple_curve": (simple_sofr - basis - policy) * 100.0,
    }


def build_scoring_tables(world, obs_dates, months_ahead=9, anchor_window_days=5):
    """Implied-path tables (one per method) and the realized-decision table.

    These are the two inputs `forecast_eval.build_forecast_errors` asks for.
    Only the next meeting is filled in: horizons beyond 1 are out of scope.
    """
    rows = {method: [] for method in METHODS}
    for obs_date in obs_dates:
        rates = _rates_at_next_meeting(world, obs_date, months_ahead, anchor_window_days)
        for method in METHODS:
            rows[method].append({
                "obs_date": rates["obs_date"],
                "meeting_date": rates["next_meeting"],
                "implied_cum_change_bps": rates[method],
            })
    implied = {method: pd.DataFrame(rows[method]) for method in METHODS}
    return implied, realized_decisions(world)


def _score(implied, realized, obs_dates):
    """Horizon-1 errors from `forecast_eval`, aligned to `obs_dates`."""
    order = pd.DatetimeIndex(pd.to_datetime(list(obs_dates))).normalize()
    scored = {}
    for method in METHODS:
        errors = build_forecast_errors(implied[method], realized, max_horizon=1)
        if errors.empty:
            raise ValueError(f"forecast_eval returned no {method} errors")
        aligned = errors.set_index("obs_date").reindex(order)
        if aligned["error_bps"].isna().any():
            raise ValueError(
                f"forecast_eval dropped {method} observations; each date needs a next "
                "meeting on the realized schedule"
            )
        scored[method] = aligned
    return scored


def run_comparison(world, obs_dates=None, months_ahead=9, anchor_window_days=5):
    """Score both methods on `obs_dates` (default: `default_obs_dates(world)`).

    The error columns are `forecast_eval`'s horizon-1 `error_bps` (implied
    cumulative change minus realized cumulative change).
    """
    obs_dates = default_obs_dates(world) if obs_dates is None else list(obs_dates)
    implied, realized = build_scoring_tables(world, obs_dates, months_ahead, anchor_window_days)
    scored = _score(implied, realized, obs_dates)
    full = scored["full_model"]
    simple = scored["simple_curve"]
    return pd.DataFrame({
        "obs_date": full.index,
        "next_meeting": full["meeting_date"].to_numpy(),
        "days_to_meeting": full["days_to_meeting"].to_numpy(),
        "rate_change_at_meeting": full["realized_move_bps"].to_numpy() != 0.0,
        "full_model_error_bps": full["error_bps"].to_numpy(),
        "simple_curve_error_bps": simple["error_bps"].to_numpy(),
    })


def compare_at_date(world, obs_date, months_ahead=9, anchor_window_days=5):
    """Run both methods at one observation date; return one result dict."""
    return run_comparison(world, [obs_date], months_ahead, anchor_window_days).iloc[0].to_dict()


def _as_eval_errors(results, method):
    """One method's errors, in the column layout `forecast_eval` summarizes.

    Bias, MAE and RMSE are recomputed by `summarize_by_horizon` from the
    horizon-1 errors. Direction columns are left blank: this comparison
    reports the error in bp, not the hike/hold/cut hit rate.
    """
    if len(results) == 0:
        raise ValueError("no forecast errors to summarize; check that the implied and realized tables overlap")
    n_obs = len(results)
    return pd.DataFrame({
        "obs_date": pd.to_datetime(results["obs_date"].to_numpy()),
        "horizon": np.ones(n_obs, dtype=int),
        "meeting_date": pd.to_datetime(results["next_meeting"].to_numpy()),
        "days_to_meeting": results["days_to_meeting"].to_numpy(),
        "error_bps": results[f"{method}_error_bps"].to_numpy(dtype=float),
        "implied_move_bps": np.full(n_obs, np.nan),
        "realized_move_bps": np.full(n_obs, np.nan),
        "direction_hit": np.full(n_obs, np.nan),
    })


def _horizon_stats(results, method):
    """Bias, MAE and RMSE (bp) for one method, from `forecast_eval`."""
    stats = summarize_by_horizon(_as_eval_errors(results, method)).loc[1]
    return {
        "n_obs": int(stats["n_obs"]),
        "bias_bps": float(stats["bias_bps"]),
        "mae_bps": float(stats["mae_bps"]),
        "rmse_bps": float(stats["rmse_bps"]),
    }


def summarize_errors(results):
    """One row per method: n_obs, bias, MAE, RMSE (bp), at the next meeting."""
    rows = {method: _horizon_stats(results, method) for method in METHODS}
    return pd.DataFrame(rows).T.loc[list(METHODS)]


def method_difference_bps(results):
    """Simplified-curve error minus full-model error, in bp, at each observation.

    Both errors are the horizon-1 errors from `forecast_eval`.
    """
    return results["simple_curve_error_bps"] - results["full_model_error_bps"]


def summarize_by_regime(results):
    """Accuracy by whether the forecasted meeting changed the target rate.

    The split is this comparison's own (a change versus a hold). The bias,
    MAE and RMSE inside each row come from `forecast_eval.summarize_by_horizon`.
    `forecast_eval`'s own regime table is a split by year, which is a different
    question; it is not what Issue #6 asks for.
    """
    rows = []
    for name, changed in (("change", True), ("hold", False)):
        group = results.loc[results["rate_change_at_meeting"] == changed]
        if len(group) == 0:
            continue
        row = {"regime": name, "n_obs": len(group)}
        for method in METHODS:
            stats = _horizon_stats(group, method)
            row[f"{method}_bias_bps"] = stats["bias_bps"]
            row[f"{method}_mae_bps"] = stats["mae_bps"]
            row[f"{method}_rmse_bps"] = stats["rmse_bps"]
        rows.append(row)
    if not rows:
        raise ValueError("no forecast errors to summarize; check that the implied and realized tables overlap")
    return pd.DataFrame(rows).set_index("regime")


def summarize_by_days_to_meeting(results, width_days=7):
    """Accuracy by calendar days before the meeting, for both methods.

    Bucket edges and the bias / MAE / RMSE come from `forecast_eval`
    (`weekly_day_bins` and `error_by_days_to_meeting`).
    """
    pieces = []
    for method in METHODS:
        frame = _as_eval_errors(results, method)
        edges = weekly_day_bins(frame, horizon=1, width_days=width_days)
        table = error_by_days_to_meeting(frame, horizon=1, bins=edges, open_ended=False)
        renamed = table[["bias_bps", "mae_bps", "rmse_bps"]].rename(
            columns={
                "bias_bps": f"{method}_bias_bps",
                "mae_bps": f"{method}_mae_bps",
                "rmse_bps": f"{method}_rmse_bps",
            }
        )
        if method == METHODS[0]:
            renamed.insert(0, "n_obs", table["n_obs"].astype(int))
        pieces.append(renamed)
    return pieces[0].join(pieces[1])


def worst_periods(results, n=5):
    """The target meetings with the largest simplified-curve MAE.

    A "period" is one meeting, not one day: the days aimed at that meeting
    share a single outcome. MAE is `forecast_eval`'s.
    """
    rows = []
    for meeting, group in results.groupby("next_meeting", sort=False):
        row = {
            "next_meeting": pd.Timestamp(meeting),
            "n_obs": len(group),
            "rate_change": bool(group["rate_change_at_meeting"].iloc[0]),
        }
        for method in METHODS:
            stats = _horizon_stats(group, method)
            row[f"{method}_bias_bps"] = stats["bias_bps"]
            row[f"{method}_mae_bps"] = stats["mae_bps"]
        rows.append(row)
    table = pd.DataFrame(rows).sort_values("simple_curve_mae_bps", ascending=False)
    return table.head(n).reset_index(drop=True)


def implied_paths_for_plot(world, obs_date, horizon_days=240, months_ahead=9, anchor_window_days=5):
    """Daily true, full-model and simple-curve policy-rate paths, for plotting.

    The basis subtracted here is the same fixed basis the scorer uses, so the
    picture is in policy-rate space.
    """
    obs_date = pd.Timestamp(obs_date).normalize()
    dates = pd.date_range(obs_date, periods=horizon_days, freq="D")
    strip = strip_for(world, obs_date, months_ahead)
    baseline = _anchor_on(world, obs_date, anchor_window_days)
    deltas = recover_full_model_path(
        strip, world.meeting_dates, baseline, obs_date, _available_sofr_on(world, obs_date)
    )
    basis = basis_on(world, obs_date)
    full_path = implied_daily_path(dates, baseline, deltas) - basis
    simple_path = simple_curve_path(strip, obs_date, dates) - basis
    true_path = world.true_policy.reindex(dates)
    return pd.DataFrame({"true": true_path, "full_model": full_path, "simple_curve": simple_path})
