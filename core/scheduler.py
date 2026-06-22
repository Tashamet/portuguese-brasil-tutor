"""Ebbinghaus spaced-repetition scheduling.

Pure date arithmetic so it is trivially unit-testable. The persistence side
(creating ``reviews`` rows, querying what's due) lives in :mod:`core.db`; this
module owns the *policy* — which intervals, computed how.
"""
from __future__ import annotations

from datetime import date, timedelta

DEFAULT_INTERVALS = [2, 7, 30]


def schedule_dates(start: date, intervals: list[int] | None = None) -> list[tuple[int, date]]:
    """Return ``(interval_day, due_date)`` pairs for a word learned on ``start``."""
    intervals = intervals or DEFAULT_INTERVALS
    return [(int(n), start + timedelta(days=int(n))) for n in intervals]


def is_due(due_date: date, on: date | None = None) -> bool:
    return due_date <= (on or date.today())


def next_interval_after_fail(intervals: list[int] | None = None) -> int:
    """SM-2-style hook: on a failed review, restart the chain from the first
    interval. Kept simple and explicit so it can be swapped for a real SM-2
    ease-factor scheme later without touching callers."""
    intervals = intervals or DEFAULT_INTERVALS
    return intervals[0]
