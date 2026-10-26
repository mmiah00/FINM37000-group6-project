"""Tests for the intraday FOMC event study (Issue #8).

Everything here is local. Synthetic minute bars are priced with the same
pricer the fit uses, so a noiseless fit should recover the moves that
were put in. No test opens a socket.

Run from the repository root:  python -m pytest tests/test_intraday.py -v
"""

import socket

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from fomc_intraday.events import (
    calendar_meeting_dates,
    covered_announcements,
    estimator_meeting_dates,
    estimator_obs_date,
)
from fomc_intraday.fetch import (
    CostCapExceeded,
    build_requests,
    enforce_cost_cap,
    pull,
    quote_cost,
    request_kwargs,
)
from fomc_intraday.plots import plot_change_by_horizon, plot_repricing_paths
from fomc_intraday.snapshots import select_snapshot
from fomc_intraday.study import fit_announcement, market_anchor, run_event_study
from sofr_pricing import FitResult
from fomc_intraday.synthetic import DEMO_SCENARIOS, make_synthetic_minutes
from fomc_intraday.windows import announcement_window, to_utc
from scripts.fetch_intraday_sofr import parse_args as parse_fetch_args
from scripts.run_intraday_demo import write_outputs
from sofr_pricing.synthetic import make_synthetic_decisions, make_synthetic_realized_sofr

# Far enough from a 1 bp move that a wrong regime fails, and wide enough
# for the small ridge the estimator uses on a long strip.
TOLERANCE_BPS = 0.05


def _blocked(*_args, **_kwargs):
    raise AssertionError("intraday tests must not use the network")


