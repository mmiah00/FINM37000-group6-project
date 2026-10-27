"""Retry Databento requests that fail for transient reasons.

Databento's historical API sometimes answers with a 5xx (most often
``504 The remote gateway timed out``) or drops a streamed response
(``Response ended prematurely``). Both are worth a retry. A 4xx is the
caller's mistake, such as an unknown symbol or a bad key, and retrying it
only delays the error, so it is raised straight away.

Every pull in this project is cached per request, so a retried or resumed
pull never downloads the same chunk twice.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

import databento as db
import requests

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_TRIES = 5
DEFAULT_BASE_WAIT_SECONDS = 10.0


def is_transient(error: BaseException) -> bool:
    """True for failures that a later attempt can reasonably be expected to fix."""
    if isinstance(error, db.BentoClientError):
        return False
    if isinstance(error, db.BentoServerError):
        return True
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    # A dropped stream surfaces as a bare BentoError rather than a BentoServerError.
    return isinstance(error, db.BentoError) and "streaming response" in str(error).lower()


def call_with_retries(
    fetch: Callable[[], T],
    label: str = "request",
    tries: int = DEFAULT_TRIES,
    base_wait: float = DEFAULT_BASE_WAIT_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """Call ``fetch()``, retrying transient failures with a doubling pause.

    Args:
        fetch: Zero-argument callable that makes the request.
        label: Name used in the log line when a retry happens.
        tries: Total attempts, including the first.
        base_wait: Seconds to wait after the first failure. Doubles each time.
        sleep: Replaces ``time.sleep``; tests pass a recorder so they do not wait.

    Returns:
        Whatever ``fetch`` returns.

    Raises:
        The last error if every attempt fails, or immediately for an error that
        is not transient.
    """
    if tries < 1:
        msg = "tries must be at least 1"
        raise ValueError(msg)
    pause = time.sleep if sleep is None else sleep
    for attempt in range(tries):
        try:
            return fetch()
        except Exception as error:
            last_attempt = attempt == tries - 1
            if last_attempt or not is_transient(error):
                raise
            wait = base_wait * 2**attempt
            logger.warning(
                "%s failed (%s); retrying in %.0fs (attempt %d of %d)",
                label, error, wait, attempt + 2, tries,
            )
            pause(wait)
    msg = "unreachable"  # the loop either returns or raises
    raise RuntimeError(msg)
