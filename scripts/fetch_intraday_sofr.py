#!/usr/bin/env python3
"""Pull minute SOFR futures bars around FOMC announcements.

The bars are Databento `GLBX.MDP3` `ohlcv-1m` for the SR1 and SR3 outright
contracts the meeting-path estimator uses. The window is 60 minutes before
the 14:00 US Eastern statement through 120 minutes after. The key is read
the same way as the daily settlement pull
(`~/.databento_api_key`, then `DATABENTO_API_KEY`).

The script asks Databento what the request would cost and does not
download if the total is above `--max-cost` (default 5 dollars). Cached
announcements are not requested again.

Examples:
    python scripts/fetch_intraday_sofr.py --dry-run
    python scripts/fetch_intraday_sofr.py --dates 2024-09-18 2024-12-18
    python scripts/fetch_intraday_sofr.py --offline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fomc_intraday.events import (  # noqa: E402
    calendar_meeting_dates,
    covered_announcements,
)
from fomc_intraday.fetch import (  # noqa: E402
    DEFAULT_MAX_COST_USD,
    CostCapExceeded,
    build_requests,
    pull,
)


def parse_args(argv=None):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dates",
        nargs="+",
        default=None,
        help="Announcement dates (YYYY-MM-DD). Default: every covered date in the team calendar.",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=DEFAULT_MAX_COST_USD,
        help="Do not download if the Databento quote is above this many US dollars (default 5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the quote and exit without downloading.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild the processed cache from announcement parquets already on disk.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the local cache and quote every announcement again.",
    )
    return parser.parse_args(argv)


def choose_dates(args):
    """Dates to request, and any the user named that the schedule cannot cover."""
    schedule = calendar_meeting_dates()
    covered = covered_announcements(schedule)
    covered_set = {day.date().isoformat() for day in covered}
    if args.dates is None:
        return [day.date().isoformat() for day in covered], []

    unknown = []
    dropped = []
    kept = []
    schedule_set = {day.date().isoformat() for day in schedule}
    for raw in args.dates:
        day = raw.strip()
        if day not in schedule_set:
            unknown.append(day)
        elif day not in covered_set:
            dropped.append(day)
        else:
            kept.append(day)
    if unknown:
        raise ValueError("Not in the team FOMC calendar: " + ", ".join(unknown))
    return kept, dropped


def print_quote(quote, total, max_cost, cached_count):
    """Print the cost table. Does not print the API key."""
    print("\nEstimated Databento cost for ohlcv-1m around these announcements:\n")
    if quote.empty:
        print("  No uncached requests.")
    else:
        print(quote.to_string(index=False))
    print(f"\n  Quoted total (uncached only): ${total:,.4f}")
    print(f"  Cap (--max-cost):             ${max_cost:,.2f}")
    if cached_count:
        print(f"  Already cached, not quoted:   {cached_count}")
    print()


def main(argv=None):
    """Quote, and download only if the quote is within the cap."""
    args = parse_args(argv)
    if args.offline and args.refresh:
        print("--offline and --refresh cannot be used together.", file=sys.stderr)
        return 2

    try:
        dates, dropped = choose_dates(args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if dropped:
        print(
            "These dates are in the calendar, but the futures strip runs past the "
            "last scheduled meeting, so the estimator cannot use them yet: "
            + ", ".join(dropped),
            file=sys.stderr,
        )
        return 2
    if not dates:
        print("No announcements to request.", file=sys.stderr)
        return 2

    requests = build_requests(dates)
    cached_count = sum(1 for request in requests if _cached(request))

    if args.offline:
        missing = [request["announcement_date"] for request in requests if not _cached(request)]
        if missing:
            print("No cached bars for: " + ", ".join(missing), file=sys.stderr)
            return 2
        bars, quote, total = pull(
            None, requests, max_cost=args.max_cost, refresh=False, dry_run=False,
        )
        print_quote(quote, total, args.max_cost, cached_count)
        if bars is None or bars.empty:
            print("No cached intraday bars to rebuild.", file=sys.stderr)
            return 2
        print(f"Rebuilt {len(bars):,} cached rows.")
        return 0

    needs_client = args.refresh or cached_count != len(requests) or args.dry_run
    # A dry run of a fully cached pull still quotes nothing and needs no key.
    if args.dry_run and cached_count == len(requests) and not args.refresh:
        needs_client = False

    client = None
    if needs_client:
        try:
            from sofr_data.databento_io import make_client
            client = make_client()
        except FileNotFoundError as error:
            print(f"\n{error}\n", file=sys.stderr)
            return 2

    try:
        bars, quote, total = pull(
            client,
            requests,
            max_cost=args.max_cost,
            refresh=args.refresh,
            dry_run=args.dry_run,
        )
    except CostCapExceeded as error:
        print_quote(error.quote, error.total, error.max_cost, 0 if args.refresh else cached_count)
        print("Nothing was downloaded.")
        return 3

    print_quote(quote, total, args.max_cost, 0 if args.refresh else cached_count)
    if args.dry_run:
        print("Dry run: nothing was downloaded.")
        return 0

    from fomc_intraday.fetch import processed_path
    n_rows = 0 if bars is None else len(bars)
    print(f"Wrote {n_rows:,} rows to {processed_path()}")
    return 0


def _cached(request):
    from fomc_intraday.fetch import raw_cache_path
    return raw_cache_path(request["announcement_date"]).exists()


if __name__ == "__main__":
    sys.exit(main())
