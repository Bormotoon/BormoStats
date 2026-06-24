"""Typed wrappers around Celery helpers used by worker tasks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast

from celery import shared_task as celery_shared_task

P = ParamSpec("P")
R = TypeVar("R")


def shared_task(*task_args: Any, **task_kwargs: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
    decorator = celery_shared_task(*task_args, **task_kwargs)
    return cast(Callable[[Callable[P, R]], Callable[P, R]], decorator)
