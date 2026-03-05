"""Retry decorators and policies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

F = TypeVar("F", bound=Callable[..., Any])


def with_retry() -> Callable[[F], F]:
    return retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
