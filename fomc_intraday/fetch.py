"""Databento request for minute bars around FOMC announcements.

The request is `GLBX.MDP3` schema `ohlcv-1m` for the outright SR1 and SR3
symbols the estimator needs, from one minute before the window opens
through the window end (Databento's end is exclusive). Nothing in this
module opens a connection by itself: the caller passes a client, and the
script is what builds that client from the team's key file.

`metadata.get_cost` is called on those exact arguments before any
`timeseries.get_range`. If the quoted total is above the cap, no download
runs.
"""

from pathlib import Path

import pandas as pd

from fomc_intraday.events import contracts_for
from fomc_intraday.windows import announcement_window, to_utc
from sofr_data import config

SCHEMA = "ohlcv-1m"
PROCESSED_NAME = "sofr_intraday_ohlcv_1m.parquet"
DEFAULT_MAX_COST_USD = 5.0


class CostCapExceeded(RuntimeError):
    """The quote for this pull is above the cap. Nothing was downloaded."""

    def __init__(self, total, max_cost, quote):
        self.total = float(total)
        self.max_cost = float(max_cost)
        self.quote = quote
        super().__init__(
            f"Databento quote ${self.total:.4f} exceeds the cap ${self.max_cost:.2f}"
        )


def processed_path(processed_dir=None):
    """Where the combined minute-bar cache is written (`data/processed/`)."""
    directory = config.PROCESSED_DIR if processed_dir is None else Path(processed_dir)
    return directory / PROCESSED_NAME


def raw_cache_path(announcement_date, raw_dir=None):
    """One parquet per announcement under `data/raw/intraday/`."""
    directory = config.RAW_DIR / "intraday" if raw_dir is None else Path(raw_dir)
    day = pd.Timestamp(announcement_date).date().isoformat()
    return directory / f"{day}.parquet"


def build_requests(announcement_dates):
    """One Databento request per announcement. No network.

    `start` is one minute before the window so the snapshot at the open
    has a completed bar. `end` equals the window end and is exclusive, so
    the last included bar is the one that closes at the window end.
    Both are timezone-aware UTC.
    """
    requests = []
    for announcement_date in announcement_dates:
        day = pd.Timestamp(announcement_date).normalize()
        contracts = contracts_for(day)
        window = announcement_window(day)
        start = (to_utc(window["window_start"]) - pd.Timedelta(minutes=1)).to_pydatetime()
        end = to_utc(window["window_end"]).to_pydatetime()
        requests.append({
            "announcement_date": day.date().isoformat(),
            "dataset": config.DATASET,
            "schema": SCHEMA,
            "stype_in": "raw_symbol",
            "symbols": sorted(set(contracts["raw_symbol"])),
            "start": start,
            "end": end,
            "contracts": contracts,
        })
    return requests


def request_kwargs(request):
    """The arguments shared by `metadata.get_cost` and `timeseries.get_range`.

    Keeping one dict is what makes the quote the cost of the download
    rather than of a similar request.
    """
    return {
        "dataset": request["dataset"],
        "schema": request["schema"],
        "symbols": list(request["symbols"]),
        "stype_in": request["stype_in"],
        "start": request["start"],
        "end": request["end"],
    }


def quote_cost(client, requests):
    """Call `metadata.get_cost` for each request. Does not download bars."""
    rows = []
    for request in requests:
        cost = client.metadata.get_cost(**request_kwargs(request))
        rows.append({
            "announcement_date": request["announcement_date"],
            "n_symbols": len(request["symbols"]),
            "start": request["start"],
            "end": request["end"],
            "cost_usd": float(cost),
        })
    return pd.DataFrame(rows)


def enforce_cost_cap(quote, max_cost):
    """Return the quoted total, or raise if it is above `max_cost` (USD)."""
    total = 0.0 if quote.empty else float(quote["cost_usd"].sum())
    if total > max_cost:
        raise CostCapExceeded(total, max_cost, quote)
    return total