_blocked._intraday_block = True


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail the test if anything tries to open a connection."""
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def test_network_guard_is_installed():
    assert getattr(socket.socket.connect, "_intraday_block", False)
    assert getattr(socket.create_connection, "_intraday_block", False)


# ---------------------------------------------------------------------------
# Clock and daylight saving
# ---------------------------------------------------------------------------


def test_summer_and_winter_statements_have_different_utc_offsets():
    june = announcement_window("2024-06-12")
    december = announcement_window("2024-12-18")

    # 14:00 EDT is 18:00 UTC. 14:00 EST is 19:00 UTC.
    assert to_utc(june["statement"]) == pd.Timestamp("2024-06-12 18:00", tz="UTC")
    assert to_utc(december["statement"]) == pd.Timestamp("2024-12-18 19:00", tz="UTC")
    assert june["statement"].utcoffset() == pd.Timedelta(hours=-4)
    assert december["statement"].utcoffset() == pd.Timedelta(hours=-5)

    # Default window: 13:00 to 16:00 Eastern, pre snapshot 13:55.
    assert to_utc(june["window_start"]) == pd.Timestamp("2024-06-12 17:00", tz="UTC")
    assert to_utc(june["window_end"]) == pd.Timestamp("2024-06-12 20:00", tz="UTC")
    assert to_utc(june["pre_snapshot"]) == pd.Timestamp("2024-06-12 17:55", tz="UTC")
    assert to_utc(december["window_start"]) == pd.Timestamp("2024-12-18 18:00", tz="UTC")
    assert to_utc(december["window_end"]) == pd.Timestamp("2024-12-18 21:00", tz="UTC")
    assert to_utc(december["pre_snapshot"]) == pd.Timestamp("2024-12-18 18:55", tz="UTC")
    assert [stamp.strftime("%H:%M") for stamp in june["post_snapshots"]] == ["14:15", "14:45", "16:00"]


def test_request_bounds_follow_the_window_across_dst():
    requests = {req["announcement_date"]: req for req in build_requests(["2024-06-12", "2024-12-18"])}
    june = requests["2024-06-12"]
    december = requests["2024-12-18"]

    # One minute before 13:00 Eastern, through 16:00 Eastern exclusive.
    assert june["start"] == pd.Timestamp("2024-06-12 16:59", tz="UTC").to_pydatetime()
    assert june["end"] == pd.Timestamp("2024-06-12 20:00", tz="UTC").to_pydatetime()
    assert december["start"] == pd.Timestamp("2024-12-18 17:59", tz="UTC").to_pydatetime()
    assert december["end"] == pd.Timestamp("2024-12-18 21:00", tz="UTC").to_pydatetime()

    assert june["schema"] == "ohlcv-1m"
    assert june["dataset"] == "GLBX.MDP3"
    assert june["stype_in"] == "raw_symbol"
    assert "SR1M4" in june["symbols"]  # June 2024 one-month
    assert "SR3M4" in june["symbols"]
    assert "SR1Z4" in december["symbols"]  # December 2024
    assert "SR3Z4" in december["symbols"]
    assert request_kwargs(june)["symbols"] == june["symbols"]
    assert len(june["symbols"]) == 11
    assert len(december["symbols"]) == 11


@pytest.mark.parametrize("option", ["--minutes-before", "--minutes-after", "--n-sr1", "--n-sr3"])
def test_fetch_cli_rejects_alternate_window_and_strip(option):
    with pytest.raises(SystemExit) as error:
        parse_fetch_args([option, "1"])
    assert error.value.code == 2


def test_today_stays_in_the_unknown_list():
    # Midnight observation date, announcement stamped at 14:00, so the
    # daily estimator does not treat the statement as already known.
    obs = estimator_obs_date("2024-06-12")
    schedule = estimator_meeting_dates("2024-06-12", ["2024-05-01", "2024-06-12", "2024-07-31"])
    assert obs == pd.Timestamp("2024-06-12")
    assert pd.Timestamp("2024-06-12 14:00") in schedule
    assert all(meeting > obs or meeting.normalize() < obs for meeting in schedule)


# ---------------------------------------------------------------------------
# Snapshots and carry-forward
# ---------------------------------------------------------------------------


def _bars(rows):
    frame = pd.DataFrame(rows)
    return frame


def _row(contract_id, ts_utc, close, volume=1, root="SR1"):
    return {
        "contract_id": contract_id,
        "root": root,
        "reference_start": pd.Timestamp("2024-12-01"),
        "reference_end": pd.Timestamp("2024-12-31"),
        "ts_utc": pd.Timestamp(ts_utc),
        "close": close,
        "volume": volume,
    }


def test_winter_snapshot_is_not_read_as_summer_time():
    # 13:54 EST is 18:54 UTC. 13:54 EDT would be 17:54 UTC. A snapshot at
    # 13:55 Eastern on a December meeting must take 18:54 (close 96) and
    # must not take the 17:54 decoy (close 10) or the 18:55 bar, which
    # starts at 13:55 and ends at 13:56.
    pre = announcement_window("2024-12-18")["pre_snapshot"]
    bars = _bars([
        _row("SR1-2024-12", "2024-12-18 17:54", 10.0),
        _row("SR1-2024-12", "2024-12-18 18:54", 96.0),
        _row("SR1-2024-12", "2024-12-18 18:55", 97.0),
    ])
    snapshot = select_snapshot(bars, pre)
    assert list(snapshot["close"]) == [96.0]


def test_summer_snapshot_is_not_read_as_winter_time():
    # 13:54 EDT is 17:54 UTC. An EST reading of 13:55 would wait until
    # 18:55 UTC and pick the decoy at 18:54 (close 10).
    pre = announcement_window("2024-06-12")["pre_snapshot"]
    bars = _bars([
        _row("SR1-2024-06", "2024-06-12 17:54", 96.0),
        _row("SR1-2024-06", "2024-06-12 18:54", 10.0),
    ])
    snapshot = select_snapshot(bars, pre)
    assert list(snapshot["close"]) == [96.0]


def test_carry_forward_and_zero_volume():
    # Last trade at 13:40 is 94. A later zero-volume bar is not a trade.
    # A contract that has not traded yet is absent. A trade after the
    # snapshot is not used.
    pre = announcement_window("2024-12-18")["pre_snapshot"]
    bars = _bars([
        _row("SR1-2024-12", "2024-12-18 18:40", 94.0),
        _row("SR1-2024-12", "2024-12-18 18:50", 91.0, volume=0),
        _row("SR3-2024-12", "2024-12-18 19:10", 93.0, root="SR3"),
    ])
    snapshot = select_snapshot(bars, pre)
    assert list(snapshot["contract_id"]) == ["SR1-2024-12"]
    assert list(snapshot["close"]) == [94.0]

    later = announcement_window("2024-12-18")["post_snapshots"][0]  # 14:15 EST
    carried = select_snapshot(bars, later)
    prices = dict(zip(carried["contract_id"], carried["close"]))
    assert prices["SR1-2024-12"] == 94.0  # still the 13:40 trade
    assert prices["SR3-2024-12"] == 93.0  # first trade is before 14:15


def test_pre_snapshot_misses_a_trade_that_starts_after_the_statement():
    # SR3 trades only at 14:10. The study must leave it out of every fit,
    # including 14:15, so the contract set does not change at 14:00.
    day = "2024-06-12"
    window = announcement_window(day)
    bars = _bars([
        _row("SR1-2024-06", "2024-06-12 17:40", 95.0),
        _row("SR3-2024-06", "2024-06-12 18:10", 96.0, root="SR3"),
    ])
    # Hand-built bars are not a full strip, so this checks the universe
    # through select_snapshot only: 13:55 sees SR1, 14:15 sees both.
    pre = select_snapshot(bars, window["pre_snapshot"])
    post = select_snapshot(bars, window["post_snapshots"][0])
    assert list(pre["contract_id"]) == ["SR1-2024-06"]
    assert set(post["contract_id"]) == {"SR1-2024-06", "SR3-2024-06"}


def test_a_contract_that_first_trades_after_the_statement_is_left_out_of_every_fit(monkeypatch):
    """The contract set is fixed at 13:55 so a later first print cannot change it."""
    captured = []

    def fake_fit(obs_date, contracts, meeting_dates, anchor, **kwargs):
        captured.append(list(contracts["contract_id"]))
        meetings = pd.DataFrame({
            "meeting_date": [pd.Timestamp("2024-06-12 14:00")],
            "effective_date": [pd.Timestamp("2024-06-13")],
            "implied_move_bps": [-25.0],
            "implied_cum_change_bps": [-25.0],
            "sensitivity": [1.0],
        })
        diagnostics = {
            "n_contracts": len(contracts),
            "n_meetings": 1,
            "rmse_bps": 0.0,
            "max_abs_residual_bps": 0.0,
            "jacobian_rank": 1,
            "fully_identified": True,
            "condition_number": 1.0,
            "iterations": 1,
            "converged": True,
            "used_realized_fixings": False,
        }
        return FitResult(pd.Timestamp(obs_date), meetings, contracts, diagnostics)

    monkeypatch.setattr("fomc_intraday.study.fit_meeting_moves", fake_fit)
    bars = _bars([
        _row("SR1-2024-06", "2024-06-12 17:40", 95.0),
        _row("SR3-2024-06", "2024-06-12 18:10", 96.0, root="SR3"),
    ])
    run_event_study(bars, "2024-06-12", ["2024-05-01", "2024-06-12", "2024-07-31"], anchor=5.375)
    assert captured
    assert all(contract_ids == ["SR1-2024-06"] for contract_ids in captured)


# ---------------------------------------------------------------------------
# Synthetic recovery
# ---------------------------------------------------------------------------


def _assert_regime(study, truth, snapshot_name, regime):
    rows = study.snapshots.loc[study.snapshots["snapshot"] == snapshot_name]
    expected = truth[regime]
    assert not rows.empty
    for row in rows.itertuples(index=False):
        target = expected.get(pd.Timestamp(row.meeting_date), 0.0)
        assert row.implied_move_bps == pytest.approx(target, abs=TOLERANCE_BPS), (
            f"{snapshot_name} {row.meeting_date.date()} got {row.implied_move_bps}, expected {target}"
        )
    horizon_one = rows.loc[rows["horizon"] == 1, "meeting_date"].iloc[0]
    assert pd.Timestamp(horizon_one) == truth["announcement_date"]


def test_synthetic_jump_is_recovered_in_summer_and_winter():
    meeting_dates = calendar_meeting_dates()
    # June is a single jump at the statement (press book equals the statement).
    # December is the demo's winter scenario, also a single jump.
    scenarios = [
        {
            "announcement_date": "2024-06-12",
            "label": "June single jump",
            "anchor": 5.375,
            "pre_moves_bps": {"2024-06-12": -5.0, "2024-07-31": -10.0, "2024-09-18": -15.0},
            "statement_moves_bps": {"2024-06-12": -25.0, "2024-07-31": -10.0, "2024-09-18": -20.0},
            "press_moves_bps": None,
        },
        DEMO_SCENARIOS[1],
    ]
    for scenario in scenarios:
        bars, truth = make_synthetic_minutes(
            scenario["announcement_date"],
            scenario["pre_moves_bps"],
            scenario["statement_moves_bps"],
            press_moves_bps=scenario["press_moves_bps"],
            anchor=scenario["anchor"],
            label=scenario["label"],
        )
        study = run_event_study(
            bars,
            truth["announcement_date"],
            meeting_dates,
            anchor=truth["anchor"],
            basis=truth["basis"],
            label=truth["label"],
        )
        rank = study.diagnostics[
            ["snapshot", "n_contracts", "n_meetings", "jacobian_rank", "fully_identified", "condition_number"]
        ]
        assert study.diagnostics["fully_identified"].all(), rank.to_string()
        assert study.diagnostics["converged"].all()
        _assert_regime(study, truth, "pre_1355", "pre_moves_bps")
        _assert_regime(study, truth, "post_1415", "statement_moves_bps")
        _assert_regime(study, truth, "post_1600", "press_moves_bps")

        pre = study.snapshots.loc[study.snapshots["snapshot"] == "pre_1355"].set_index("horizon")
        post = study.snapshots.loc[study.snapshots["snapshot"] == "post_1600"].set_index("horizon")
        gap = post.loc[1, "implied_cum_change_bps"] - pre.loc[1, "implied_cum_change_bps"]
        assert post.loc[1, "delta_cum_bps"] == pytest.approx(gap)


def test_press_conference_jump_lands_at_1445_and_on_the_minute_path():
    scenario = DEMO_SCENARIOS[0]  # September, two steps
    meeting_dates = calendar_meeting_dates()
    bars, truth = make_synthetic_minutes(
        scenario["announcement_date"],
        scenario["pre_moves_bps"],
        scenario["statement_moves_bps"],
        press_moves_bps=scenario["press_moves_bps"],
        anchor=scenario["anchor"],
        label=scenario["label"],
    )
    study = run_event_study(
        bars, truth["announcement_date"], meeting_dates,
        anchor=truth["anchor"], basis=0.0, label=scenario["label"],
    )
    _assert_regime(study, truth, "pre_1355", "pre_moves_bps")
    _assert_regime(study, truth, "post_1415", "statement_moves_bps")
    _assert_regime(study, truth, "post_1445", "press_moves_bps")
    _assert_regime(study, truth, "post_1600", "press_moves_bps")

    path = study.minutes.loc[study.minutes["horizon"] == 1].sort_values("minutes_from_statement")
    # The 14:00 bar is the first post-statement trade, so minute 0 (the
    # clock of the statement) is still the pre book. Minute 1 is the
    # statement book. Minute 31 is the first post-press-conference book.
    before = path.loc[path["minutes_from_statement"] <= 0, "implied_move_bps"]
    between = path.loc[path["minutes_from_statement"].between(1, 30), "implied_move_bps"]
    after = path.loc[path["minutes_from_statement"] >= 31, "implied_move_bps"]
    assert before.nunique() == 1
    assert between.nunique() == 1
    assert after.nunique() == 1
    assert before.iloc[0] == pytest.approx(-25.0, abs=TOLERANCE_BPS)
    assert between.iloc[0] == pytest.approx(-40.0, abs=TOLERANCE_BPS)
    assert after.iloc[0] == pytest.approx(-50.0, abs=TOLERANCE_BPS)


def test_anchor_uses_the_pre_announcement_policy_rate_and_sofr_basis():
    decisions = make_synthetic_decisions(
        ["2024-07-31", "2024-09-18"], [-25, -50], start_lower=5.50, start_upper=5.75,
    )
    sofr = make_synthetic_realized_sofr("2024-07-01", "2024-09-30", decisions, basis=-0.06)
    anchor, basis = market_anchor("2024-09-18", decisions, sofr)
    # Midpoint before the July cut is 5.625. After it, and still on the
    # morning of September 18, the midpoint is 5.375. The September cut
    # is not in the anchor.
    assert anchor == pytest.approx(5.375)
    assert basis == pytest.approx(-0.06)
    no_sofr_anchor, no_sofr_basis = market_anchor("2024-09-18", decisions, sofr=None)
    assert no_sofr_anchor == pytest.approx(5.375)
    assert no_sofr_basis == 0.0


# ---------------------------------------------------------------------------
# Cost cap, coverage, figures
# ---------------------------------------------------------------------------


class _Meta:
    def __init__(self, cost, calls):
        self._cost = cost
        self._calls = calls

    def get_cost(self, **kwargs):
        self._calls.append(kwargs)
        return self._cost


class _Timeseries:
    def __init__(self):
        self.calls = []

    def get_range(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("download ran")


class _Client:
    def __init__(self, cost):
        self.calls = []
        self.metadata = _Meta(cost, self.calls)
        self.timeseries = _Timeseries()


def test_cost_cap_blocks_the_download(tmp_path):
    requests = build_requests(["2024-06-12", "2024-12-18"])
    client = _Client(cost=3.0)
    with pytest.raises(CostCapExceeded) as caught:
        pull(client, requests, max_cost=5.0, raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed")
    assert caught.value.total == pytest.approx(6.0)
    assert client.timeseries.calls == []
    assert len(client.calls) == 2
    assert client.calls[0]["schema"] == "ohlcv-1m"
    assert client.calls[0]["dataset"] == "GLBX.MDP3"


def test_quote_under_the_cap_can_download_without_a_second_price(tmp_path):
    # One announcement, quote under the cap. The fake store returns no
    # rows; the test checks that get_range sees the same kwargs as get_cost.
    requests = build_requests(["2024-06-12"])

    class Store:
        def to_df(self):
            return pd.DataFrame()

    class Timeseries:
        def __init__(self):
            self.calls = []

        def get_range(self, **kwargs):
            self.calls.append(kwargs)
            return Store()

    client = _Client(cost=0.25)
    client.timeseries = Timeseries()
    quote = quote_cost(client, requests)
    assert enforce_cost_cap(quote, 5.0) == pytest.approx(0.25)
    bars, quoted, total = pull(
        client, requests, max_cost=5.0, raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed",
    )
    assert total == pytest.approx(0.25)
    assert client.timeseries.calls == [request_kwargs(requests[0])]
    assert bars is not None
    assert (tmp_path / "raw" / "2024-06-12.parquet").exists()


def test_covered_announcements_drop_the_tail_of_the_calendar():
    dates = calendar_meeting_dates()
    covered = covered_announcements(dates)
    covered_set = set(covered)
    assert covered
    assert covered_set <= set(dates)
    assert pd.Timestamp("2024-06-12") in covered_set
    assert pd.Timestamp("2024-12-18") in covered_set
    # The calendar ends in September 2026, before a full SR3 strip from
    # that meeting would finish.
    assert pd.Timestamp("2026-09-16") not in covered_set
    assert covered[-1] < dates[-1]


def test_plots_return_one_panel_per_announcement_and_a_horizon_chart():
    minutes = pd.DataFrame({
        "label": ["A", "A", "B", "B"],
        "horizon": [1, 1, 1, 1],
        "minutes_from_statement": [-10, 10, -10, 10],
        "implied_cum_change_bps": [-25.0, -50.0, 0.0, -10.0],
    })
    snapshots = pd.DataFrame({
        "label": ["A", "B"],
        "snapshot": ["post_1600", "post_1600"],
        "horizon": [1, 1],
        "delta_cum_bps": [-25.0, -10.0],
    })
    paths = plot_repricing_paths(minutes, synthetic=True)
    changes = plot_change_by_horizon(snapshots, synthetic=True)
    assert len(paths.axes) == 2
    assert "Synthetic check" in paths._suptitle.get_text()
    assert len(changes.axes) == 1
    plt.close(paths)
    plt.close(changes)


def test_real_outputs_skip_unidentified_path_chart(tmp_path, capsys, monkeypatch):
    snapshots = pd.DataFrame({
        "announcement_date": pd.to_datetime(["2024-06-12", "2024-12-18"]),
        "label": ["identified", "unidentified"],
        "snapshot": ["post_1600", "post_1600"],
        "horizon": [1, 1],
        "delta_cum_bps": [-5.0, -10.0],
    })
    minutes = pd.DataFrame({
        "label": ["identified", "identified", "unidentified", "unidentified"],
        "horizon": [1, 1, 1, 1],
        "minutes_from_statement": [-10, 10, -10, 10],
        "implied_cum_change_bps": [0.0, -5.0, 0.0, -10.0],
    })
    diagnostics = pd.DataFrame({
        "label": ["identified", "unidentified"],
        "snapshot": ["post_1600", "post_1600"],
        "fully_identified": [True, False],
    })
    import scripts.run_intraday_demo as runner

    plotted = []
    original_plot = runner.plot_repricing_paths

    def record_plot(rows, **kwargs):
        plotted.append(set(rows["label"].astype(str)))
        return original_plot(rows, **kwargs)

    monkeypatch.setattr(runner, "plot_repricing_paths", record_plot)
    write_outputs(tmp_path, snapshots, minutes, diagnostics, synthetic=False)
    assert plotted == [{"identified"}]
    assert (tmp_path / "repricing_paths.png").exists()

    write_outputs(
        tmp_path,
        snapshots.loc[snapshots["label"] == "unidentified"],
        minutes.loc[minutes["label"] == "unidentified"],
        diagnostics.loc[diagnostics["label"] == "unidentified"],
        synthetic=False,
    )
    assert plotted == [{"identified"}]
    assert not (tmp_path / "repricing_paths.png").exists()
    assert (tmp_path / "change_by_horizon.png").exists()
    assert set(pd.read_csv(tmp_path / "minute_paths.csv")["label"]) == {"unidentified"}
    assert "Skipped repricing_paths.png: no fully identified afternoon at 16:00." in capsys.readouterr().out


def test_published_sofr_that_starts_inside_the_front_month_is_left_unspliced():
    """The January 2022 file starts after that SR1 month. The fit still runs.

    Splicing a series that begins after the contract's first day makes the
    pricer refuse the strip. The announcement is fit again with no splice,
    and the planted jump still comes back.
    """
    bars, _truth = make_synthetic_minutes(
        "2024-06-12",
        {"2024-06-12": -5.0, "2024-07-31": -10.0, "2024-09-18": -15.0},
        {"2024-06-12": -25.0, "2024-07-31": -10.0, "2024-09-18": -20.0},
        anchor=5.33,
    )
    # Inside the June SR1 month, and before the 12 June announcement, so
    # the splice has rows but they start after 1 June.
    late = pd.Series(
        [5.33, 5.33],
        index=pd.to_datetime(["2024-06-10", "2024-06-11"]),
    )
    study = fit_announcement(
        bars,
        "2024-06-12",
        calendar_meeting_dates(),
        anchor=5.33,
        basis=0.0,
        realized_fixings=late,
    )
    assert not bool(study.diagnostics["used_realized_fixings"].any())
    post = study.snapshots.loc[study.snapshots["snapshot"] == "post_1415"]
    front = post.loc[post["horizon"] == 1].iloc[0]
    assert abs(float(front["implied_move_bps"]) - (-25.0)) < 0.05
