import os
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from app.parser import STATION_TZ, OBS_ST_FIELDS

_BASE_URL = "https://swd.weatherflow.com/swd/rest"
_device_id_cache: Optional[int] = None


def _token() -> str:
    token = os.getenv("TEMPEST_PERSONAL_TOKEN")
    if not token:
        raise RuntimeError("TEMPEST_PERSONAL_TOKEN not set")
    return token


async def _resolve_device_id() -> int:
    global _device_id_cache
    if _device_id_cache is not None:
        return _device_id_cache

    env_id = os.getenv("TEMPEST_DEVICE_ID", "").strip()
    if env_id and env_id.isdigit():
        _device_id_cache = int(env_id)
        return _device_id_cache

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_BASE_URL}/stations", params={"token": _token()})
        resp.raise_for_status()
        stations = resp.json().get("stations", [])
        if not stations:
            raise RuntimeError("No stations found in Tempest account")
        for device in stations[0].get("devices", []):
            if device.get("device_type") == "ST":
                _device_id_cache = device["device_id"]
                return _device_id_cache
        raise RuntimeError("No Tempest (ST) device found in station")


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(STATION_TZ).isoformat()


def _parse_row(row: list) -> dict:
    obs = dict(zip(OBS_ST_FIELDS, row))
    obs["timestamp"] = _iso(obs["timestamp"])
    return obs


async def fetch_obs_history(minutes: int) -> List[dict]:
    device_id = await _resolve_device_id()
    now = int(datetime.now(timezone.utc).timestamp())
    params = {
        "token": _token(),
        "time_start": now - minutes * 60,
        "time_end": now,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_BASE_URL}/observations/device/{device_id}",
            params=params,
        )
        resp.raise_for_status()
    return [_parse_row(row) for row in resp.json().get("obs", []) if row and row[0]]
