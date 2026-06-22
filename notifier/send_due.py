#!/usr/bin/env python3
"""Cron entry point for the outbound notifier (profiles B, C, and D).

Thin wrapper over ``tutor.py notify``: optionally pull + import the latest
synced words (git mode), then deliver today's due reviews to Telegram as a
post = word card + voice (by ``file_id``). No interactive bot, no long-running
process — cron/launchd (or a scheduled agent) invokes this once and it exits.

    python notifier/send_due.py            # send today's due reviews
    python notifier/send_due.py --on DATE  # simulate a given day (testing)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.tutor import cmd_notify  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--on", help="date YYYY-MM-DD (default today)")
    parser.add_argument("--no-pull", action="store_true")
    cmd_notify(parser.parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
