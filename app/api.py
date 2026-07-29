import asyncio
import json
import logging
import os
import resource
import socket
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CICD_SCRIPT = _PROJECT_ROOT / "scripts" / "cicd_update.py"
_LAST_RUN_FILE = _PROJECT_ROOT / "logs" / ".last_run"
_SYSTEMCTL = "/usr/bin/systemctl"
_SERVICE = "tempest-weather"
_REBOOT = "/usr/sbin/reboot"
_DEVICE_TREE_MODEL = Path("/proc/device-tree/model")
_SSE_HEARTBEAT_SECONDS = 15
_WATCHDOG_PING_SECONDS = 15

from app.cloud import fetch_forecast, fetch_obs_history
from app.display import start_display
from app.listener import (
    start_listener,
    get_state,
    subscribe,
    unsubscribe,
    get_subscriber_counts,
    listener_thread_alive,
)


def _sd_notify(state: str) -> None:
    """Send a status update to systemd via the sd_notify protocol.

    No-op if NOTIFY_SOCKET isn't set (not running under systemd, e.g. dev/macOS).
    Implemented with a raw AF_UNIX datagram socket so no extra dependency
    (e.g. python-systemd) is needed.
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.sendto(state.encode(), addr)
    except OSError:
        logging.exception("sd_notify failed")
    finally:
        sock.close()


async def _watchdog_loop() -> None:
    """Ping systemd's watchdog only while the UDP listener thread is alive.

    If the listener thread has silently died, this stops petting the
    watchdog so systemd (WatchdogSec=) kills and restarts the service
    instead of the app running with no live weather data forever.
    """
    while True:
        await asyncio.sleep(_WATCHDOG_PING_SECONDS)
        if listener_thread_alive():
            _sd_notify("WATCHDOG=1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_listener()
    try:
        start_display()
    except Exception:
        logging.exception("LCD display failed to start; continuing without it")
    _sd_notify("READY=1")
    watchdog_task = asyncio.create_task(_watchdog_loop())
    yield
    watchdog_task.cancel()


app = FastAPI(title="Tempest Weather API", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/weather/latest")
async def weather_latest() -> dict:
    try:
        data = get_state("obs_st")
        if data is None:
            raise HTTPException(status_code=503, detail="No obs_st received yet")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/wind")
async def weather_wind() -> dict:
    try:
        data = get_state("rapid_wind")
        if data is None:
            raise HTTPException(status_code=503, detail="No rapid_wind received yet")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/status")
async def weather_status() -> dict:
    try:
        return {
            "hub": get_state("hub_status"),
            "device": get_state("device_status"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/history")
async def weather_history(minutes: int = Query(default=60, ge=1, le=1440)) -> dict:
    try:
        observations = await fetch_obs_history(minutes)
        return {"minutes": minutes, "count": len(observations), "observations": observations}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/forecast/daily")
async def weather_forecast_daily() -> dict:
    try:
        entries = await fetch_forecast("daily")
        return {"count": len(entries), "forecast": entries}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/forecast/hourly")
async def weather_forecast_hourly() -> dict:
    try:
        entries = await fetch_forecast("hourly")
        return {"count": len(entries), "forecast": entries}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _sse_generator(msg_type: str, request: Request) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()
    queue = subscribe(msg_type, loop)
    try:
        while True:
            try:
                parsed = await asyncio.wait_for(queue.get(), timeout=_SSE_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                # No message in a while — actively check for a half-open
                # connection (client gone dark without a clean TCP close)
                # instead of relying solely on ASGI disconnect detection,
                # which can miss that case and leak the subscriber forever.
                if await request.is_disconnected():
                    break
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(parsed)}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        unsubscribe(msg_type, loop, queue)


@app.get("/weather/stream")
async def weather_stream(request: Request) -> StreamingResponse:
    return StreamingResponse(_sse_generator("*", request), media_type="text/event-stream")


@app.get("/weather/stream/obs")
async def weather_stream_obs(request: Request) -> StreamingResponse:
    return StreamingResponse(_sse_generator("obs_st", request), media_type="text/event-stream")


@app.get("/weather/stream/wind")
async def weather_stream_wind(request: Request) -> StreamingResponse:
    return StreamingResponse(_sse_generator("rapid_wind", request), media_type="text/event-stream")


@app.get("/admin/metrics")
async def admin_metrics() -> dict:
    """Lightweight process/app metrics for external monitoring."""
    return {
        "subscribers": get_subscriber_counts(),
        "threads": threading.active_count(),
        "listener_thread_alive": listener_thread_alive(),
        "rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


@app.post("/admin/restart")
async def admin_restart() -> dict:
    """Restart the systemd service. Response is sent before the process exits."""
    async def _do() -> None:
        await asyncio.sleep(1)
        subprocess.Popen(["sudo", _SYSTEMCTL, "restart", _SERVICE])

    asyncio.create_task(_do())
    return {"status": "restarting"}


def _is_raspberry_pi() -> bool:
    try:
        return "raspberry pi" in _DEVICE_TREE_MODEL.read_text(errors="ignore").lower()
    except OSError:
        return False


@app.post("/admin/reboot")
async def admin_reboot() -> dict:
    """Reboot the host. Only permitted when running on a Raspberry Pi."""
    if not _is_raspberry_pi():
        raise HTTPException(status_code=400, detail="Not running on a Raspberry Pi")

    async def _do() -> None:
        await asyncio.sleep(1)
        subprocess.Popen(["sudo", _REBOOT])

    asyncio.create_task(_do())
    return {"status": "rebooting"}


@app.post("/admin/cicd")
async def admin_cicd() -> dict:
    """Force a CI/CD deploy check, bypassing the interval gate."""
    async def _do() -> None:
        await asyncio.sleep(0.5)
        _LAST_RUN_FILE.unlink(missing_ok=True)
        env = {**os.environ, "ENVIRONMENT": "production"}
        subprocess.Popen(["/usr/bin/python3", str(_CICD_SCRIPT)], env=env)

    asyncio.create_task(_do())
    return {"status": "triggered"}
