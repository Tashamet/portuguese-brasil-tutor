"""SSH deploy for the remote notifier (24/7 on a host you control).

``tutor.py deploy --ssh user@host`` rsyncs the **code** to the host and runs the
remote setup script, which clones the **student's private data repo**, installs
deps, and installs a daily cron that runs ``tutor.py notify`` against that data
dir. Code and data stay separate, mirroring the local layout.

The notifier never generates audio (it reuses Telegram ``file_id``), so the host
needs only PyYAML + requests — no Piper.

Secrets are NOT copied — the script prints the env var you must set on the host.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

from core import paths

REMOTE_CODE = "~/ptb-tutor-code"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}")


def deploy_ssh(ssh: str, send_time: str = "09:00", data_repo: str = "") -> None:
    if not data_repo:
        raise SystemExit(
            "Remote deploy needs your private DATA repo URL — push the student's "
            "data dir to a private git repo, set sync.git.repo_url (or pass "
            "--data-repo), then retry."
        )
    src = str(paths.PKG_ROOT) + "/"
    excludes = ["--exclude", ".git", "--exclude", ".venv", "--exclude", "__pycache__"]

    if shutil.which("rsync"):
        _run(["rsync", "-az", *excludes, src, f"{ssh}:{REMOTE_CODE}/"])
    else:
        _run(["ssh", ssh, f"mkdir -p {REMOTE_CODE}"])
        _run(["scp", "-r", src, f"{ssh}:{REMOTE_CODE}/"])

    _run(["ssh", ssh,
          f"bash {REMOTE_CODE}/deploy/remote-setup.sh '{send_time}' '{data_repo}'"])

    print("\nDeploy done. On the host:")
    print("  1) set the bot token:  echo 'export TELEGRAM_BOT_TOKEN=...' >> ~/.ptb_env")
    print("  2) ensure the host can read your private data repo (add a deploy key)")
    print(f"The cron runs daily at {send_time}: it pulls the data repo and sends "
          "due reviews + the lesson nudge.")
    sys.stdout.flush()
