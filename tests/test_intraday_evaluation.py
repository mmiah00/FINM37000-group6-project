"""Tests for the closing check and sample summaries of the intraday study (Issue #8).

The synthetic drill plants a known pre-statement path and a known announced move, so
the surprise and the closing error can be checked against numbers we chose. The
other tests use small hand-built tables so each rule is visible. No network.
"""

import socket

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from fomc_intraday.evaluation import (
    TOLERANCE_BPS,
    WINDOW_NAMES,
    announcement_summary,
    horizon_summary,
    noise_floor,
    select_headline_events,
    window_changes,
    window_summary,
)
from fomc_intraday.plots import plot_repricing_windows, plot_surprise_check


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("these tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


# --- hand-built tables ---------------------------------------------------------------------


def _snapshots(rows):
    """rows: (label, date, priced_1355, level_1600). One horizon-1 row per snapshot."""
    records = []
    for label, day, pre, final in rows:
        for snapshot, level in (("pre_1355", pre), ("post_1600", final)):
            records.append({
                "announcement_date": pd.Timestamp(day), "label": label, "snapshot": snapshot,
                "horizon": 1, "meeting_date": pd.Timestamp(day),
                "implied_cum_change_bps": level, "delta_cum_bps": final - pre if snapshot == "post_1600" else 0.0,
            })
    return pd.DataFrame(records)


def _diagnostics(identified):
    return pd.DataFrame({
        "label": list(identified), "snapshot": "post_1600", "fully_identified": list(identified.values()),
    })


def _decisions(moves):
    return pd.DataFrame({
        "meeting_date": [pd.Timestamp(day) for day in moves], "change_bps": list(moves.values()),
    })


@pytest.fixture
def three_afternoons():
    """A usable big surprise, a fit-error day with the largest fitted move, and an unidentified day."""
    snapshots = _snapshots([
        ("news", "2024-09-18", -37.0, -48.0),       # announced -50: surprise -13, closing error +2... see below
        ("artifact", "2025-10-29", -24.7, -20.2),    # announced -25: surprise -0.3, but the fit says +4.5
        ("rank_short", "2022-03-16", 28.6, 26.5),    # announced +25, not fully identified
    ])
    decisions = _decisions({"2024-09-18": -50.0, "2025-10-29": -25.0, "2022-03-16": 25.0})
    diagnostics = _diagnostics({"news": True, "artifact": True, "rank_short": False})
    return snapshots, diagnostics, decisions


# --- announcement_summary ------------------------------------------------------------------


def test_summary_separates_news_from_fit_error(three_afternoons):
    snapshots, diagnostics, decisions = three_afternoons
    summary = announcement_summary(snapshots, diagnostics, decisions).set_index("label")

    assert summary.loc["news", "surprise"] == pytest.approx(-13.0)        # -50 - (-37)
    assert summary.loc["news", "repricing"] == pytest.approx(-11.0)       # -48 - (-37)
    assert summary.loc["news", "closing_error"] == pytest.approx(2.0)     # -48 - (-50)

    # The fit says +4.5 bp of news, but the Fed delivered what was priced.
    assert summary.loc["artifact", "surprise"] == pytest.approx(-0.3)
    assert summary.loc["artifact", "repricing"] == pytest.approx(4.5)
    assert summary.loc["artifact", "closing_error"] == pytest.approx(4.8)


def test_flags_say_why_a_day_is_not_usable(three_afternoons):
    snapshots, diagnostics, decisions = three_afternoons
    summary = announcement_summary(snapshots, diagnostics, decisions, tolerance_bps=TOLERANCE_BPS).set_index("label")

    assert summary.loc["news", "flag"] == ""                                # error of exactly 2.0 is inside
    assert "closing error above 2 bp" in summary.loc["artifact", "flag"]
    assert summary.loc["rank_short", "flag"] == "not fully identified"
    assert not summary.loc["rank_short", "identified"]


def test_both_reasons_are_reported_together():
    snapshots = _snapshots([("both", "2024-06-12", 0.0, 6.0)])
    summary = announcement_summary(snapshots, _diagnostics({"both": False}), _decisions({"2024-06-12": 0.0}))
    assert summary["flag"].iloc[0] == "not fully identified; closing error above 2 bp"


def test_a_day_with_no_diagnostics_is_treated_as_not_identified():
    snapshots = _snapshots([("lonely", "2024-06-12", 0.0, 0.0)])
    empty = pd.DataFrame({"label": [], "snapshot": [], "fully_identified": []})
    summary = announcement_summary(snapshots, empty, _decisions({"2024-06-12": 0.0}))
    assert not summary["identified"].iloc[0]


def test_summary_is_in_date_order(three_afternoons):
    summary = announcement_summary(*three_afternoons)
    assert list(summary["label"]) == ["rank_short", "news", "artifact"]


def test_a_missing_announced_decision_is_an_error(three_afternoons):
    snapshots, diagnostics, _ = three_afternoons
    with pytest.raises(ValueError, match="no announced decision for 2025-10-29"):
        announcement_summary(snapshots, diagnostics, _decisions({"2024-09-18": -50.0, "2022-03-16": 25.0}))


def test_a_missing_snapshot_is_an_error():
    only_pre = _snapshots([("x", "2024-06-12", 0.0, 0.0)])
    only_pre = only_pre.loc[only_pre["snapshot"] == "pre_1355"]
    with pytest.raises(ValueError, match="post_1600"):
        announcement_summary(only_pre, _diagnostics({"x": True}), _decisions({"2024-06-12": 0.0}))


def test_noise_floor_is_the_mean_absolute_closing_error(three_afternoons):
    summary = announcement_summary(*three_afternoons)
    assert noise_floor(summary) == pytest.approx(np.mean([2.0, 4.8, 1.5]))


# --- headline events -----------------------------------------------------------------------


def test_headline_events_are_ranked_by_true_surprise_and_skip_flagged_days(three_afternoons):
    summary = announcement_summary(*three_afternoons)
    # "artifact" has the largest fitted move among identified days, and "rank_short" is large too,
    # but neither is usable. Only "news" qualifies.
    assert select_headline_events(summary, n=3) == ["news"]


def test_headline_events_prefer_the_larger_surprise_in_either_direction():
    snapshots = _snapshots([
        ("small_up", "2023-02-01", 20.0, 24.5),
        ("big_down", "2024-09-18", -37.0, -49.0),
        ("mid_up", "2022-06-15", 70.0, 74.5),
    ])
    decisions = _decisions({"2023-02-01": 25.0, "2024-09-18": -50.0, "2022-06-15": 75.0})
    diagnostics = _diagnostics({"small_up": True, "big_down": True, "mid_up": True})
    summary = announcement_summary(snapshots, diagnostics, decisions)
    assert select_headline_events(summary, n=2) == ["big_down", "mid_up"]


def test_ranking_follows_the_surprise_even_when_the_fitted_change_orders_them_differently():
    """Both afternoons are usable. Ranked by fitted change B would lead; by true surprise A does."""
    snapshots = _snapshots([
        ("A", "2023-02-01", 0.0, 8.5),    # announced 10: surprise 10, fitted repricing 8.5, closing error -1.5
        ("B", "2024-09-18", 0.0, 10.4),   # announced 9: surprise 9, fitted repricing 10.4, closing error +1.4
    ])
    decisions = _decisions({"2023-02-01": 10.0, "2024-09-18": 9.0})
    summary = announcement_summary(snapshots, _diagnostics({"A": True, "B": True}), decisions)
    assert (summary["flag"] == "").all()
    assert select_headline_events(summary, n=2) == ["A", "B"]


def test_a_fit_that_undershoots_the_announced_move_is_flagged_too():
    """The tolerance applies in both directions: -5 bp of closing error is as bad as +5."""
    snapshots = _snapshots([("under", "2024-06-12", -10.0, -30.0)])   # announced -25, fit says -30
    summary = announcement_summary(snapshots, _diagnostics({"under": True}), _decisions({"2024-06-12": -25.0}))
    assert summary["closing_error"].iloc[0] == pytest.approx(-5.0)
    assert "closing error above 2 bp" in summary["flag"].iloc[0]


def test_no_usable_afternoon_gives_no_headline_events():
    snapshots = _snapshots([("x", "2024-06-12", 0.0, 0.0)])
    summary = announcement_summary(snapshots, _diagnostics({"x": False}), _decisions({"2024-06-12": 0.0}))
    assert select_headline_events(summary) == []


# --- horizon summary -----------------------------------------------------------------------


def test_horizon_summary_counts_and_sizes():
    frame = pd.DataFrame({
        "snapshot": "post_1600",
        "horizon": [1, 1, 1, 2, 2, 7],
        "delta_cum_bps": [-10.0, 2.0, 4.0, 6.0, -6.0, 99.0],
    })
    table = horizon_summary(frame, max_horizon=6)
    assert list(table.index) == [1, 2]                 # horizon 7 is beyond max_horizon
    assert table.loc[1, "n_events"] == 3
    assert table.loc[1, "mean_bps"] == pytest.approx(-4 / 3)
    assert table.loc[1, "mean_abs_bps"] == pytest.approx(16 / 3)
    assert table.loc[1, "median_abs_bps"] == pytest.approx(4.0)
    assert table.loc[1, "max_abs_bps"] == pytest.approx(10.0)
    assert table.loc[2, "mean_abs_bps"] == pytest.approx(6.0)


# --- windows -------------------------------------------------------------------------------


def _minutes(label, horizon, levels):
    return pd.DataFrame({
        "label": label, "horizon": horizon,
        "minutes_from_statement": list(levels), "implied_cum_change_bps": list(levels.values()),
    })


def test_window_changes_use_the_study_minute_convention():
    levels = {-5: 0.0, 0: 1.0, 1: -9.0, 30: -9.0, 31: -13.0, 120: -12.0}
    changes = window_changes(_minutes("A", 1, levels)).set_index("window")["change_bps"]
    assert changes[WINDOW_NAMES[0]] == pytest.approx(1.0)      # drift 13:55 -> 14:00 (-5 -> 0)
    assert changes[WINDOW_NAMES[1]] == pytest.approx(-10.0)    # the statement minute (0 -> 1)
    assert changes[WINDOW_NAMES[2]] == pytest.approx(0.0)      # digesting (1 -> 30)
    assert changes[WINDOW_NAMES[3]] == pytest.approx(-4.0)     # the press conference minute (30 -> 31)
    assert changes[WINDOW_NAMES[4]] == pytest.approx(1.0)      # after the press conference (31 -> 120)


def test_a_missing_minute_leaves_only_its_windows_empty():
    levels = {-5: 0.0, 0: 0.0, 1: -5.0, 31: -8.0, 120: -8.0}   # no minute 30
    changes = window_changes(_minutes("A", 1, levels)).set_index("window")["change_bps"]
    assert np.isnan(changes[WINDOW_NAMES[2]])
    assert np.isnan(changes[WINDOW_NAMES[3]])
    assert changes[WINDOW_NAMES[1]] == pytest.approx(-5.0)
    assert changes[WINDOW_NAMES[4]] == pytest.approx(0.0)


def test_window_summary_uses_absolute_values_and_clock_order():
    up = _minutes("up", 1, {-5: 0.0, 0: 0.0, 1: 10.0, 30: 10.0, 31: 10.0, 120: 10.0})
    down = _minutes("down", 1, {-5: 0.0, 0: 0.0, 1: -10.0, 30: -10.0, 31: -10.0, 120: -10.0})
    table = window_summary(window_changes(pd.concat([up, down])))
    statement = table.loc[table["window"] == WINDOW_NAMES[1]].iloc[0]
    assert statement["mean_abs_bps"] == pytest.approx(10.0)    # +10 and -10 are not averaged to zero
    assert statement["n_events"] == 2
    assert list(table["window"]) == list(WINDOW_NAMES)


def test_window_summary_ignores_empty_windows():
    full = _minutes("full", 1, {-5: 0.0, 0: 0.0, 1: -4.0, 30: -4.0, 31: -4.0, 120: -4.0})
    gap = _minutes("gap", 1, {-5: 0.0, 0: 0.0, 1: -8.0, 31: -8.0, 120: -8.0})  # no minute 30
    table = window_summary(window_changes(pd.concat([full, gap])))
    press = table.loc[table["window"] == WINDOW_NAMES[3]].iloc[0]
    assert press["n_events"] == 1                               # the afternoon with a gap is left out
    assert press["mean_abs_bps"] == pytest.approx(0.0)


# --- the synthetic drill: planted answer known exactly -------------------------------------


@pytest.fixture(scope="module")
def drill():
    import scripts.run_intraday_demo as runner

    snapshots, minutes, diagnostics, truths = runner.run_synthetic()
    moves = {}
    for truth in truths:
        day = pd.Timestamp(truth["announcement_date"])
        moves[day] = (truth["pre_moves_bps"].get(day, 0.0), truth["press_moves_bps"].get(day, 0.0))
    decisions = pd.DataFrame({"meeting_date": list(moves), "change_bps": [press for _, press in moves.values()]})
    return snapshots, minutes, diagnostics, decisions, moves


def test_the_closing_check_passes_on_the_drill(drill):
    snapshots, _minutes_unused, diagnostics, decisions, moves = drill
    summary = announcement_summary(snapshots, diagnostics, decisions)
    assert len(summary) == len(moves)
    assert (summary["closing_error"].abs() < 0.05).all()
    assert (summary["flag"] == "").all()


def test_the_drill_surprise_is_the_planted_one(drill):
    snapshots, _minutes_unused, diagnostics, decisions, moves = drill
    summary = announcement_summary(snapshots, diagnostics, decisions).set_index("announcement_date")
    for day, (pre, press) in moves.items():
        assert summary.loc[day, "surprise"] == pytest.approx(press - pre, abs=0.05)
        assert summary.loc[day, "repricing"] == pytest.approx(press - pre, abs=0.05)


def test_the_drill_statement_and_press_jumps_land_in_their_windows(drill):
    _snapshots_unused, minutes, _diagnostics_unused, _decisions_unused, _moves = drill
    table = window_summary(window_changes(minutes)).set_index(["horizon", "window"])
    # The scenarios plant jumps at 14:00 and 14:30 and nothing at other times, so the quiet
    # windows are quiet and the jump windows carry the repricing.
    for horizon in (1, 2, 3):
        assert table.loc[(horizon, WINDOW_NAMES[0]), "mean_abs_bps"] == pytest.approx(0.0, abs=0.05)
        assert table.loc[(horizon, WINDOW_NAMES[2]), "mean_abs_bps"] == pytest.approx(0.0, abs=0.05)
        assert table.loc[(horizon, WINDOW_NAMES[4]), "mean_abs_bps"] == pytest.approx(0.0, abs=0.05)
    assert table.loc[(1, WINDOW_NAMES[1]), "mean_abs_bps"] > 1.0


# --- figures and the writer ----------------------------------------------------------------


def test_surprise_check_labels_only_the_flagged_days(three_afternoons):
    summary = announcement_summary(*three_afternoons)
    fig = plot_surprise_check(summary)
    texts = {text.get_text() for text in fig.axes[0].texts}
    assert texts == {"artifact", "rank_short"}
    plt.close(fig)


def test_repricing_windows_chart_has_a_bar_group_per_horizon():
    frames = [_minutes("A", h, {-5: 0.0, 0: 0.0, 1: -5.0 * h, 30: -5.0 * h, 31: -6.0 * h, 120: -6.0 * h}) for h in (1, 2, 3)]
    table = window_summary(window_changes(pd.concat(frames)))
    fig = plot_repricing_windows(table)
    assert len(fig.axes) == 1
    assert len(fig.axes[0].patches) == 3 * len(WINDOW_NAMES)
    assert "1 announcements" in fig.axes[0].get_title()
    plt.close(fig)


def test_real_outputs_use_the_closing_check_and_write_the_sample_files(tmp_path, three_afternoons, monkeypatch):
    import scripts.run_intraday_demo as runner

    snapshots, diagnostics, decisions = three_afternoons
    levels = {-5: 0.0, 0: 0.0, 1: -3.0, 30: -3.0, 31: -4.0, 120: -4.0}
    minutes = pd.concat([_minutes(label, 1, levels) for label in ("news", "artifact", "rank_short")])
    plotted = []
    original = runner.plot_repricing_paths

    def record(rows, **kwargs):
        plotted.append(list(rows["label"].astype(str).unique()))
        return original(rows, **kwargs)

    monkeypatch.setattr(runner, "plot_repricing_paths", record)
    runner.write_outputs(tmp_path, snapshots, minutes, diagnostics, synthetic=False, decisions=decisions)

    # Ranked by the fitted change alone, "artifact" would lead the path chart. It is flagged, so it does not.
    assert plotted == [["news"]]
    for name in ("announcement_summary.csv", "horizon_summary.csv", "repricing_windows.csv",
                 "repricing_window_summary.csv", "surprise_check.png", "repricing_speed.png",
                 "change_by_horizon.png", "repricing_paths.png"):
        assert (tmp_path / name).exists(), name
    saved = pd.read_csv(tmp_path / "announcement_summary.csv")
    assert list(saved.loc[saved["flag"].notna(), "label"]) == ["rank_short", "artifact"]


def test_synthetic_outputs_do_not_claim_a_closing_check(tmp_path, three_afternoons):
    import scripts.run_intraday_demo as runner

    snapshots, diagnostics, decisions = three_afternoons
    minutes = _minutes("news", 1, {-5: 0.0, 0: 0.0, 1: -3.0, 30: -3.0, 31: -4.0, 120: -4.0})
    runner.write_outputs(tmp_path, snapshots, minutes, diagnostics, synthetic=True, decisions=decisions)
    assert not (tmp_path / "announcement_summary.csv").exists()
    assert not (tmp_path / "surprise_check.png").exists()
