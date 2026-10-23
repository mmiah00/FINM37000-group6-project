"""Tests for curve_compare (Issue #6)."""

import pandas as pd
import pytest

from curve_compare.calendar import meeting_calendar
from curve_compare.compare import (
    build_scoring_tables,
    compare_at_date,
    default_obs_dates,
    implied_paths_for_plot,
    run_comparison,
    sr1_strip_as_of,
    summarize_by_days_to_meeting,
    summarize_by_regime,
    summarize_errors,
)
from curve_compare.full_model import observed_sofr_total, recover_full_model_path
from curve_compare.real_data import load_real_world, world_from_frames
from curve_compare.synthetic import generate_synthetic_world, generate_sr1_contracts
from forecast_eval import build_forecast_errors
from sofr_pricing.pricing import sr1_rate


def test_full_model_recovers_true_path_from_noiseless_sr1_prices():
    """With no SOFR noise, no price noise, and no spread, the recovered deltas
    must equal the true policy moves exactly (Section 12 of docs/METHODOLOGY.md:
    "generate prices from a known path, then recover the path")."""
    world = generate_synthetic_world(sofr_noise_bps=0.0, price_noise_bps=0.0, spread_pct=0.0, seed=0)

    obs_date = world.meeting_dates[2] + pd.Timedelta(days=3)
    strip = sr1_strip_as_of(world.sr1_contracts, obs_date, months_ahead=9)
    baseline = float(world.true_policy.loc[obs_date])

    deltas = recover_full_model_path(strip, world.meeting_dates, baseline, obs_date, world.daily_sofr)

    future_meetings = [m for m in world.meeting_dates if m > obs_date and m <= strip["month_end"].max()]
    assert len(future_meetings) > 0
    for meeting in future_meetings:
        true_delta = world.move_at(meeting) / 100.0
        assert deltas[meeting] == pytest.approx(true_delta, abs=1e-9)


def test_post_meeting_anchor_keeps_next_forecast_and_plot_on_current_rate():
    world = generate_synthetic_world(sofr_noise_bps=0.0, price_noise_bps=0.0, spread_pct=0.0, seed=0)
    obs_date = world.meeting_dates[2] + pd.Timedelta(days=1)

    result = compare_at_date(world, obs_date)
    paths = implied_paths_for_plot(world, obs_date, horizon_days=50)

    assert result["full_model_error_bps"] == pytest.approx(0.0, abs=1e-9)
    assert paths.loc[obs_date, "full_model"] == pytest.approx(world.true_policy.loc[obs_date], abs=1e-9)
    assert paths.loc[result["next_meeting"], "full_model"] == pytest.approx(
        world.true_policy.loc[result["next_meeting"]], abs=1e-9
    )


def test_elapsed_sr1_fixings_are_used_for_late_month_forecasts_and_paths():
    world = generate_synthetic_world(n_meetings=2, moves_bps=[50, 0], sofr_noise_bps=0.0, spread_pct=0.0)
    obs_date = pd.Timestamp("2024-01-30")
    world.daily_sofr.loc["2024-01-26":obs_date] = 4.1
    world.sr1_contracts = generate_sr1_contracts(
        world.daily_sofr, world.sr1_contracts["month_start"], price_noise_bps=0.0
    )

    result = compare_at_date(world, obs_date)
    paths = implied_paths_for_plot(world, obs_date, horizon_days=3)

    assert result["full_model_error_bps"] == pytest.approx(0.0, abs=1e-9)
    assert paths.loc[world.meeting_dates[0], "full_model"] == pytest.approx(
        world.true_policy.loc[world.meeting_dates[0]], abs=1e-9
    )


def test_synthetic_history_covers_default_observations_for_early_month_meeting():
    world = generate_synthetic_world(start="2024-03-20", sofr_noise_bps=0.0)
    first_obs_date = default_obs_dates(world)[0]

    assert first_obs_date in world.daily_sofr.index
    assert pd.notna(compare_at_date(world, first_obs_date)["full_model_error_bps"])


