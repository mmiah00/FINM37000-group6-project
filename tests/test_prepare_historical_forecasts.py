"""Tests for the historical forecast preparation used by Issue #7.

The prices are synthetic. They check that the scored cumulative changes follow
the basis from estimate_basis, and that a horizon near the end of the meeting
file is not reported as if every date still had six meetings ahead.
"""

import pandas as pd
import pytest

from sofr_pricing import contract_strip, fit_many
from sofr_pricing.synthetic import (
    make_synthetic_decisions,
    make_synthetic_market,
    make_synthetic_realized_sofr,
)
from scripts.prepare_historical_forecasts import (
    prepare_historical_forecasts,
    trailing_basis,
)
from scripts.prepare_visualization_inputs import build_visualization_inputs


OBS = pd.Timestamp("2024-06-03")
TRUE_BASIS = -0.06
MEETINGS = [
    "2024-01-31", "2024-03-20", "2024-05-01",
    "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30",
    "2025-09-17", "2025-10-29", "2025-12-10",
]
# Moves the synthetic market prices in. The June 12 meeting is the first one
# after the observation date, so its cumulative change is just this move.
EXPECTED_BPS = {
    "2024-06-12": -2.0,
    "2024-07-31": -6.0,
    "2024-09-18": -18.0,
    "2024-11-07": -12.0,
    "2024-12-18": -10.0,
    "2025-01-29": -8.0,
    "2025-03-19": -7.0,
}


def _decisions():
    changes = [EXPECTED_BPS.get(day, 0.0) for day in MEETINGS]
    return make_synthetic_decisions(MEETINGS, changes)


def test_trailing_basis_ignores_the_observation_date_itself():
    """A fixing dated on the observation date is not published yet."""
    decisions = _decisions()
    fixings = make_synthetic_realized_sofr("2024-04-01", "2024-06-03", decisions, basis=TRUE_BASIS)
    fixings.loc[OBS] = 50.0

    basis = trailing_basis(fixings, decisions, OBS)

    assert basis == pytest.approx(TRUE_BASIS)


def test_prepare_historical_forecasts_passes_the_estimated_basis(tmp_path):
    """Cumulative changes follow the estimated basis, not fit_many's default of 0."""
    decisions = _decisions()
    anchor = 5.375
    fixings = make_synthetic_realized_sofr("2023-12-01", "2024-06-03", decisions, basis=TRUE_BASIS)
    fixings.loc[OBS] = 50.0
    prices = make_synthetic_market(
        OBS, contract_strip(OBS), EXPECTED_BPS, anchor, TRUE_BASIS,
    )
    panel = prices.assign(trade_date=OBS)

    futures_path = tmp_path / "sofr_futures_settlements.parquet"
    sofr_path = tmp_path / "sofr_daily.csv"
    decisions_path = tmp_path / "fomc_meetings.csv"
    output_dir = tmp_path / "visualizations"
    panel.to_parquet(futures_path, index=False)
    fixings.rename("sofr").rename_axis("date").reset_index().to_csv(sofr_path, index=False)
    decisions.to_csv(decisions_path, index=False)

    implied, _diagnostics, basis = prepare_historical_forecasts(
        futures_path, sofr_path, decisions_path, output_dir,
        start_date="2024-06-01", months_ahead=12,
    )

    assert basis.loc[0, "basis"] == pytest.approx(TRUE_BASIS)
    first = implied.sort_values("meeting_date").iloc[0]
    assert first["meeting_date"] == pd.Timestamp("2024-06-12")
    assert first["implied_cum_change_bps"] == pytest.approx(-2.0, abs=1e-2)

    at_zero, _zero_diag = fit_many(
        panel, [OBS], decisions, meeting_dates=MEETINGS, basis=0.0,
        realized_fixings=fixings, months_ahead=12,
    )
    zero_first = at_zero.sort_values("meeting_date").iloc[0]["implied_cum_change_bps"]
    # A 6 bp basis error is absorbed into the near-meeting cumulative change.
    assert abs(zero_first - first["implied_cum_change_bps"]) > 5.0


def test_horizon_counts_stop_at_the_end_of_the_meeting_file():
    """A date with only two meetings left does not produce six horizon rows."""
    implied = pd.DataFrame({
        "obs_date": [pd.Timestamp("2024-06-03")] * 2,
        "meeting_date": [pd.Timestamp("2024-06-12"), pd.Timestamp("2024-07-31")],
        "implied_cum_change_bps": [-2.0, -8.0],
    })
    decisions = pd.DataFrame({
        "meeting_date": [pd.Timestamp("2024-06-12"), pd.Timestamp("2024-07-31")],
        "change_bps": [-25.0, 0.0],
    })

    errors, by_horizon = build_visualization_inputs(implied, decisions)

    assert list(by_horizon.index) == [1, 2]
    assert by_horizon["n_obs"].tolist() == [1, 1]
    assert by_horizon.loc[1, "n_meetings"] == 1
    assert len(errors) == 2
