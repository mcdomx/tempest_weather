# Tempest Weather Station — Project Guidelines

## Purpose
Local UDP listener, data exploration, and HTTP API service for a WeatherFlow Tempest weather station.

## Stack
- Python 3.13, Jupyter notebooks, pandas, FastAPI, uvicorn, httpx
- Dependency management: `pipenv`
- No external weather libraries — raw sockets only

## Key Constants
- UDP port: `50222`
- Buffer size: `4096` bytes
- Hub broadcasts every 10 seconds (`hub_status`); `obs_st` every minute; `rapid_wind` every 3 seconds

## Architecture

```
app/
  listener.py   # UDP daemon thread, in-memory state store, SSE subscriber fan-out
  parser.py     # pure parse functions for all message types (no pandas)
  api.py        # FastAPI app, lifespan, all REST and SSE endpoints
  cloud.py      # Tempest cloud REST API client (history and forecast endpoints)
  display.py    # optional I2C 1602 LCD status display (no-op if absent)
main.py         # uvicorn entry point (port 8766)
Dockerfile
docker-compose.yml
deploy/
  tempest-weather.service  # systemd unit for production Pi deployment
scripts/
  cicd_update.py           # CI/CD polling script (stdlib only)
  run_cicd.sh              # executable wrapper; sets ENVIRONMENT=production
notebooks/      # exploratory Jupyter notebooks (unchanged)
tests/          # pytest test suite
conftest.py     # adds project root to sys.path for test imports
```

**Connection pattern**: A daemon thread opens a UDP socket on port 50222, parses each broadcast via `app/parser.py`, updates an in-memory state dict, and fans out to any active SSE subscriber queues via `asyncio.call_soon_threadsafe`. FastAPI routes read from that shared state.

**Cloud API pattern**: `app/cloud.py` calls `swd.weatherflow.com/swd/rest` using `TEMPEST_PERSONAL_TOKEN`. The numeric station ID and device ID are each auto-discovered via `/stations` on first use and cached for the process lifetime. Both can be pinned via `TEMPEST_STATION_ID` / `TEMPEST_DEVICE_ID` env vars to skip discovery.

**Display pattern**: `app/display.py` optionally drives an I2C 1602 LCD (PCF8574 backpack) on a Raspberry Pi. `start_display()` (called from `lifespan` after `start_listener()`) runs a daemon thread that reads listener state and polls `/health`, rendering a fixed 16x2 screen. Every hardware path is guarded — a missing `RPLCD` library, absent LCD, or I2C error is logged and the app runs without the display. The libraries are linux-marked in the `Pipfile` (skipped on macOS). See `README-LCD.md` for wiring and setup.

## API Endpoints

| Method | Path | Action |
|--------|------|--------|
| GET | `/health` | Service health check |
| GET | `/weather/latest` | Latest `obs_st` observation (all 18 fields) |
| GET | `/weather/wind` | Latest `rapid_wind` reading |
| GET | `/weather/status` | Hub and device heartbeat status |
| GET | `/weather/stream` | SSE stream — all message types |
| GET | `/weather/stream/obs` | SSE stream — `obs_st` only (every ~60s) |
| GET | `/weather/stream/wind` | SSE stream — `rapid_wind` only (every 3s) |
| GET | `/weather/history` | Historical `obs_st` from Tempest cloud API (requires `TEMPEST_PERSONAL_TOKEN`) |
| GET | `/weather/forecast/daily` | 10-day forecast from Tempest Better Forecast API |
| GET | `/weather/forecast/hourly` | Hourly forecast (~231 hours) from Tempest Better Forecast API |
| POST | `/admin/restart` | Restart the systemd service (unauthenticated) |
| POST | `/admin/cicd` | Force a CI/CD deploy check, bypassing the interval gate (unauthenticated) |

`/weather/history` accepts a `minutes` query parameter (1–1440, default 60). Fields match `obs_st` naming. The forecast and history endpoints require `TEMPEST_PERSONAL_TOKEN`; station/device IDs are auto-discovered.

## Running

### Native (macOS — receives UDP broadcasts)
```bash
pipenv install
pipenv run python main.py
```

### Docker (Linux host — receives UDP broadcasts via host networking)
```bash
docker compose build
docker compose up
```

> On macOS, Docker cannot receive subnet UDP broadcasts. Use native mode for development. On Linux, `docker-compose.yml` uses `network_mode: host` — swap `ports:` for that when deploying to a Linux host.

### Notebooks
```bash
pipenv run jupyter notebook
```

## Testing
```bash
pipenv run pytest tests/
```

## Environment Variables

`.env` holds cloud REST API credentials (not required for UDP):
```
TEMPEST_CLIENT_ID
TEMPEST_SECRET
TEMPEST_PERSONAL_TOKEN   # required for /weather/history and /weather/forecast/*
WEATHER_PORT             # host port for docker-compose (default: 8766)
STATION_TIMEZONE         # IANA timezone for timestamp display (default: America/New_York)
TEMPEST_STATION_ID       # optional numeric station ID; auto-discovered via /stations if unset
TEMPEST_DEVICE_ID        # optional numeric ST device ID; auto-discovered via /stations if unset
CICD_INTERVAL_MINUTES    # polling interval for CI/CD script in minutes (default: 15)
LCD_ENABLED              # I2C LCD: auto (default) | true | false  — see README-LCD.md
LCD_I2C_ADDRESS          # LCD I2C address (default: 0x27; some modules use 0x3f)
LCD_I2C_PORT             # I2C bus number (default: 1)
LCD_UPDATE_SECONDS       # LCD refresh interval in seconds (default: 5)
HEALTH_URL               # endpoint polled for the LCD health indicator (default: http://127.0.0.1:8766/health)
```

## CI/CD (Raspberry Pi production only)

`scripts/cicd_update.py` polls GitHub for new commits on `main` and automatically deploys. It only runs when `ENVIRONMENT=production` is set — safe to run accidentally in dev.

**Sudoers prerequisite** — the cron job restarts the service non-interactively, so this entry is required in `/etc/sudoers.d/tempest-weather`:
```
mcdomx ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart tempest-weather
```

**Cron entry (Pi, as `mcdomx`):**
```
(crontab -l 2>/dev/null; echo "* * * * * ENVIRONMENT=production /usr/bin/python3 /home/mcdomx/tempest_weather/scripts/cicd_update.py") | crontab -
```

**Manual trigger:**
```bash
./scripts/run_cicd.sh
```

**Pause / resume without editing cron:**
```bash
touch .cicd_disabled   # pause
rm .cicd_disabled      # resume
```

**Logs:** `logs/cicd.log`

**Key behaviour:**
- Cron fires every minute; the script gates on `CICD_INTERVAL_MINUTES` via `logs/.last_run` — most fires are silent no-ops
- On new commits: `git pull` → `pipenv install` → `systemctl restart tempest-weather`
- `Pipfile.lock` is committed for reproducibility; regenerate it on the Pi when adding Linux-only packages (e.g. RPLCD)