def test_simplified_curve_error_is_larger_around_meetings_with_a_rate_change():
    """The headline check for Issue #6: a smooth curve that ignores FOMC timing
    should do noticeably worse when the next meeting actually moves the rate
    than when it is a hold, while the full model should not show nearly as
    large a gap."""
    world = generate_synthetic_world(seed=0)
    results = run_comparison(world, default_obs_dates(world))
    by_regime = summarize_by_regime(results)

    assert by_regime.loc["change", "simple_curve_mae_bps"] > by_regime.loc["hold", "simple_curve_mae_bps"]
    # The gap should be large, not just statistically nonzero: this is the
    # property the comparison exists to demonstrate.
    assert by_regime.loc["change", "simple_curve_mae_bps"] > 5 * by_regime.loc["hold", "simple_curve_mae_bps"]


def test_full_model_more_accurate_than_simplified_curve_overall():
    """Sanity check: explicitly modeling FOMC timing should reduce next-meeting
    forecast error overall, not just around rate changes."""
    world = generate_synthetic_world(seed=0)
    results = run_comparison(world, default_obs_dates(world))

    full_mae = results["full_model_error_bps"].abs().mean()
    simple_mae = results["simple_curve_error_bps"].abs().mean()
    assert full_mae < simple_mae


def test_sr1_strip_as_of_only_includes_unexpired_contracts():
    world = generate_synthetic_world(seed=0)
    obs_date = world.meeting_dates[5]
    strip = sr1_strip_as_of(world.sr1_contracts, obs_date, months_ahead=4)
    assert len(strip) == 4
    assert (strip["month_end"] > obs_date).all()
    assert strip["month_start"].is_monotonic_increasing


def test_next_meeting_after_raises_past_the_last_meeting():
    from curve_compare.compare import next_meeting_after

    world = generate_synthetic_world(seed=0)
    with pytest.raises(ValueError):
        next_meeting_after(world.meeting_dates, world.meeting_dates[-1])


def test_meeting_dates_come_from_fomc_data(monkeypatch):
    """The synthetic schedule is a slice of fomc_data, not an even grid.

    An even grid of 8 meetings a year from 2024-01-31 would put the second
    meeting on 2024-03-17. The Fed's second 2024 meeting is 2024-03-20.
    """
    import curve_compare.calendar as calendar

    real = calendar.fetch_fomc_calendar

    def wrapper(*args, **kwargs):
        wrapper.calls += 1
        return real(*args, **kwargs)

    wrapper.calls = 0
    monkeypatch.setattr(calendar, "fetch_fomc_calendar", wrapper)

    world = generate_synthetic_world(seed=0)
    assert wrapper.calls >= 1
    assert world.meeting_dates[0] == pd.Timestamp("2024-01-31")
    assert world.meeting_dates[1] == pd.Timestamp("2024-03-20")
    assert world.meeting_dates == meeting_calendar(start="2024-01-31")[:16]


def test_scores_match_forecast_eval_horizon_1():
    """Next-meeting errors are forecast_eval's horizon-1 error, unchanged."""
    world = generate_synthetic_world(
        n_meetings=4,
        moves_bps=[25, 0, -25, 25],
        sofr_noise_bps=1.0,
        spread_pct=0.03,
        seed=2,
    )
    obs_dates = default_obs_dates(world)[::12]
    results = run_comparison(world, obs_dates)
    implied, realized = build_scoring_tables(world, obs_dates)
    for method, column in (
        ("full_model", "full_model_error_bps"),
        ("simple_curve", "simple_curve_error_bps"),
    ):
        scored = build_forecast_errors(implied[method], realized, max_horizon=1)
        merged = results.merge(scored, on="obs_date")
        assert len(merged) == len(results)
        assert merged[column].to_numpy() == pytest.approx(merged["error_bps"].to_numpy())
        assert (merged["horizon"] == 1).all()


