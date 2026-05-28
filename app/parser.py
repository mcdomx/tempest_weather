import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

UDP_PORT: int = 50222
BUFFER_SIZE: int = 4096

STATION_TZ = ZoneInfo(os.getenv("STATION_TIMEZONE", "America/New_York"))

OBS_ST_FIELDS: list = [
    "timestamp",
    "wind_lull_m_s",
    "wind_avg_m_s",
    "wind_gust_m_s",
    "wind_direction_deg",
    "wind_sample_interval_s",
    "pressure_mb",
    "air_temp_c",
    "relative_humidity_pct",
    "illuminance_lux",
    "uv_index",
    "solar_radiation_w_m2",
    "rain_prev_min_mm",
    "precip_type",
    "lightning_avg_dist_km",
    "lightning_count",
    "battery_volts",
    "report_interval_min",
]


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(STATION_TZ).isoformat()


def parse_obs_st(msg: dict) -> Optional[dict]:
    obs = msg.get("obs")
    if not obs:
        return None
    row = dict(zip(OBS_ST_FIELDS, obs[0]))
    row["timestamp"] = _iso(row["timestamp"])
    row["serial_number"] = msg.get("serial_number")
    return row


def parse_rapid_wind(msg: dict) -> Optional[dict]:
    ob = msg.get("ob")
    if not ob:
        return None
    return {
        "timestamp": _iso(ob[0]),
        "wind_speed_m_s": ob[1],
        "wind_speed_mph": round(ob[1] * 2.23694, 2),
        "wind_direction_deg": ob[2],
        "serial_number": msg.get("serial_number"),
    }


def parse_hub_status(msg: dict) -> dict:
    return {
        "serial_number": msg.get("serial_number"),
        "firmware_revision": msg.get("firmware_revision"),
        "uptime": msg.get("uptime"),
        "rssi": msg.get("rssi"),
        "timestamp": _iso(msg["timestamp"]),
    }


def parse_device_status(msg: dict) -> dict:
    return {
        "serial_number": msg.get("serial_number"),
        "firmware_revision": msg.get("firmware_revision"),
        "uptime": msg.get("uptime"),
        "voltage": msg.get("voltage"),
        "rssi": msg.get("rssi"),
        "sensor_status": msg.get("sensor_status"),
        "timestamp": _iso(msg["timestamp"]),
    }


def parse_evt_precip(msg: dict) -> dict:
    evt = msg.get("evt", [None])
    ts = evt[0] if evt else None
    return {
        "serial_number": msg.get("serial_number"),
        "timestamp": _iso(ts) if ts else None,
    }


def parse_evt_strike(msg: dict) -> Optional[dict]:
    evt = msg.get("evt")
    if not evt:
        return None
    return {
        "timestamp": _iso(evt[0]),
        "distance_km": evt[1],
        "energy": evt[2],
        "serial_number": msg.get("serial_number"),
    }


_PARSERS = {
    "obs_st": parse_obs_st,
    "rapid_wind": parse_rapid_wind,
    "hub_status": parse_hub_status,
    "device_status": parse_device_status,
    "evt_precip": parse_evt_precip,
    "evt_strike": parse_evt_strike,
}


def parse_message(msg: dict) -> Optional[dict]:
    msg_type = msg.get("type")
    parser = _PARSERS.get(msg_type)
    if parser is None:
        return None
    data = parser(msg)
    if data is None:
        return None
    return {"type": msg_type, "data": data}