def normalize_ohlcv(frame, announcement_date, contracts):
    """Turn a Databento `ohlcv-1m` frame into the study's bar columns.

    Prices are the client's decoded index points (`to_df` uses float
    prices). Symbols that are not in this announcement's strip are
    dropped. The close is the last trade of the minute.
    """
    day = pd.Timestamp(announcement_date).normalize()
    if frame is None or len(frame) == 0:
        return pd.DataFrame()

    table = frame.copy()
    if "ts_event" not in table.columns:
        table = table.reset_index()
    if "ts_event" not in table.columns:
        raise ValueError("ohlcv response has no ts_event column")

    symbol_column = "symbol" if "symbol" in table.columns else "raw_symbol"
    if symbol_column not in table.columns:
        raise ValueError("ohlcv response has no symbol column")

    meta = contracts.copy()
    meta["raw_symbol"] = meta["raw_symbol"].str.upper()
    table["raw_symbol"] = table[symbol_column].astype(str).str.upper()
    table = table.loc[table["raw_symbol"].isin(set(meta["raw_symbol"]))]
    if table.empty:
        return pd.DataFrame()

    merged = table.merge(meta, on="raw_symbol", how="left")
    merged["announcement_date"] = day
    merged["ts_utc"] = pd.to_datetime(merged["ts_event"], utc=True)
    merged["volume"] = pd.to_numeric(merged["volume"]) if "volume" in merged.columns else pd.NA
    for column in ("open", "high", "low", "close"):
        if column in merged.columns:
            merged[column] = pd.to_numeric(merged[column])
    keep = [
        "announcement_date", "contract_id", "root", "raw_symbol",
        "reference_start", "reference_end", "ts_utc",
        "open", "high", "low", "close", "volume",
    ]
    present = [column for column in keep if column in merged.columns]
    return merged.loc[:, present].reset_index(drop=True)


def _empty_bars():
    """Column skeleton so an announcement with no trades still caches."""
    columns = [
        "announcement_date", "contract_id", "root", "raw_symbol",
        "reference_start", "reference_end", "ts_utc",
        "open", "high", "low", "close", "volume",
    ]
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def pull(
    client,
    requests,
    max_cost=DEFAULT_MAX_COST_USD,
    raw_dir=None,
    processed_dir=None,
    refresh=False,
    dry_run=False,
):
    """Quote, refuse if over the cap, otherwise download into the cache.

    Cached announcements are not quoted and not requested again unless
    `refresh` is set. A dry run quotes and returns `(None, quote, total)`
    without writing. A real run returns `(bars, quote, total)` and writes
    `data/processed/sofr_intraday_ohlcv_1m.parquet` plus one raw parquet
    per announcement.

    Raises CostCapExceeded before any download when the quote is over
    `max_cost`. `client` may be None when every request is already cached.
    """
    pending = []
    cached = []
    for request in requests:
        path = raw_cache_path(request["announcement_date"], raw_dir)
        if path.exists() and not refresh:
            cached.append(pd.read_parquet(path))
        else:
            pending.append(request)

    if pending:
        if client is None:
            raise RuntimeError("a Databento client is required to quote or download")
        quote = quote_cost(client, pending)
    else:
        quote = pd.DataFrame(columns=["announcement_date", "n_symbols", "start", "end", "cost_usd"])
    total = enforce_cost_cap(quote, max_cost)
    if dry_run:
        return None, quote, total

    frames = list(cached)
    for request in pending:
        store = client.timeseries.get_range(**request_kwargs(request))
        normalized = normalize_ohlcv(store.to_df(), request["announcement_date"], request["contracts"])
        if normalized.empty:
            normalized = _empty_bars()
        path = raw_cache_path(request["announcement_date"], raw_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_parquet(path, index=False)
        frames.append(normalized)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not combined.empty:
        destination = processed_path(processed_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(destination, index=False)
    return combined, quote, total