def test_summary_tables_call_forecast_eval(monkeypatch):
    import curve_compare.compare as compare

    calls = []

    def wrap(name, fn):
        def inner(*args, **kwargs):
            calls.append(name)
            return fn(*args, **kwargs)
        return inner

    monkeypatch.setattr(compare, "build_forecast_errors", wrap("build", compare.build_forecast_errors))
    monkeypatch.setattr(compare, "summarize_by_horizon", wrap("horizon", compare.summarize_by_horizon))
    monkeypatch.setattr(compare, "error_by_days_to_meeting", wrap("days", compare.error_by_days_to_meeting))

    world = generate_synthetic_world(
        n_meetings=3, moves_bps=[25, 0, -25], sofr_noise_bps=0.0, spread_pct=0.0
    )
    results = run_comparison(world, default_obs_dates(world)[::20])
    summarize_errors(results)
    summarize_by_regime(results)
    summarize_by_days_to_meeting(results)
    assert {"build", "horizon", "days"} <= set(calls)


def test_observed_total_matches_sr1_rate_and_weekend_carry():
    """Calendar-day totals agree with sofr_pricing; business-day series carry Friday."""
    world = generate_synthetic_world(
        n_meetings=2, moves_bps=[25, 0], sofr_noise_bps=0.0, spread_pct=0.0
    )
    start = world.sr1_contracts.loc[0, "month_start"]
    end = world.sr1_contracts.loc[0, "month_end"]
    total, days = observed_sofr_total(world.daily_sofr, start, end)
    assert days == (end - start).days + 1
    assert total / days == pytest.approx(sr1_rate(world.daily_sofr, start, end))
    assert total == pytest.approx(world.daily_sofr.loc[start:end].sum())

    # Friday 2024-06-14 carries across the weekend. Monday's fixing is not in force yet.
    business = pd.Series([1.0, 3.0], index=pd.to_datetime(["2024-06-14", "2024-06-17"]))
    carried, carried_days = observed_sofr_total(business, "2024-06-14", "2024-06-16")
    assert carried_days == 3
    assert carried == pytest.approx(3.0)
    assert carried / carried_days == pytest.approx(sr1_rate(business, "2024-06-14", "2024-06-16"))


def test_business_day_sofr_still_recovers_the_meeting_move():
    """NY Fed SOFR has no weekend rows. The bootstrap follows sofr_pricing's carry."""
    world = generate_synthetic_world(
        n_meetings=2, moves_bps=[25, 0], sofr_noise_bps=0.0, spread_pct=0.0, price_noise_bps=0.0
    )
    business = world.daily_sofr[world.daily_sofr.index.day_of_week < 5]
    world.daily_sofr = business
    world.sr1_contracts = generate_sr1_contracts(business, world.sr1_contracts["month_start"])
    obs_date = world.meeting_dates[0] - pd.Timedelta(days=10)
    result = compare_at_date(world, obs_date)
    assert result["full_model_error_bps"] == pytest.approx(0.0, abs=1e-8)


def _sample_decisions():
    return pd.DataFrame([
        {
            "meeting_date": pd.Timestamp("2024-01-31"),
            "effective_date": pd.NaT,
            "target_lower_before": 5.25,
            "target_upper_before": 5.50,
            "target_lower_after": 5.25,
            "target_upper_after": 5.50,
            "change_bps": 0.0,
            "decision": "hold",
        },
        {
            "meeting_date": pd.Timestamp("2024-03-20"),
            "effective_date": pd.Timestamp("2024-03-21"),
            "target_lower_before": 5.25,
            "target_upper_before": 5.50,
            "target_lower_after": 5.00,
            "target_upper_after": 5.25,
            "change_bps": -25.0,
            "decision": "cut",
        },
    ])


def _sample_sofr():
    days = pd.bdate_range("2024-01-16", "2024-03-19")
    return pd.DataFrame({"date": days, "sofr": 5.33})


