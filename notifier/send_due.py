#!/usr/bin/env python3
"""Cron entry point for the outbound notifier (profiles B and C).

Does exactly one job, on a schedule: optionally pull the latest synced words
(git mode), import them, then deliver today's due reviews to Telegram as a
post = word card + voice (by ``file_id``). No interactive bot, no long-running
process — cron/launchd invokes this once and it exits.

    python notifier/send_due.py            # send today's due reviews
    python notifier/send_due.py --on DATE  # simulate a given day (testing)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config, db, paths, sync  # noqa: E402


def _git_pull() -> None:
    repo = paths.PKG_ROOT
    if not (repo / ".git").exists():
        return
    proc = subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[notifier] git pull failed: {proc.stderr.strip()}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--on", help="date YYYY-MM-DD (default today)")
    parser.add_argument("--no-pull", action="store_true")
    args = parser.parse_args(argv)

    db.init()
    if config.sync_mode() == "git" and not args.no_pull:
        _git_pull()
        sync.import_bundle()

    # Reuse the CLI's delivery logic so behaviour is identical.
    from cli.tutor import cmd_send_due

    class _A:
        on = args.on
    cmd_send_due(_A())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
