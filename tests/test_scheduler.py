"""Unit tests for the Ebbinghaus scheduler — pure date arithmetic."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import scheduler  # noqa: E402


def test_default_intervals():
    start = date(2026, 1, 1)
    pairs = scheduler.schedule_dates(start)
    assert pairs == [
        (2, date(2026, 1, 3)),
        (7, date(2026, 1, 8)),
        (30, date(2026, 1, 31)),
    ]


def test_custom_intervals():
    start = date(2026, 6, 22)
    pairs = scheduler.schedule_dates(start, [1, 3])
    assert pairs == [(1, date(2026, 6, 23)), (3, date(2026, 6, 25))]


def test_is_due():
    assert scheduler.is_due(date(2026, 1, 1), on=date(2026, 1, 2))
    assert scheduler.is_due(date(2026, 1, 2), on=date(2026, 1, 2))
    assert not scheduler.is_due(date(2026, 1, 3), on=date(2026, 1, 2))


def test_fail_restarts_chain():
    assert scheduler.next_interval_after_fail([2, 7, 30]) == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all scheduler tests passed")
