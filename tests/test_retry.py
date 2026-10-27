"""Tests for retrying transient Databento failures. No test waits or opens a socket."""

import socket

import databento as db
import pandas as pd
import pytest
import requests

from fomc_intraday.fetch import build_requests, pull, request_kwargs
from sofr_data import databento_io
from sofr_data.retry import call_with_retries, is_transient


@pytest.fixture(autouse=True)
def no_network_no_sleep(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("retry tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    # If a test forgets to pass `sleep`, fail loudly instead of waiting.
    monkeypatch.setattr("sofr_data.retry.time.sleep", lambda seconds: pytest.fail(f"slept {seconds}s"))


def gateway_timeout():
    return db.BentoServerError(http_status=504, message="The remote gateway timed out.")


def bad_symbol():
    return db.BentoClientError(http_status=422, message="symbology_invalid_request")


def dropped_stream():
    return db.BentoError("Error streaming response: Response ended prematurely")


class Flaky:
    """Raises the given errors in order, then returns `value`."""

    def __init__(self, errors, value="ok"):
        self.errors = list(errors)
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.value


# --- which errors count as transient --------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [gateway_timeout(), dropped_stream(), requests.ConnectionError("reset"), requests.Timeout("slow")],
)
def test_transient_errors(error):
    assert is_transient(error)


@pytest.mark.parametrize(
    "error",
    [bad_symbol(), db.BentoError("some other databento problem"), ValueError("bad argument"), KeyError("x")],
)
def test_errors_that_are_not_transient(error):
    assert not is_transient(error)


# --- call_with_retries -----------------------------------------------------------------


def test_retries_a_transient_failure_and_waits_longer_each_time():
    flaky = Flaky([gateway_timeout(), dropped_stream()])
    waits = []
    assert call_with_retries(flaky, tries=5, base_wait=10, sleep=waits.append) == "ok"
    assert flaky.calls == 3
    assert waits == [10, 20]


def test_a_client_error_is_raised_immediately_without_waiting():
    flaky = Flaky([bad_symbol()])
    waits = []
    with pytest.raises(db.BentoClientError):
        call_with_retries(flaky, sleep=waits.append)
    assert flaky.calls == 1
    assert waits == []


def test_gives_up_after_the_last_attempt_and_raises_the_last_error():
    flaky = Flaky([gateway_timeout()] * 10)
    waits = []
    with pytest.raises(db.BentoServerError):
        call_with_retries(flaky, tries=3, base_wait=1, sleep=waits.append)
    assert flaky.calls == 3
    assert waits == [1, 2]  # no pause after the final failure


def test_a_non_databento_error_is_not_swallowed():
    flaky = Flaky([ValueError("bad")])
    with pytest.raises(ValueError, match="bad"):
        call_with_retries(flaky, sleep=lambda _seconds: None)
    assert flaky.calls == 1


def test_tries_must_be_positive():
    with pytest.raises(ValueError, match="at least 1"):
        call_with_retries(lambda: 1, tries=0)


# --- the two pulls that use it ---------------------------------------------------------


def test_the_futures_cache_retries_a_download(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr("sofr_data.retry.time.sleep", waits.append)
    flaky = Flaky([gateway_timeout()], value=pd.DataFrame({"a": [1]}))
    frame = databento_io._cached_fetch(tmp_path / "chunk.parquet", flaky, refresh=False)
    assert list(frame["a"]) == [1]
    assert flaky.calls == 2
    assert waits == [10.0]
    # The retried download was cached, so the next call does not touch the network.
    again = databento_io._cached_fetch(tmp_path / "chunk.parquet", Flaky([AssertionError("refetched")]), refresh=False)
    assert list(again["a"]) == [1]


def test_the_intraday_pull_resumes_after_a_dropped_stream(tmp_path, monkeypatch):
    monkeypatch.setattr("sofr_data.retry.time.sleep", lambda _seconds: None)
    requests_ = build_requests(["2024-06-12"])

    class Store:
        def to_df(self):
            return pd.DataFrame()

    class Timeseries:
        def __init__(self):
            self.calls = []

        def get_range(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise dropped_stream()
            return Store()

    class Meta:
        def get_cost(self, **_kwargs):
            return 0.0

    class Client:
        metadata = Meta()
        timeseries = Timeseries()

    client = Client()
    bars, _quote, _total = pull(
        client, requests_, raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed",
    )
    assert bars is not None
    assert client.timeseries.calls == [request_kwargs(requests_[0])] * 2
    assert (tmp_path / "raw" / "2024-06-12.parquet").exists()


def test_the_cost_quote_retries_a_read_timeout(monkeypatch):
    """A timeout on the cost quote used to abort the whole run before anything downloaded."""
    from fomc_intraday.fetch import quote_cost

    waits = []
    monkeypatch.setattr("sofr_data.retry.time.sleep", waits.append)
    calls = []

    class Meta:
        def get_cost(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=100)")
            return 0.0

    class Client:
        metadata = Meta()

    quote = quote_cost(Client(), build_requests(["2024-06-12"]))
    assert len(calls) == 2
    assert waits == [10.0]
    assert float(quote["cost_usd"].iloc[0]) == 0.0
