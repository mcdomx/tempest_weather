#!/usr/bin/env python3
"""Standalone resource-snapshot script for diagnosing full-system freezes.

Runs independently of the FastAPI process (fired from cron every couple of
minutes) so it keeps recording system state even if the app itself is wedged.
Appends one line per snapshot to a size-capped, rotating log. After a freeze
and a hard power-cycle, the minutes leading up to the gap in this log are the
evidence: climbing RSS/FD counts point at a leak, climbing swap + load average
point at OOM thrashing, near-full disk points at log growth, and a clean stop
with nothing anomalous points at a hardware/kernel-level wedge instead.

Stdlib only, matching scripts/cicd_update.py's convention.
"""

import json
import logging
import logging.handlers
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "resource_monitor.log"
SERVICE_NAME = "tempest-weather"
METRICS_URL = "http://127.0.0.1:8766/admin/metrics"
METRICS_TIMEOUT_SECONDS = 3

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5_000_000, backupCount=3
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def read_loadavg() -> str:
    one, five, fifteen = os.getloadavg()
    return f"{one:.2f},{five:.2f},{fifteen:.2f}"


def read_meminfo() -> dict:
    fields = {}
    text = Path("/proc/meminfo").read_text()
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            fields[key] = int(rest.strip().split()[0])  # kB
    return fields


def read_disk_usage() -> dict:
    import shutil
    total, used, free = shutil.disk_usage("/")
    return {"total_mb": total // 1_000_000, "used_mb": used // 1_000_000, "free_mb": free // 1_000_000}


def get_service_pid() -> str:
    try:
        out = subprocess.run(
            ["systemctl", "show", "-p", "MainPID", "--value", SERVICE_NAME],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def read_process_stats(pid: str) -> dict:
    if not pid or pid == "0":
        return {"rss_kb": None, "fd_count": None}
    proc_dir = Path(f"/proc/{pid}")
    rss_kb = None
    try:
        for line in (proc_dir / "status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
                break
    except (OSError, ValueError):
        pass
    try:
        fd_count = len(os.listdir(proc_dir / "fd"))
    except OSError:
        fd_count = None
    return {"rss_kb": rss_kb, "fd_count": fd_count}


def fetch_app_metrics() -> dict:
    try:
        with urllib.request.urlopen(METRICS_URL, timeout=METRICS_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"error": str(exc)}


def main() -> None:
    setup_logging()
    pid = get_service_pid()
    snapshot = {
        "loadavg": read_loadavg(),
        "mem": read_meminfo(),
        "disk": read_disk_usage(),
        "proc": read_process_stats(pid),
        "app": fetch_app_metrics(),
    }
    logger.info(json.dumps(snapshot))


if __name__ == "__main__":
    main()
