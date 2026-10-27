#!/usr/bin/env python3
"""Reproduce the project's results from Databento and public data, in order.

Run from the repository root, after `pip install -r requirements.txt` and saving the
Databento API key in `~/.databento_api_key` (see README.md, "Reproduce the results").

    python scripts/reproduce.py --list        # the plan, nothing runs
    python scripts/reproduce.py --dry-run     # quote the Databento cost, download nothing
    python scripts/reproduce.py --yes         # run everything

Each step is one of the scripts the README describes, run as `python -m scripts.<name>`.
The steps run in dependency order and the run stops at the first failure, naming the
command to repeat. Downloads are cached per request, so repeating a run, or resuming
after a Databento timeout, does not download the same data twice.

Two steps use CME data from Databento (`sofr_futures`, `minute_bars`). The rest use the
files those produce plus public NY Fed and FRED data, which need no key.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

FUTURES = "data/processed/sofr_futures_settlements.parquet"
SOFR = "data/processed/sofr_daily.csv"
DECISIONS = "data/processed/fomc_meetings.csv"
VIZ = "data/processed/visualizations"
MINUTE_BARS = "data/processed/sofr_intraday_ohlcv_1m.parquet"
RESULTS = "reports/results"


@dataclass(frozen=True)
class Step:
    """One script in the pipeline."""

    name: str
    module: str
    args: tuple = ()
    requires: tuple = ()
    produces: tuple = ()
    databento: bool = False
    stdout_to: str | None = None
    description: str = ""

    def command(self, assume_yes=False, dry_run=False):
        """The argv that runs this step."""
        extra = list(self.args)
        if self.name == "sofr_futures" and assume_yes:
            extra.append("--yes")
        if dry_run:
            extra.append("--dry-run")
        return [sys.executable, "-m", self.module, *extra]


STEPS = (
    Step(
        "sofr_futures", "scripts.fetch_sofr_futures",
        produces=(FUTURES, "data/processed/sofr_futures_contracts.parquet", "reports/data_quality_sofr_futures.md"),
        databento=True,
        description="SR1 and SR3 settlement prices from Databento (GLBX.MDP3), cleaned, with a data quality report",
    ),
    Step(
        "rate_data", "scripts.fetch_rate_data",
        produces=(SOFR, DECISIONS, "data/processed/effr_daily.csv"),
        description="Daily SOFR and EFFR (NY Fed) and the FOMC decisions and target range (FRED)",
    ),
    Step(
        "alignment", "scripts.align_fomc_futures",
        requires=(FUTURES, DECISIONS), produces=("data/processed/fomc_futures_alignment.csv",),
        description="Match every futures settlement to the FOMC meetings it can still forecast",
    ),
    Step(
        "historical_forecasts", "scripts.prepare_historical_forecasts",
        requires=(FUTURES, SOFR, DECISIONS),
        produces=(f"{VIZ}/implied_forecasts.csv", f"{VIZ}/estimation_diagnostics.csv", f"{VIZ}/basis_by_date.csv"),
        description="Fit the market-implied Fed path on the first trading day of each month",
    ),
    Step(
        "forecast_errors", "scripts.prepare_visualization_inputs",
        args=("--implied", f"{VIZ}/implied_forecasts.csv", "--decisions", DECISIONS, "--output-dir", VIZ),
        requires=(f"{VIZ}/implied_forecasts.csv", DECISIONS),
        produces=(f"{VIZ}/forecast_errors.csv", f"{VIZ}/accuracy_by_horizon.csv"),
        description="Score the implied paths against the realized FOMC decisions, by horizon",
    ),
    Step(
        "curve_comparison", "scripts.prepare_historical_comparison",
        requires=(FUTURES, SOFR, DECISIONS, f"{VIZ}/forecast_errors.csv"),
        produces=(f"{VIZ}/model_comparison.csv",),
        description="Score the FOMC-aware model against a simplified smooth SOFR curve",
    ),
    Step(
        "final_figures", "scripts.generate_final_figures",
        args=("--errors", f"{VIZ}/forecast_errors.csv", "--decisions", DECISIONS,
              "--comparison", f"{VIZ}/model_comparison.csv", "--obs-date", "2022-04-01", "--output-dir", RESULTS),
        requires=(f"{VIZ}/forecast_errors.csv", DECISIONS, f"{VIZ}/model_comparison.csv"),
        produces=(f"{RESULTS}/01_fed_paths.png", f"{RESULTS}/03_model_comparison.png"),
        description="The four final figures and their summary tables",
    ),
    Step(
        "daily_sr1_comparison", "scripts.run_curve_compare_real",
        requires=(FUTURES, SOFR, DECISIONS), produces=(f"{RESULTS}/sr1_curve_comparison.txt",),
        stdout_to=f"{RESULTS}/sr1_curve_comparison.txt",
        description="The same two methods scored on every trading day, SR1 only, next meeting",
    ),
    Step(
        "minute_bars", "scripts.fetch_intraday_sofr",
        produces=(MINUTE_BARS,), databento=True,
        description="One-minute SR1 and SR3 bars from Databento around each FOMC statement",
    ),
    Step(
        "intraday_study", "scripts.run_intraday_demo",
        args=("--real", "--out", "reports/intraday/real"),
        requires=(MINUTE_BARS, SOFR, DECISIONS),
        produces=("reports/intraday/real/announcement_summary.csv", "reports/intraday/real/repricing_speed.png"),
        description="The intraday FOMC event study: implied path before and after each statement",
    ),
)

STEP_NAMES = tuple(step.name for step in STEPS)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="Print the steps and exit.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Quote the Databento cost of the two downloads and stop. Nothing is downloaded or analysed.")
    parser.add_argument("--yes", action="store_true", help="Do not ask before the SOFR futures download.")
    parser.add_argument("--only", default="", help="Comma-separated step names to run (default: all).")
    parser.add_argument("--skip", default="", help="Comma-separated step names to leave out.")
    return parser.parse_args(argv)


def _names(text):
    return [name.strip() for name in text.split(",") if name.strip()]


def select_steps(only="", skip=""):
    """The steps to run, in pipeline order. Unknown names raise ValueError."""
    chosen, left_out = _names(only), _names(skip)
    unknown = [name for name in (*chosen, *left_out) if name not in STEP_NAMES]
    if unknown:
        raise ValueError(f"unknown step {', '.join(unknown)}; choose from {', '.join(STEP_NAMES)}")
    return [step for step in STEPS if (not chosen or step.name in chosen) and step.name not in left_out]


def print_plan(steps):
    print("Steps, in order (* = downloads CME data from Databento):\n")
    for number, step in enumerate(steps, start=1):
        marker = "*" if step.databento else " "
        print(f" {number:2d}. {marker} {step.name:22s} {step.description}")
    print("\nA step is skipped with --skip NAME, or the run limited with --only NAME[,NAME].")


def key_problem():
    """None if a Databento key is available, otherwise the message that says how to add one."""
    from sofr_data import config

    try:
        config.resolve_api_key()
    except FileNotFoundError as error:
        return str(error)
    return None


def _run(step, command, runner, root):
    """Run one command, copying its output to the screen and, if asked, to a file."""
    destination = root / step.stdout_to if step.stdout_to else None
    return runner(command, root, destination)


def run_command(command, root, destination):
    """Run `command` from `root` and return its exit code.

    With no `destination` the command talks to the terminal directly, so a prompt such as the
    Databento cost confirmation is seen and answered. With one, output is copied to the screen
    and to that file as it arrives.
    """
    if destination is None:
        return subprocess.run(command, cwd=root).returncode
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    sink = open(destination, "w") if destination is not None else None
    try:
        for line in process.stdout:
            print(line, end="", flush=True)
            if sink is not None:
                sink.write(line)
    finally:
        if sink is not None:
            sink.close()
    return process.wait()


def missing_inputs(step, root):
    return [path for path in step.requires if not (root / path).exists()]


def main(argv=None, runner=run_command, root=REPO_ROOT):
    args = parse_args(argv)
    try:
        steps = select_steps(args.only, args.skip)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    if args.list:
        print_plan(steps)
        return 0

    if args.dry_run:
        steps = [step for step in steps if step.databento]
    if any(step.databento for step in steps):
        problem = key_problem()
        if problem is not None:
            print(f"\n{problem}\n", file=sys.stderr)
            return 2

    for number, step in enumerate(steps, start=1):
        absent = missing_inputs(step, root)
        if absent and not args.dry_run:
            print(
                f"\nStep {step.name} needs {', '.join(absent)}, which no earlier step in this run produced.\n"
                f"Run the earlier steps first (python scripts/reproduce.py --list shows the order).",
                file=sys.stderr,
            )
            return 2
        command = step.command(assume_yes=args.yes, dry_run=args.dry_run)
        print(f"\n[{number}/{len(steps)}] {step.name}: {step.description}\n    $ {' '.join(command[1:])}", flush=True)
        started = time.time()
        code = _run(step, command, runner, root)
        if code != 0:
            print(f"\nStep {step.name} failed with exit code {code}. Repeat just this step with:\n"
                  f"    python scripts/reproduce.py --only {step.name}"
                  f"{' --yes' if step.name == 'sofr_futures' else ''}", file=sys.stderr)
            return code
        print(f"    done in {time.time() - started:.0f}s")

    print("\nDry run only: nothing was downloaded." if args.dry_run else "\nAll steps finished. Results are under reports/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
