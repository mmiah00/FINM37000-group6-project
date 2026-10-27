"""Last-trade snapshots and last-price carry for minute bars.

Databento `ohlcv-1m` bars are stamped at the START of the minute. The
close is the last trade in that minute, so it is known one minute later.
A snapshot "at or before 13:55" therefore uses bars whose end is at or
before 13:55 (the bar that started at 13:54), and does not use the bar
that started at 13:55.

Contracts that did not trade in the latest minute keep their last earlier
trade. That is the carry-forward. A contract with no trade at or before
the snapshot is left out: there is no price to carry.
"""

import pandas as pd

from fomc_intraday.windows import to_utc

BAR_COLUMNS = [
    "contract_id",
    "root",
    "reference_start",
    "reference_end",
    "ts_utc",
    "close",
    "volume",
]


def prepare_bars(bars):
    """Copy `bars` and add `bar_end_utc` (one minute after the bar start).

    Naive `ts_utc` values are read as UTC. That matches Databento's
    `to_df()` default.
    """
    missing = [column for column in BAR_COLUMNS if column not in bars.columns]
    if missing:
        raise ValueError(f"minute bars are missing columns {missing}")

    frame = bars.copy()
    frame["ts_utc"] = pd.to_datetime(frame["ts_utc"], utc=True)
    frame["bar_end_utc"] = frame["ts_utc"] + pd.Timedelta(minutes=1)
    frame["reference_start"] = pd.to_datetime(frame["reference_start"])
    frame["reference_end"] = pd.to_datetime(frame["reference_end"])
    frame["close"] = pd.to_numeric(frame["close"])
    frame["volume"] = pd.to_numeric(frame["volume"])
    return frame


def _traded(frame):
    """Bars that actually traded.

    A missing volume is treated as a trade when the close is present
    (some exports omit volume). A volume of zero is not a trade: carrying
    a quote-only bar forward would freeze a price nobody traded.
    """
    has_price = frame["close"].notna()
    traded = frame["volume"].isna() | (frame["volume"] > 0)
    return frame.loc[has_price & traded]


def select_snapshot(bars, snapshot_time):
    """Last traded close of each contract at or before `snapshot_time`.

    `snapshot_time` is an aware timestamp (the window helpers return
    US Eastern). Returns one row per contract that has traded by then,
    including `close` and `bar_end_utc` of the trade that was carried.
    Contracts with no earlier trade are absent, not filled with NaN.
    """
    frame = prepare_bars(bars)
    deadline = to_utc(snapshot_time)
    eligible = _traded(frame)
    eligible = eligible.loc[eligible["bar_end_utc"] <= deadline]
    if eligible.empty:
        return eligible.copy()
    # If two bars share an end time, keep the later row in file order.
    eligible = eligible.drop_duplicates(["contract_id", "ts_utc"], keep="last")
    chosen = eligible.groupby("contract_id")["bar_end_utc"].idxmax()
    return eligible.loc[chosen].reset_index(drop=True)


def to_contract_table(snapshot):
    """Rename a snapshot into the columns `fit_meeting_moves` expects.

    The close of the carried minute is the market price. The estimator
    calls that column `settlement_price` because the daily fit uses
    settlement prices; intraday, it is the last trade.
    """
    if snapshot.empty:
        raise ValueError("snapshot has no traded contracts")
    table = snapshot.rename(columns={"close": "settlement_price"})
    columns = ["contract_id", "root", "reference_start", "reference_end", "settlement_price"]
    return table.loc[:, columns].reset_index(drop=True)
