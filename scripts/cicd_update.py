#!/usr/bin/env python3
"""CI/CD polling script for Tempest Weather FastAPI server."""

import logging
import os
import shutil
import sys
import subprocess
import time
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────
PROJECT_ROOT  = Path(__file__).resolve().parent.parent
LOG_DIR       = PROJECT_ROOT / "logs"
LOG_FILE      = LOG_DIR / "cicd.log"
FLAG_FILE     = PROJECT_ROOT / ".cicd_disabled"
LAST_RUN_FILE = LOG_DIR / ".last_run"
SERVICE_NAME  = "tempest-weather"
GIT           = "/usr/bin/git"
SYSTEMCTL     = "/usr/bin/systemctl"
PIPENV        = "/usr/local/bin/pipenv"  # adjust if `which pipenv` differs on the Pi
DEFAULT_INTERVAL = 15

logger = logging.getLogger(__name__)


# ── Logging ────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ── Interval gating ────────────────────────────────────────────────────────

def load_interval() -> int:
    """Read CICD_INTERVAL_MINUTES from .env; fall back to DEFAULT_INTERVAL."""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("CICD_INTERVAL_MINUTES="):
                try:
                    return int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
    return int(os.environ.get("CICD_INTERVAL_MINUTES", DEFAULT_INTERVAL))


def is_too_soon(interval_minutes: int) -> bool:
    """Return True if fewer than interval_minutes have elapsed since last run."""
    if not LAST_RUN_FILE.exists():
        return False
    try:
        last = float(LAST_RUN_FILE.read_text().strip())
        elapsed = (time.time() - last) / 60
        return elapsed < interval_minutes
    except (ValueError, OSError):
        return False


def record_run_time() -> None:
    LAST_RUN_FILE.write_text(str(time.time()))


# ── Git / deploy helpers ───────────────────────────────────────────────────

def _run(cmd: list, **kwargs) -> str:
    """Run a subprocess command; raise RuntimeError on non-zero exit."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(str(c) for c in cmd)!r} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def fetch_remote() -> None:
    _run([GIT, "fetch", "origin", "main"], cwd=PROJECT_ROOT)


def get_local_commit() -> str:
    return _run([GIT, "rev-parse", "HEAD"], cwd=PROJECT_ROOT)


def get_remote_commit() -> str:
    return _run([GIT, "rev-parse", "origin/main"], cwd=PROJECT_ROOT)


def git_pull() -> None:
    out = _run([GIT, "pull", "origin", "main"], cwd=PROJECT_ROOT)
    logger.info("git pull: %s", out)


def install_dependencies() -> None:
    pipenv_path = Path(PIPENV)
    if pipenv_path.exists():
        pipenv_bin = str(pipenv_path)
    else:
        pipenv_bin = shutil.which("pipenv")
    if not pipenv_bin:
        raise RuntimeError(f"pipenv not found at {PIPENV} and not on PATH")
    env = {**os.environ, "PIPENV_VENV_IN_PROJECT": "1"}
    out = _run([pipenv_bin, "install"], cwd=PROJECT_ROOT, env=env)
    logger.info("pipenv install: %s", out or "ok")


def restart_service() -> None:
    _run([SYSTEMCTL, "restart", SERVICE_NAME])
    logger.info("Service '%s' restarted.", SERVICE_NAME)


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    setup_logging()

    env = os.environ.get("ENVIRONMENT", "development")
    if env != "production":
        logger.info("ENVIRONMENT=%s — CI/CD automation disabled. Exiting.", env)
        sys.exit(0)

    if FLAG_FILE.exists():
        logger.info(".cicd_disabled flag present — automation paused. Exiting.")
        sys.exit(0)

    interval = load_interval()
    if is_too_soon(interval):
        sys.exit(0)  # silent — most cron fires hit this path
    record_run_time()
    logger.info("--- CI/CD poll starting (interval: %d min) ---", interval)

    try:
        fetch_remote()
        local  = get_local_commit()
        remote = get_remote_commit()

        if local == remote:
            logger.info("No new commits (HEAD=%s). Nothing to do.", local[:8])
            sys.exit(0)

        logger.info("New commits: local=%s → remote=%s", local[:8], remote[:8])
        git_pull()
        install_dependencies()
        restart_service()
        logger.info("Deployment complete.")

    except RuntimeError as exc:
        logger.error("Deployment aborted: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
