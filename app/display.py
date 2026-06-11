"""Optional I2C 1602 LCD status display.

Drives a Hosyond (PCF8574-backpack) 16x2 character LCD attached to a Raspberry
Pi, showing service health and live weather metrics. The display is entirely
optional: if the LCD library is missing, the hardware is absent, or the I2C bus
errors at runtime, the application keeps running normally — every hardware path
is guarded and never raises into the caller.

Fixed 16x2 layout::

    72F 55% 9mph NW      temp(F)  humidity(%)  wind(mph)  wind dir(compass)
    UV3 12klx R:N OK     UV index  lux  rain indicator  health(OK/--)
"""

import json
import logging
import os
import threading
import time
import urllib.request
from typing import Optional, Tuple

from app.listener import get_state

try:
    from RPLCD.i2c import CharLCD

    _LIB_AVAILABLE = True
except ImportError:
    CharLCD = None  # type: ignore[assignment, misc]
    _LIB_AVAILABLE = False

logger = logging.getLogger(__name__)

LCD_COLS: int = 16
LCD_ROWS: int = 2

_COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

_started = threading.Event()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _compass(deg: Optional[float]) -> str:
    """Convert a wind direction in degrees to an 8-point compass label."""
    if deg is None:
        return "--"
    index = int((float(deg) % 360) / 45.0 + 0.5) % 8
    return _COMPASS_8[index]


def _c_to_f(celsius: Optional[float]) -> Optional[int]:
    if celsius is None:
        return None
    return round(celsius * 9.0 / 5.0 + 32.0)


def _fmt_lux(lux: Optional[float]) -> str:
    """Format illuminance compactly, abbreviating thousands (max 6 chars)."""
    if lux is None:
        return "--lx"
    lux = float(lux)
    if lux >= 1000:
        return f"{round(lux / 1000)}klx"
    return f"{round(lux)}lx"


def _rain_indicator(obs: Optional[dict]) -> str:
    if not obs:
        return "R:?"
    raining = (obs.get("rain_prev_min_mm") or 0) > 0 or (obs.get("precip_type") or 0) != 0
    return "R:Y" if raining else "R:N"


def _pad(line: str) -> str:
    """Truncate/pad a line to exactly LCD_COLS characters."""
    return line[:LCD_COLS].ljust(LCD_COLS)


def format_lines(obs: Optional[dict], wind: Optional[dict], healthy: bool) -> Tuple[str, str]:
    """Build the two LCD rows from current state. Pure; no hardware access."""
    temp_f = _c_to_f(obs.get("air_temp_c")) if obs else None
    humidity = obs.get("relative_humidity_pct") if obs else None
    uv = obs.get("uv_index") if obs else None

    wind_mph = wind.get("wind_speed_mph") if wind else None
    wind_dir = _compass(wind.get("wind_direction_deg")) if wind else "--"

    temp_s = f"{temp_f}F" if temp_f is not None else "--F"
    hum_s = f"{round(humidity)}%" if humidity is not None else "--%"
    wind_s = f"{round(wind_mph)}mph" if wind_mph is not None else "--mph"
    uv_s = f"UV{round(uv)}" if uv is not None else "UV-"

    line1 = f"{temp_s} {hum_s} {wind_s} {wind_dir}"
    line2 = f"{uv_s} {_fmt_lux(obs.get('illuminance_lux') if obs else None)} {_rain_indicator(obs)} {'OK' if healthy else '--'}"
    return _pad(line1), _pad(line2)


def _check_health() -> bool:
    """Return True only if the local /health endpoint reports status 'ok'."""
    url = os.getenv("HEALTH_URL", "http://127.0.0.1:8766/health")
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status != 200:
                return False
            payload = json.loads(resp.read().decode("utf-8"))
            return payload.get("status") == "ok"
    except Exception:
        return False


def _init_lcd():
    """Create and return a CharLCD handle, or None if it cannot be opened."""
    address = int(os.getenv("LCD_I2C_ADDRESS", "0x27"), 0)
    port = _env_int("LCD_I2C_PORT", 1)
    lcd = CharLCD(
        i2c_expander="PCF8574",
        address=address,
        port=port,
        cols=LCD_COLS,
        rows=LCD_ROWS,
        auto_linebreaks=False,
    )
    lcd.clear()
    return lcd


def _display_thread(lcd) -> None:
    interval = _env_int("LCD_UPDATE_SECONDS", 5)
    prev: Optional[Tuple[str, str]] = None
    while True:
        line1, line2 = format_lines(get_state("obs_st"), get_state("rapid_wind"), _check_health())
        if (line1, line2) != prev:
            try:
                lcd.cursor_pos = (0, 0)
                lcd.write_string(line1)
                lcd.cursor_pos = (1, 0)
                lcd.write_string(line2)
                prev = (line1, line2)
            except Exception:
                logger.exception("LCD write failed; disabling display")
                return
        time.sleep(interval)


def start_display() -> None:
    """Start the LCD render loop if a display is enabled and available.

    Safe to call unconditionally: returns quietly (logging the reason) when the
    display is disabled, the library is missing, or the LCD cannot be opened.
    """
    if _started.is_set():
        return

    mode = os.getenv("LCD_ENABLED", "auto").lower()
    if mode in ("false", "0", "no", "off"):
        logger.info("LCD display disabled via LCD_ENABLED")
        return

    if not _LIB_AVAILABLE:
        logger.info("LCD library (RPLCD) not installed; running without display")
        return

    try:
        lcd = _init_lcd()
    except Exception:
        logger.info("LCD not detected on I2C bus; running without display")
        return

    _started.set()
    t = threading.Thread(target=_display_thread, args=(lcd,), daemon=True, name="lcd-display")
    t.start()
    logger.info("LCD display started")
