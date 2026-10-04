"""Fetch SOFR futures definitions and daily statistics from Databento.

Settlement prices live in the ``statistics`` schema, not in ``ohlcv-1d``: the
daily OHLCV close is the last trade of the session, which for a back-month SOFR
contract is often stale or absent. The exchange's official settlement is
published as a statistics record with `stat_type == SETTLEMENT_PRICE`.

Every request is chunked and cached to `data/raw/` as parquet. Databento bills
per request, so a rerun after a crash or a change to the cleaning code costs
nothing as long as the cache is intact.
"""

from __future__ import annotations

import logging
from pathlib import Path

import databento as db
import pandas as pd

from sofr_data import config

logger = logging.getLogger(__name__)

DEFINITION_COLUMNS = [
    "instrument_id",
    "raw_symbol",
    "instrument_class",
    "expiration",
    "activation",
]

STATISTICS_COLUMNS = [
    "ts_event",
    "ts_ref",
    "instrument_id",
    "symbol",
    "price",
    "quantity",
    "stat_type",
    "stat_flags",
]


def make_client(api_key: str | None = None) -> db.Historical:
    """Build a Databento historical client without putting the key in code."""
    return db.Historical(api_key or config.resolve_api_key())


# --- chunking ---------------------------------------------------------------


def quarter_chunks(
    start: pd.Timestamp, end: pd.Timestamp
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split ``[start, end]`` into quarterly ``[chunk_start, chunk_end)`` pairs.

    Databento treats `end` as exclusive, so the returned right edges are
    exclusive and the final one sits one day past `end`.

    >>> chunks = quarter_chunks(pd.Timestamp("2022-01-15"), pd.Timestamp("2022-07-02"))
    >>> [(a.date().isoformat(), b.date().isoformat()) for a, b in chunks]
    [('2022-01-15', '2022-04-01'), ('2022-04-01', '2022-07-01'), ('2022-07-01', '2022-07-03')]
    """
    edges = pd.date_range(
        start.normalize(), (end + pd.Timedelta(days=1)).normalize(), freq="QS"
    )
    edges = pd.DatetimeIndex([start.normalize(), *edges, (end + pd.Timedelta(days=1)).normalize()])
    edges = edges[(edges >= start.normalize()) & (edges <= (end + pd.Timedelta(days=1)).normalize())]
    edges = edges.drop_duplicates().sort_values()
    return list(zip(edges[:-1], edges[1:], strict=True))


def month_starts(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    """Dates on which to snapshot instrument definitions.

    One snapshot per month is enough to see every contract in the sample: the
    shortest-lived SOFR future (SR1) is listed about 13 months ahead of its
    expiry, so no contract can be listed and delisted between two snapshots.

    >>> [d.date().isoformat() for d in month_starts(pd.Timestamp('2022-01-10'), pd.Timestamp('2022-03-05'))]
    ['2022-01-10', '2022-02-01', '2022-03-01']
    """
    firsts = pd.date_range(start.normalize(), end.normalize(), freq="MS")
    dates = pd.DatetimeIndex([start.normalize(), *firsts]).drop_duplicates().sort_values()
    return list(dates[dates <= end.normalize()])


# --- caching ----------------------------------------------------------------


def _cache_path(root: str, kind: str, label: str) -> Path:
    directory = config.RAW_DIR / root / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{label}.parquet"


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def _subset(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Keep `columns` that are actually present, preserving their order."""
    present = [c for c in columns if c in frame.columns]
    return frame.loc[:, present].copy()


def _store_to_df(store: db.DBNStore, columns: list[str]) -> pd.DataFrame:
    """Convert a DBN store to a DataFrame, tolerating an empty response."""
    try:
        frame = store.to_df()
    except ValueError:  # no records in the range
        return _empty(columns)
    if frame.empty:
        return _empty(columns)
    return _subset(frame.reset_index(), columns)


def _cached_fetch(path: Path, fetch: callable, refresh: bool) -> pd.DataFrame:
    """Return a cached parquet file, or fetch, cache and return the data."""
    if path.exists() and not refresh:
        logger.info("cache hit  %s", path.name)
        return pd.read_parquet(path)

    logger.info("fetching   %s", path.name)
    frame = fetch()
    try:
        frame.to_parquet(path, index=False)
    except Exception as exc:  # caching is best-effort; never lose a paid pull
        logger.warning("could not cache %s: %s", path, exc)
    return frame


# --- definitions ------------------------------------------------------------


def fetch_definitions(
    client: db.Historical,
    root: str,
    start: pd.Timestamp = config.START,
    end: pd.Timestamp = config.END,
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch instrument definitions for every leg of a product's futures chain.

    Takes one definition snapshot per month and unions them, so contracts
    listed part-way through the sample are still picked up.

    Returns:
        One row per (snapshot date, instrument), with `snapshot_date`,
        `instrument_id`, `raw_symbol`, `instrument_class`, `expiration` and
        `activation`.
    """
    frames = []
    for snapshot in month_starts(start, end):
        label = snapshot.date().isoformat()
        path = _cache_path(root, "definitions", label)

        def fetch(snapshot: pd.Timestamp = snapshot) -> pd.DataFrame:
            store = client.timeseries.get_range(
                dataset=config.DATASET,
                schema="definition",
                symbols=config.PARENT_SYMBOL[root],
                stype_in="parent",
                start=snapshot.date(),
                end=(snapshot + pd.Timedelta(days=1)).date(),
            )
            return _store_to_df(store, DEFINITION_COLUMNS)

        frame = _cached_fetch(path, fetch, refresh)
        if not frame.empty:
            frames.append(frame.assign(snapshot_date=snapshot))

    if not frames:
        return _empty([*DEFINITION_COLUMNS, "snapshot_date"])
    return pd.concat(frames, ignore_index=True)


def fetch_statistics(
    client: db.Historical,
    root: str,
    start: pd.Timestamp = config.START,
    end: pd.Timestamp = config.END,
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch daily statistics records for every leg of a product's chain.

    Requested in quarterly chunks via `parent` symbology, which covers legs
    listed or expiring mid-sample without having to enumerate symbols.
    """
    frames = []
    for chunk_start, chunk_end in quarter_chunks(start, end):
        label = f"{chunk_start.date().isoformat()}_{chunk_end.date().isoformat()}"
        path = _cache_path(root, "statistics", label)

        def fetch(
            chunk_start: pd.Timestamp = chunk_start, chunk_end: pd.Timestamp = chunk_end
        ) -> pd.DataFrame:
            store = client.timeseries.get_range(
                dataset=config.DATASET,
                schema="statistics",
                symbols=config.PARENT_SYMBOL[root],
                stype_in="parent",
                start=chunk_start.date(),
                end=chunk_end.date(),
            )
            return _store_to_df(store, STATISTICS_COLUMNS)

        frame = _cached_fetch(path, fetch, refresh)
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return _empty(STATISTICS_COLUMNS)
    return pd.concat(frames, ignore_index=True)


# --- cost estimation --------------------------------------------------------


def estimate_cost(
    client: db.Historical,
    roots: tuple[str, ...] = config.ROOTS,
    start: pd.Timestamp = config.START,
    end: pd.Timestamp = config.END,
) -> pd.DataFrame:
    """Estimate the Databento cost of a full pull before spending anything.

    The definition figure is approximate: it prices a single one-day snapshot
    and multiplies by the number of monthly snapshots.

    Returns:
        A `pd.DataFrame` with one row per (root, schema) and columns
        `records` and `cost_usd`.
    """
    end_exclusive = (end + pd.Timedelta(days=1)).date()
    snapshots = month_starts(start, end)
    rows = []

    for root in roots:
        symbol = config.PARENT_SYMBOL[root]
        shared = {
            "dataset": config.DATASET,
            "symbols": symbol,
            "stype_in": "parent",
        }
        rows.append(
            {
                "root": root,
                "schema": "statistics",
                "records": client.metadata.get_record_count(
                    schema="statistics", start=start.date(), end=end_exclusive, **shared
                ),
                "cost_usd": client.metadata.get_cost(
                    schema="statistics", start=start.date(), end=end_exclusive, **shared
                ),
            }
        )

        probe = snapshots[0]
        one_day = {
            "start": probe.date(),
            "end": (probe + pd.Timedelta(days=1)).date(),
        }
        rows.append(
            {
                "root": root,
                "schema": f"definition (~{len(snapshots)} snapshots)",
                "records": client.metadata.get_record_count(
                    schema="definition", **one_day, **shared
                )
                * len(snapshots),
                "cost_usd": client.metadata.get_cost(
                    schema="definition", **one_day, **shared
                )
                * len(snapshots),
            }
        )

    return pd.DataFrame(rows)
