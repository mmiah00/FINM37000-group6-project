"""Clock times around an FOMC statement.

The statement is released at 14:00 US Eastern. That same clock time is
UTC-4 in summer (EDT) and UTC-5 in winter (EST). `zoneinfo` applies the
US daylight-saving rules for the announcement date, so a June meeting and
a December meeting do not share a fixed UTC offset.

The press conference, when there is one, starts at 14:30 Eastern.
"""

from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

EASTERN = ZoneInfo("America/New_York")

STATEMENT_TIME = time(14, 0)
PRE_SNAPSHOT_TIME = time(13, 55)
# After the statement, and after the 14:30 press conference.
POST_SNAPSHOT_TIMES = (time(14, 15), time(14, 45))
PRESS_CONFERENCE_TIME = time(14, 30)

DEFAULT_MINUTES_BEFORE = 60
DEFAULT_MINUTES_AFTER = 120


def as_naive_date(value):
    """Midnight, with no timezone, for the calendar date of `value`."""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(EASTERN)
    return stamp.normalize().tz_localize(None)


def eastern_on(announcement_date, clock_time):
    """Eastern clock time on the announcement's calendar date.

    Returns a timezone-aware pandas Timestamp. 14:00 is never in the
    DST gap (the US transition is at 02:00), so the clock time exists
    on every announcement date.
    """
    day = as_naive_date(announcement_date)
    local = pd.Timestamp(
        year=int(day.year),
        month=int(day.month),
        day=int(day.day),
        hour=clock_time.hour,
        minute=clock_time.minute,
    )
    return local.tz_localize(EASTERN)


def to_utc(timestamp):
    """Convert an aware timestamp to UTC."""
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        raise ValueError("timestamp needs a timezone; Eastern clock times are not UTC")
    return stamp.tz_convert("UTC")


def announcement_window(announcement_date):
    """Window and snapshot times around the 14:00 Eastern statement.

    The window runs 60 minutes before the statement through 120 minutes after
    (13:00 to 16:00 Eastern). The pre snapshot is the last trade at or
    before 13:55. Post snapshots are 14:15, 14:45, and the window end
    (16:00), so one of them sits after the 14:30 press
    conference.

    Every returned timestamp is timezone-aware US Eastern.
    """
    statement = eastern_on(announcement_date, STATEMENT_TIME)
    window_start = statement - pd.Timedelta(minutes=DEFAULT_MINUTES_BEFORE)
    window_end = statement + pd.Timedelta(minutes=DEFAULT_MINUTES_AFTER)
    pre_snapshot = eastern_on(announcement_date, PRE_SNAPSHOT_TIME)

    post_snapshots = [eastern_on(announcement_date, clock) for clock in POST_SNAPSHOT_TIMES]
    post_snapshots.append(window_end)

    return {
        "announcement_date": as_naive_date(announcement_date),
        "statement": statement,
        "window_start": window_start,
        "window_end": window_end,
        "pre_snapshot": pre_snapshot,
        "post_snapshots": post_snapshots,
        "press_conference": eastern_on(announcement_date, PRESS_CONFERENCE_TIME),
    }


def snapshot_label(timestamp, statement):
    """Name such as 'pre_1355' or 'post_1415' from the Eastern clock."""
    local = pd.Timestamp(timestamp).tz_convert(EASTERN)
    kind = "pre" if local <= statement else "post"
    return f"{kind}_{local.strftime('%H%M')}"


def minute_grid(window):
    """Every whole minute from the window start through the window end, inclusive."""
    times = []
    stamp = window["window_start"]
    while stamp <= window["window_end"]:
        times.append(stamp)
        stamp = stamp + pd.Timedelta(minutes=1)
    return times
