"""FOMC announcement dates for the curve comparison.

The schedule is the one bundled in `fomc_data` (the Federal Reserve's
regularly scheduled decision dates). Nothing in this package invents an
evenly spaced substitute.
"""

import pandas as pd

from fomc_data.fomc_calendar import fetch_fomc_calendar


def meeting_calendar(start=None, end=None):
    """Announcement dates from `fomc_data.fomc_calendar.fetch_fomc_calendar`.

    `start` and `end` are inclusive. Omit them to take the calendar's own
    sample (2022-01-01 through 2026-09-30). Each date is midnight, with no
    time zone.
    """
    kwargs = {}
    if start is not None:
        kwargs["start"] = start
    if end is not None:
        kwargs["end"] = end
    calendar = fetch_fomc_calendar(**kwargs) if kwargs else fetch_fomc_calendar()
    return [pd.Timestamp(day).normalize() for day in calendar["meeting_date"]]
