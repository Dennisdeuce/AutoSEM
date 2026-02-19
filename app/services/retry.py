"""
Shared retry utility — exponential backoff decorator.
Use @with_retry() on any function that makes external API calls.
"""

import time
import logging
import functools
from typing import Tuple, Type

logger = logging.getLogger("autosem.retry")

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 1.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

# Include httpx/requests exceptions if available
try:
    import requests.exceptions
    DEFAULT_EXCEPTIONS = DEFAULT_EXCEPTIONS + (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.HTTPError,
    )
except ImportError:
    pass

try:
    import httpx
    DEFAULT_EXCEPTIONS = DEFAULT_EXCEPTIONS + (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.HTTPStatusError,
    )
except ImportError:
    pass


def with_retry(
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    exceptions: Tuple[Type[Exception], ...] = DEFAULT_EXCEPTIONS,
):
    """Decorator: retry a function with exponential backoff.

    Args:
        retries: Max number of retry attempts (default 3).
        backoff: Initial wait in seconds (default 1.0).
        backoff_factor: Multiplier per attempt (default 2.0).
        exceptions: Tuple of exception types to retry on.

    Usage:
        @with_retry()
        def call_api():
            ...

        @with_retry(retries=5, backoff=0.5)
        def flaky_call():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            wait = backoff

            for attempt in range(1, retries + 2):  # +1 for initial attempt
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt > retries:
                        break
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{retries} failed: {e}. "
                        f"Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                    wait *= backoff_factor

            logger.error(f"{func.__name__} failed after {retries} retries: {last_exception}")
            raise last_exception

        return wrapper
    return decorator
