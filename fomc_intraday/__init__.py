"""Intraday FOMC announcement study (Issue #8).

How the implied SR1/SR3 meeting path changes in the minutes around the
14:00 US Eastern statement. See INTRADAY.md for the question, the data,
and how to run the synthetic check or a real Databento pull.
"""

from fomc_intraday.events import (
    DEFAULT_N_SR1,
    DEFAULT_N_SR3,
    calendar_meeting_dates,
    contracts_for,
    covered_announcements,
)
from fomc_intraday.plots import plot_change_by_horizon, plot_repricing_paths
from fomc_intraday.snapshots import select_snapshot
from fomc_intraday.study import market_anchor, run_event_study
from fomc_intraday.synthetic import DEMO_SCENARIOS, make_synthetic_minutes
from fomc_intraday.windows import announcement_window

__all__ = [
    "DEFAULT_N_SR1",
    "DEFAULT_N_SR3",
    "DEMO_SCENARIOS",
    "announcement_window",
    "calendar_meeting_dates",
    "contracts_for",
    "covered_announcements",
    "make_synthetic_minutes",
    "market_anchor",
    "plot_change_by_horizon",
    "plot_repricing_paths",
    "run_event_study",
    "select_snapshot",
]
