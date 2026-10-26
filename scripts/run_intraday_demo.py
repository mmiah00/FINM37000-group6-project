#!/usr/bin/env python3
"""Intraday FOMC event study.

By default this builds deterministic synthetic minute bars with a known
policy surprise at 14:00 US Eastern and shows that the team's estimator
recovers it. No Databento key and no network.

    python scripts/run_intraday_demo.py
    python scripts/run_intraday_demo.py --out reports/intraday

With bars and daily rates already on disk, write the market study
somewhere other than the synthetic directory:

    PYTHONPATH=. python scripts/fetch_rate_data.py
    python scripts/fetch_intraday_sofr.py --dry-run
    python scripts/run_intraday_demo.py --real --out reports/intraday/real

`--real` reads `data/processed/sofr_intraday_ohlcv_1m.parquet` plus the
SOFR and FOMC files from `scripts/fetch_rate_data.py`. It does not
download anything. The committed market run is `reports/intraday/real/`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import pandas as pd  # noqa: E402

from fomc_intraday import calendar_meeting_dates  # noqa: E402
from fomc_intraday.fetch import processed_path  # noqa: E402
from fomc_intraday.plots import (  # noqa: E402
    plot_change_by_horizon,
    plot_repricing_paths,
    snapshot_change_table,
)
from fomc_intraday.study import (  # noqa: E402
    fit_announcement,
    load_team_rates,
    market_anchor,
    run_event_study,
    stack_studies,
)
from fomc_intraday.synthetic import make_demo_bars  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="reports/intraday",
        help="Directory for the figures and tables (default reports/intraday).",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Fit cached minute bars instead of the synthetic check.",
    )
    return parser.parse_args(argv)


def _truth_rows(truths):
    rows = []
    for truth in truths:
        regimes = (
            ("pre_1355", "pre_moves_bps"),
            ("statement", "statement_moves_bps"),
            ("press", "press_moves_bps"),
        )
        for regime, key in regimes:
            for meeting, move in sorted(truth[key].items()):
                rows.append({
                    "announcement_date": truth["announcement_date"],
                    "label": truth["label"],
                    "regime": regime,
                    "meeting_date": meeting,
                    "move_bps": move,
                    "anchor_percent": truth["anchor"],
                })
    return pd.DataFrame(rows)


def _max_abs_error(snapshots, truths):
    """Largest gap, in bp, between a recovered move and the move that built the bars."""
    worst = 0.0
    checks = (
        ("pre_1355", "pre_moves_bps"),
        ("post_1415", "statement_moves_bps"),
        ("post_1445", "press_moves_bps"),
        ("post_1600", "press_moves_bps"),
    )
    for truth in truths:
        day = pd.Timestamp(truth["announcement_date"])
        block = snapshots.loc[snapshots["announcement_date"] == day]
        for snapshot_name, key in checks:
            expected = truth[key]
            rows = block.loc[block["snapshot"] == snapshot_name]
            for row in rows.itertuples(index=False):
                target = expected.get(pd.Timestamp(row.meeting_date), 0.0)
                worst = max(worst, abs(float(row.implied_move_bps) - target))
    return worst


def run_synthetic():
    """Fit the three built-in scenarios. Returns tables and True for `synthetic`."""
    meeting_dates = calendar_meeting_dates()
    bars, truths = make_demo_bars()
    studies = []
    for truth in truths:
        day = truth["announcement_date"]
        studies.append(run_event_study(
            bars,
            day,
            meeting_dates,
            anchor=truth["anchor"],
            basis=truth["basis"],
            label=truth["label"],
        ))
    snapshots, minutes, diagnostics = stack_studies(studies)
    return snapshots, minutes, diagnostics, truths


def _fit_one_day(day_iso):
    """Fit one announcement from the tables the worker was given.

    The pool forks this process, so `_REAL` is the parent's loaded data.
    """
    day = pd.Timestamp(day_iso)
    anchor, basis = market_anchor(day, _REAL["decisions"], _REAL["sofr"])
    return fit_announcement(
        _REAL["bars"],
        day,
        _REAL["meeting_dates"],
        anchor,
        basis=basis,
        realized_fixings=_REAL["sofr"],
        label=day.date().isoformat(),
    )


def run_real():
    """Fit cached minute bars, anchored on the team's daily SOFR and decisions.

    Days are fit in parallel. One fit of a three-hour window is about a
    minute, and the sample is a few dozen announcements.
    """
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    path = processed_path()
    if not path.exists():
        raise FileNotFoundError(
            f"No minute bars at {path}. Run scripts/fetch_intraday_sofr.py after a cost check."
        )
    decisions, sofr = load_team_rates()
    bars = pd.read_parquet(path)
    if bars.empty:
        raise FileNotFoundError(f"{path} is empty.")

    global _REAL
    _REAL = {
        "bars": bars,
        "decisions": decisions,
        "sofr": sofr,
        "meeting_dates": calendar_meeting_dates(),
    }
    dates = pd.to_datetime(bars["announcement_date"]).dt.tz_localize(None).dt.normalize()
    day_list = [day.date().isoformat() for day in sorted(dates.unique())]
    workers = min(4, len(day_list))
    studies = []
    # fork, so the worker sees _REAL without re-running this script.
    context = multiprocessing.get_context("fork")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        for study in pool.map(_fit_one_day, day_list):
            spliced = bool(study.diagnostics["used_realized_fixings"].any())
            note = "SOFR spliced" if spliced else "SOFR not spliced (series does not cover the front month)"
            print(f"  {study.snapshots['label'].iloc[0]}  {note}", flush=True)
            studies.append(study)
    snapshots, minutes, diagnostics = stack_studies(studies)
    return snapshots, minutes, diagnostics


def _path_labels(snapshots, diagnostics, limit=3):
    """Up to `limit` fully identified announcements with the largest horizon-1 move.

    The path chart has up to three afternoons. The horizon chart and the
    tables keep the whole sample. A day that is not full rank stays in
    the tables and off this chart, because that path is not unique.
    """
    post = snapshots.loc[
        (snapshots["snapshot"] == "post_1600") & (snapshots["horizon"] == 1)
    ].copy()
    identified = diagnostics.loc[
        (diagnostics["snapshot"] == "post_1600") & (diagnostics["fully_identified"].astype(bool))
    ]
    ranked = post.loc[post["label"].isin(set(identified["label"]))]
    ranked = ranked.assign(abs_move=ranked["delta_cum_bps"].abs())
    return list(ranked.sort_values("abs_move", ascending=False)["label"].head(limit))


def write_outputs(out, snapshots, minutes, diagnostics, synthetic, truths=None):
    """Write available figures and the tables. Returns the max synthetic error, or None."""
    directory = Path(out)
    directory.mkdir(parents=True, exist_ok=True)

    path_minutes = minutes
    if not synthetic:
        labels = _path_labels(snapshots, diagnostics)
        path_minutes = minutes.loc[minutes["label"].isin(labels)]
        # Keep the chart in the same order as the ranking, not file order.
        path_minutes = path_minutes.copy()
        path_minutes["label"] = pd.Categorical(path_minutes["label"], categories=labels, ordered=True)
    path_file = directory / "repricing_paths.png"
    if not path_minutes.empty:
        paths = plot_repricing_paths(path_minutes, synthetic=synthetic)
        paths.savefig(path_file, dpi=150)
    else:
        path_file.unlink(missing_ok=True)
        print("Skipped repricing_paths.png: no fully identified afternoon at 16:00.")
    changes = plot_change_by_horizon(snapshots, synthetic=synthetic)
    changes.savefig(directory / "change_by_horizon.png", dpi=150)

    snapshots.to_csv(directory / "snapshot_changes.csv", index=False)
    minutes.to_csv(directory / "minute_paths.csv", index=False)
    diagnostics.to_csv(directory / "fit_diagnostics.csv", index=False)
    snapshot_change_table(snapshots).to_csv(directory / "change_by_horizon.csv", index=False)

    worst = None
    if truths is not None:
        _truth_rows(truths).to_csv(directory / "synthetic_truth.csv", index=False)
        worst = _max_abs_error(snapshots, truths)
    return worst


def main(argv=None):
    args = parse_args(argv)
    pd.set_option("display.width", 120)
    pd.set_option("display.float_format", lambda value: f"{value:.2f}")

    if args.real:
        try:
            snapshots, minutes, diagnostics = run_real()
        except FileNotFoundError as error:
            print(f"\n{error}\n", file=sys.stderr)
            return 2
        worst = write_outputs(args.out, snapshots, minutes, diagnostics, synthetic=False)
        print("REAL minute bars. Figures are market data, not the synthetic check.\n")
    else:
        snapshots, minutes, diagnostics, truths = run_synthetic()
        worst = write_outputs(args.out, snapshots, minutes, diagnostics, synthetic=True, truths=truths)
        print("SYNTHETIC minute bars. The jumps below were put in by the scenario, not observed.\n")
        print(f"Largest recovered-move error across snapshots: {worst:.4f} bp\n")

    view = snapshot_change_table(snapshots)
    print("Change in the implied cumulative path, 16:00 minus 13:55 Eastern, first six horizons:")
    print(view.to_string(index=False))
    print("\nFit diagnostics:")
    columns = ["label", "snapshot", "n_contracts", "n_meetings", "rmse_bps", "fully_identified", "converged"]
    print(diagnostics.loc[:, columns].to_string(index=False))
    print(f"\nWrote figures and tables under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
