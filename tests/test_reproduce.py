"""Tests for the reproduction driver. No test runs a real step or touches the network."""

import pytest

import scripts.reproduce as reproduce
from scripts.reproduce import STEPS, STEP_NAMES, main, select_steps


def test_every_step_names_a_script_that_exists():
    for step in STEPS:
        path = reproduce.REPO_ROOT / (step.module.replace(".", "/") + ".py")
        assert path.exists(), f"{step.name}: {path} does not exist"


def test_step_names_are_unique():
    assert len(set(STEP_NAMES)) == len(STEP_NAMES)


def test_each_step_is_preceded_by_whatever_it_requires():
    """The order must be runnable: nothing needs a file that only a later step writes."""
    produced = set()
    for step in STEPS:
        missing = [path for path in step.requires if path not in produced]
        assert not missing, f"{step.name} needs {missing} before any step makes it"
        produced.update(step.produces)


def test_exactly_the_two_download_steps_use_databento():
    assert [step.name for step in STEPS if step.databento] == ["sofr_futures", "minute_bars"]


def test_select_steps_keeps_pipeline_order_whatever_order_names_are_given():
    chosen = select_steps(only="final_figures,rate_data")
    assert [step.name for step in chosen] == ["rate_data", "final_figures"]


def test_skip_removes_a_step():
    names = [step.name for step in select_steps(skip="minute_bars,intraday_study")]
    assert "minute_bars" not in names and "intraday_study" not in names
    assert "sofr_futures" in names


def test_an_unknown_step_name_is_reported_with_the_valid_ones(capsys):
    assert main(["--only", "nonsense"]) == 2
    err = capsys.readouterr().err
    assert "unknown step nonsense" in err and "sofr_futures" in err


def test_list_prints_the_plan_and_runs_nothing(capsys):
    calls = []
    assert main(["--list"], runner=lambda *a: calls.append(a) or 0) == 0
    out = capsys.readouterr().out
    assert calls == []
    assert "sofr_futures" in out and "intraday_study" in out
    assert out.count("*") >= 2


def test_dry_run_only_quotes_the_two_downloads(monkeypatch, capsys):
    monkeypatch.setattr(reproduce, "key_problem", lambda: None)
    commands = []
    assert main(["--dry-run"], runner=lambda command, root, destination: commands.append(command) or 0) == 0
    assert len(commands) == 2
    assert all(command[-1] == "--dry-run" for command in commands)
    assert [command[2] for command in commands] == ["scripts.fetch_sofr_futures", "scripts.fetch_intraday_sofr"]
    assert "nothing was downloaded" in capsys.readouterr().out


def test_a_missing_key_stops_before_anything_runs(monkeypatch, capsys):
    monkeypatch.setattr(reproduce, "key_problem", lambda: "No Databento API key found.")
    calls = []
    assert main(["--only", "sofr_futures"], runner=lambda *a: calls.append(a) or 0) == 2
    assert "No Databento API key found." in capsys.readouterr().err
    assert calls == []


def test_no_key_is_needed_when_no_step_downloads(monkeypatch, tmp_path):
    def fail():
        raise AssertionError("the key should not be checked")

    monkeypatch.setattr(reproduce, "key_problem", fail)
    assert main(["--only", "rate_data"], runner=lambda *a: 0, root=tmp_path) == 0


def test_a_failing_step_stops_the_run_and_names_the_command_to_repeat(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(reproduce, "key_problem", lambda: None)
    seen = []

    def runner(command, root, destination):
        seen.append(command[2])
        return 3 if command[2] == "scripts.fetch_rate_data" else 0

    # Put every required input in place so the run reaches the failing step.
    for step in STEPS:
        for path in step.requires:
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text("x")
    code = main(["--yes", "--only", "sofr_futures,rate_data,alignment"], runner=runner, root=tmp_path)
    assert code == 3
    assert seen == ["scripts.fetch_sofr_futures", "scripts.fetch_rate_data"]  # alignment never ran
    assert "python scripts/reproduce.py --only rate_data" in capsys.readouterr().err


def test_a_step_whose_inputs_are_absent_says_which(tmp_path, capsys):
    assert main(["--only", "alignment"], runner=lambda *a: 0, root=tmp_path) == 2
    err = capsys.readouterr().err
    assert "alignment needs" in err and "sofr_futures_settlements.parquet" in err


def test_yes_is_passed_only_to_the_futures_download():
    assert "--yes" in STEPS[0].command(assume_yes=True)
    assert "--yes" not in STEPS[0].command(assume_yes=False)
    assert all("--yes" not in step.command(assume_yes=True) for step in STEPS[1:])


def test_stdout_capture_writes_the_file(tmp_path):
    import sys

    destination = tmp_path / "out" / "captured.txt"
    code = reproduce.run_command([sys.executable, "-c", "print('hello'); print('world')"], tmp_path, destination)
    assert code == 0
    assert destination.read_text() == "hello\nworld\n"
