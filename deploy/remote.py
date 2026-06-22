"""SSH deploy for the remote notifier (profile C).

``tutor.py deploy --ssh user@host`` copies the package to the host, runs the
remote setup script (creates a venv, installs deps, installs a daily cron job
that pulls + imports + sends due reviews). Secrets are NOT copied — the script
prints the env vars you must set on the host.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from core import paths

REMOTE_DIR = "~/portuguese-brasil-tutor"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}")


def deploy_ssh(ssh: str, send_time: str = "09:00") -> None:
    src = str(paths.PKG_ROOT) + "/"
    excludes = ["--exclude", "data/tutor.db", "--exclude", "data/audio",
                "--exclude", "config/config.yaml", "--exclude", "__pycache__"]

    if shutil.which("rsync"):
        _run(["rsync", "-az", *excludes, src, f"{ssh}:{REMOTE_DIR}/"])
    else:
        _run(["ssh", ssh, f"mkdir -p {REMOTE_DIR}"])
        _run(["scp", "-r", src, f"{ssh}:{REMOTE_DIR}/"])

    setup = (paths.PKG_ROOT / "deploy" / "remote-setup.sh")
    _run(["scp", str(setup), f"{ssh}:{REMOTE_DIR}/deploy/remote-setup.sh"])
    _run(["ssh", ssh, f"bash {REMOTE_DIR}/deploy/remote-setup.sh '{send_time}'"])

    print("\nDeploy done. On the host, make sure these are set (e.g. in ~/.profile):")
    print("  export TELEGRAM_BOT_TOKEN=...   # from @BotFather")
    print("  (and, for git sync, a deploy key with read access to your repo)")
    print(f"The cron job runs daily at {send_time} and calls notifier/send_due.py.")
    sys.stdout.flush()