def _sample_settlements():
    rows = []
    for trade_date in pd.bdate_range("2024-02-01", "2024-02-20"):
        rows.append({
            "trade_date": trade_date,
            "root": "SR1",
            "reference_start": pd.Timestamp("2024-02-01"),
            "reference_end": pd.Timestamp("2024-02-29"),
            "settlement_price": 94.67,
            "settlement_is_final": True,
        })
        rows.append({
            "trade_date": trade_date,
            "root": "SR1",
            "reference_start": pd.Timestamp("2024-03-01"),
            "reference_end": pd.Timestamp("2024-03-31"),
            "settlement_price": 94.80,
            "settlement_is_final": False,
        })
    return pd.DataFrame(rows)


def test_real_frames_use_fomc_calendar_and_forecast_eval():
    world = world_from_frames(_sample_settlements(), _sample_sofr(), _sample_decisions())
    assert world.meeting_dates == [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-03-20")]
    assert world.fix_basis is True
    result = compare_at_date(world, world.obs_dates[0])
    assert result["next_meeting"] == pd.Timestamp("2024-03-20")
    assert pd.notna(result["full_model_error_bps"])
    assert pd.notna(result["simple_curve_error_bps"])
    # The panel's reference window is the contract month, not a recomputed date.
    march = world.sr1_panel.loc[world.sr1_panel["month_start"] == pd.Timestamp("2024-03-01")]
    assert march["month_end"].iloc[0] == pd.Timestamp("2024-03-31")


def test_real_world_rejects_a_date_off_the_fomc_calendar():
    decisions = _sample_decisions()
    decisions.loc[0, "meeting_date"] = pd.Timestamp("2024-01-30")
    with pytest.raises(ValueError, match="fomc_data"):
        world_from_frames(_sample_settlements(), _sample_sofr(), decisions)


def test_load_real_world_reads_team_processed_files(monkeypatch, tmp_path):
    panel = _sample_settlements()

    def fake_load(roots=None, start=None, end=None):
        fake_load.roots = roots
        return panel

    monkeypatch.setattr("curve_compare.real_data.load_settlements", fake_load)
    sofr_path = tmp_path / "sofr_daily.csv"
    fomc_path = tmp_path / "fomc_meetings.csv"
    _sample_sofr().to_csv(sofr_path, index=False)
    _sample_decisions().to_csv(fomc_path, index=False)
    monkeypatch.setattr("curve_compare.real_data.SOFR_CSV", sofr_path)
    monkeypatch.setattr("curve_compare.real_data.FOMC_CSV", fomc_path)

    world = load_real_world()
    assert fake_load.roots == ("SR1",)
    assert list(world.meeting_dates) == list(meeting_calendar(start="2024-01-31", end="2024-03-20"))


def test_missing_real_files_name_the_build_commands(monkeypatch, tmp_path):
    def missing_settlements(roots=None):
        raise FileNotFoundError("Build it with python -m scripts.fetch_sofr_futures")

    monkeypatch.setattr("curve_compare.real_data.load_settlements", missing_settlements)
    monkeypatch.setattr("curve_compare.real_data.SOFR_CSV", tmp_path / "missing_sofr.csv")
    monkeypatch.setattr("curve_compare.real_data.FOMC_CSV", tmp_path / "missing_fomc.csv")
    with pytest.raises(FileNotFoundError) as exc:
        load_real_world()
    message = str(exc.value)
    assert "fetch_sofr_futures" in message
    assert "fetch_rate_data" in message


def test_default_obs_dates_skips_new_years_day():
    """The default window starts 30 days before the 2024-01-31 meeting, which
    falls on New Year's Day; it should start on the next real business day
    instead (2024-01-02 is a Tuesday, so it is the first one)."""
    world = generate_synthetic_world(seed=0)
    first_obs_date = default_obs_dates(world)[0]
    assert first_obs_date != pd.Timestamp("2024-01-01")
    assert first_obs_date == pd.Timestamp("2024-01-02")
