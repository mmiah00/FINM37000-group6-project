#!/usr/bin/env python3
"""Collect and clean CME SOFR futures settlement prices from Databento.

Pulls One-Month (SR1) and Three-Month (SR3) SOFR futures settlement prices for
the project sample, standardizes contract identifiers and settlement reference
periods, runs the data quality checks and writes the result to
`data/processed/`.

Examples:
    # What would this cost? Makes no billable data request.
    python scripts/fetch_sofr_futures.py --dry-run

    # Full pull for the project sample.
    python scripts/fetch_sofr_futures.py

    # Rebuild the processed files from the existing cache, fetching nothing.
    python scripts/fetch_sofr_futures.py --offline
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sofr_data import clean, config, databento_io, quality  # noqa: E402

logger = logging.getLogger("fetch_sofr_futures")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=config.START.date().isoformat())
    parser.add_argument("--end", default=config.END.date().isoformat())
    parser.add_argument(
        "--roots",
        nargs="+",
        default=list(config.ROOTS),
        choices=list(config.ROOTS),
        help="Product roots to collect.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the estimated Databento cost and exit.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild from the local cache only; make no Databento requests.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the local cache and re-fetch every chunk.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the cost confirmation prompt.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def confirm_cost(client: databento_io.db.Historical, args: argparse.Namespace) -> bool:
    """Show the estimated cost of the pull and ask before spending credits."""
    estimate = databento_io.estimate_cost(
        client,
        roots=tuple(args.roots),
        start=pd.Timestamp(args.start),
        end=pd.Timestamp(args.end),
    )
    total = float(estimate["cost_usd"].sum())
    print("\nEstimated Databento usage for this pull:\n")
    print(estimate.to_string(index=False))
    print(f"\n  Total estimated cost: ${total:,.4f}")
    print("  (Cached chunks are not re-requested, so the actual charge may be lower.)\n")

    if args.dry_run or args.yes:
        return not args.dry_run
    reply = input("Proceed with the pull? [y/N] ").strip().lower()
    return reply in {"y", "yes"}


def collect(args: argparse.Namespace) -> pd.DataFrame:
    """Fetch and clean the panel for every requested root."""
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    client = None if args.offline else databento_io.make_client()

    if client is not None and not confirm_cost(client, args):
        print("Aborted; nothing was fetched.")
        sys.exit(0)

    panels = []
    for root in args.roots:
        logger.info("collecting %s", root)
        if args.offline:
            statistics = _read_cache(root, "statistics")
            definitions = _read_cache(root, "definitions")
        else:
            statistics = databento_io.fetch_statistics(
                client, root, start, end, refresh=args.refresh
            )
            definitions = databento_io.fetch_definitions(
                client, root, start, end, refresh=args.refresh
            )
        logger.info(
            "%s: %d statistics records, %d definition records",
            root,
            len(statistics),
            len(definitions),
        )
        panel = clean.build_panel(statistics, definitions)
        logger.info("%s: %d cleaned rows", root, len(panel))
        panels.append(panel)

    if not panels:
        return pd.DataFrame(columns=clean.OUTPUT_COLUMNS)
    combined = pd.concat(panels, ignore_index=True)
    in_sample = combined["trade_date"].between(start, end)
    return combined.loc[in_sample].reset_index(drop=True)


def _read_cache(root: str, kind: str) -> pd.DataFrame:
    """Load every cached parquet chunk for a root and schema."""
    directory = config.RAW_DIR / root / kind
    files = sorted(directory.glob("*.parquet")) if directory.exists() else []
    if not files:
        logger.warning("no cached %s for %s under %s", kind, root, directory)
        return pd.DataFrame()
    frames = []
    for path in files:
        frame = pd.read_parquet(path)
        if kind == "definitions" and not frame.empty:
            frame = frame.assign(snapshot_date=pd.Timestamp(path.stem))
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    """Run the collection pipeline."""
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    config.ensure_dirs()

    try:
        if args.dry_run:
            confirm_cost(databento_io.make_client(), args)
            return 0
        panel = collect(args)
    except FileNotFoundError as exc:
        # Missing API key, or `--offline` with nothing cached. Both are the
        # user's situation to fix, not a bug worth a traceback.
        print(f"\n{exc}\n", file=sys.stderr)
        return 2
    if panel.empty:
        logger.error("no data collected; nothing written")
        return 1

    panel, post_expiry_dropped = clean.drop_post_expiry(panel)
    contracts = clean.build_contract_table(panel)

    panel.to_parquet(config.SETTLEMENTS_PARQUET, index=False)
    panel.to_csv(config.SETTLEMENTS_CSV, index=False)
    contracts.to_parquet(config.CONTRACTS_PARQUET, index=False)
    contracts.to_csv(config.CONTRACTS_CSV, index=False)

    report = quality.run_checks(
        panel, extra={"post_expiry_rows_dropped": post_expiry_dropped}
    )
    quality.write_report(report)

    print(f"\nWrote {len(panel):,} rows covering {panel['contract_id'].nunique()} contracts")
    print(f"  {config.SETTLEMENTS_PARQUET.relative_to(config.REPO_ROOT)}")
    print(f"  {config.CONTRACTS_PARQUET.relative_to(config.REPO_ROOT)}")
    print(f"  {config.QUALITY_REPORT.relative_to(config.REPO_ROOT)}")
    for key in (
        "live_rows_without_settlement",
        "implausible_prices",
        "duplicate_rows",
        "expiration_convention_mismatches",
    ):
        print(f"  {key}: {report.summary.get(key)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
