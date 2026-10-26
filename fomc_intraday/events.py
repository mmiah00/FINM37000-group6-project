"""Which FOMC announcements and which outright contracts enter the study.

The meeting list is the team's `fomc_data` calendar. The contracts come
from the team's `contract_strip`: the same SR1 months and quarterly SR3
months the daily estimator prices, fewer of them by default (see
`DEFAULT_N_SR1`). A raw CME symbol is attached with
`sofr_data.contracts.Contract`, so the Databento request uses the same
identifier as the settlement pipeline.

Not every calendar date can be fit. The estimator refuses a strip whose
last reference day sits more than about nine weeks past the last scheduled
meeting, because the missing meetings would be loaded onto the meetings
that are listed. The published calendar ends in September 2026, so the
latest announcements drop out until later meetings are added. That filter
is `covered_announcements`.
"""

import pandas as pd

from fomc_data.fomc_calendar import fetch_fomc_calendar
from sofr_data.contracts import Contract
from sofr_pricing import contract_strip, fixing_dates, upcoming_meetings

# Eight SR1 months and three SR3 quarters.
#
# The daily fit uses 13 SR1 and 6 SR3. That strip reaches meetings a
# three-hour window barely trades, and with the published calendar it
# leaves the furthest meeting weakly identified (the Jacobian comes up
# one rank short and the condition number blows up). Eight and three
# cover the next several meetings, stay full rank on the dates checked
# in the tests, and are the outright contracts a minute-bar pull can
# actually price.
DEFAULT_N_SR1 = 8
DEFAULT_N_SR3 = 3


def calendar_meeting_dates(start=None, end=None):
    """Announcement dates from the team's FOMC calendar, oldest first."""
    if start is None and end is None:
        table = fetch_fomc_calendar()
    else:
        table = fetch_fomc_calendar(start, end)
    return [pd.Timestamp(day).normalize() for day in table["meeting_date"]]


def estimator_obs_date(announcement_date):
    """Observation date passed to the daily estimator.

    `fit_meeting_moves` treats a meeting ON the observation date as already
    announced, because daily settlements are end-of-day. An intraday
    snapshot is around 14:00, and the study reads today's expected move
    out of prices both before and after the statement. The observation
    date stays at midnight; today's meeting is stamped at 14:00 by
    `estimator_meeting_dates`, which is strictly after midnight, so the
    estimator still treats it as unknown.

    The policy anchor is computed separately and is the rate in force
    that morning, before the decision.
    """
    return pd.Timestamp(announcement_date).normalize()


def estimator_meeting_dates(announcement_date, meeting_dates):
    """Calendar dates, with the announcement itself stamped at 14:00.

    See `estimator_obs_date`. Other meetings stay at midnight, so meetings
    on earlier days remain "already announced" and later days remain
    unknown. Effective dates are unchanged: 14:00 still falls before the
    next business day's fixing.
    """
    announcement = pd.Timestamp(announcement_date).normalize()
    stamped = []
    for meeting in meeting_dates:
        day = pd.Timestamp(meeting).normalize()
        if day == announcement:
            stamped.append(day + pd.Timedelta(hours=14))
        else:
            stamped.append(day)
    return stamped


def contracts_for(announcement_date):
    """SR1/SR3 strip the estimator needs that day, plus the CME raw symbol.

    `contract_id` matches `sofr_pricing.contract_strip` (`SR3-2024-09`).
    `raw_symbol` matches the settlement pipeline (`SR3U4`).
    """
    day = pd.Timestamp(announcement_date).normalize()
    table = contract_strip(day, n_sr1=DEFAULT_N_SR1, n_sr3=DEFAULT_N_SR3).copy()

    def raw_symbol(contract_id):
        root, year, month = contract_id.split("-")
        return Contract(root, int(year), int(month)).raw_symbol

    table["raw_symbol"] = [raw_symbol(contract_id) for contract_id in table["contract_id"]]
    return table


def strip_is_covered(announcement_date, meeting_dates):
    """True when the estimator can see every meeting this strip can reach.

    Uses `upcoming_meetings`, so the rule cannot drift from the fit.
    """
    day = pd.Timestamp(announcement_date).normalize()
    contracts = contracts_for(day)
    last_day = pd.Timestamp(contracts["reference_end"].max())
    first_day = pd.Timestamp(contracts["reference_start"].min()) - pd.Timedelta(days=10)
    dates = fixing_dates(first_day, last_day + pd.Timedelta(days=10))
    try:
        upcoming_meetings(
            estimator_obs_date(day),
            estimator_meeting_dates(day, meeting_dates),
            dates,
            last_day,
        )
    except ValueError:
        return False
    return True


def covered_announcements(meeting_dates=None):
    """Announcements inside the calendar whose strip the schedule can support.

    `meeting_dates` defaults to the full team calendar. Passing a shorter
    list also shortens the schedule the coverage check sees.
    """
    if meeting_dates is None:
        meeting_dates = calendar_meeting_dates()
    covered = []
    for day in meeting_dates:
        if strip_is_covered(day, meeting_dates):
            covered.append(pd.Timestamp(day).normalize())
    return covered
