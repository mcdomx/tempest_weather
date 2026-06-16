"""Tests for the optional LCD display module.

All tests are pure-function / no-hardware so they run on any platform (the
RPLCD library is linux-only and absent in CI on macOS).
"""

import app.display as display
from app.display import (
    LCD_COLS,
    _compass_index,
    _c_to_f,
    _fmt_lux,
    _rain_indicator,
    format_lines,
    start_display,
)

FULL_OBS = {
    "air_temp_c": 22.4,
    "relative_humidity_pct": 55,
    "illuminance_lux": 12345,
    "uv_index": 3,
    "rain_prev_min_mm": 0,
    "precip_type": 0,
}
FULL_WIND = {"wind_speed_mph": 9.2, "wind_direction_deg": 315}


def test_format_lines_full_state():
    line1, line2 = format_lines(FULL_OBS, FULL_WIND)
    assert len(line1) == LCD_COLS
    assert len(line2) == LCD_COLS
    assert line1.startswith("72F 55% 9mph")
    assert line1[15] == chr(7)  # 315° → NW → CGRAM slot 7, right-justified
    assert line2.startswith("UV3")       # UV left-justified
    assert line2.endswith("R:N")        # rain right-justified
    assert "12klx" in line2             # lux centred


def test_format_lines_missing_state_uses_placeholders():
    line1, line2 = format_lines(None, None)
    assert len(line1) == LCD_COLS
    assert len(line2) == LCD_COLS
    assert "--F" in line1
    assert "--mph" in line1
    assert "R:?" in line2


def test_format_lines_missing_wind_only():
    line1, _ = format_lines(FULL_OBS, None)
    assert "72F 55%" in line1
    assert "--mph" in line1
    assert "?" in line1


def test_rain_indicator():
    assert _rain_indicator({"rain_prev_min_mm": 0.5, "precip_type": 0}) == "R:Y"
    assert _rain_indicator({"rain_prev_min_mm": 0, "precip_type": 1}) == "R:Y"
    assert _rain_indicator({"rain_prev_min_mm": 0, "precip_type": 0}) == "R:N"
    assert _rain_indicator(None) == "R:?"


def test_compass_index_boundaries():
    assert _compass_index(0) == 0    # N
    assert _compass_index(45) == 1   # NE
    assert _compass_index(90) == 2   # E
    assert _compass_index(180) == 4  # S
    assert _compass_index(315) == 7  # NW
    assert _compass_index(359) == 0  # N
    assert _compass_index(360) == 0  # N
    assert _compass_index(None) is None


def test_fmt_lux_thresholds():
    assert _fmt_lux(999) == "999lx"
    assert _fmt_lux(1000) == "1klx"
    assert _fmt_lux(12345) == "12klx"
    assert _fmt_lux(None) == "--lx"


def test_c_to_f():
    assert _c_to_f(0) == 32
    assert _c_to_f(22.4) == 72
    assert _c_to_f(None) is None


def test_start_display_noop_without_library(monkeypatch):
    """The 'works without a display' guarantee: no raise, no thread started."""
    monkeypatch.setattr(display, "_LIB_AVAILABLE", False)
    display._started.clear()
    start_display()  # must not raise
    assert not display._started.is_set()
