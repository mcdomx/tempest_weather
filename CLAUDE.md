# Tempest Weather Station — Project Guidelines

## Purpose
Local UDP listener, data exploration, and HTTP API service for a WeatherFlow Tempest weather station.

## Stack
- Python 3.9, Jupyter notebooks, pandas, FastAPI, uvicorn, httpx
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
  cloud.py      # Tempest cloud REST API client (history endpoint)
main.py         # uvicorn entry point (port 8766)
Dockerfile
docker-compose.yml
notebooks/      # exploratory Jupyter notebooks (unchanged)
tests/          # pytest test suite
conftest.py     # adds project root to sys.path for test imports
```

**Connection pattern**: A daemon thread opens a UDP socket on port 50222, parses each broadcast via `app/parser.py`, updates an in-memory state dict, and fans out to any active SSE subscriber queues via `asyncio.call_soon_threadsafe`. FastAPI routes read from that shared state.

**Cloud API pattern**: `app/cloud.py` calls `swd.weatherflow.com/swd/rest` using `TEMPEST_PERSONAL_TOKEN`. The numeric device ID is auto-discovered via `/stations` on first use and cached for the process lifetime.

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

`/weather/history` accepts a `minutes` query parameter (1–1440, default 60). Fields match `obs_st` naming. Device ID is auto-discovered; optionally set `TEMPEST_DEVICE_ID` to skip the discovery call.

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
TEMPEST_PERSONAL_TOKEN   # required for /weather/history
WEATHER_PORT             # host port for docker-compose (default: 8766)
STATION_TIMEZONE         # IANA timezone for timestamp display (default: America/New_York)
TEMPEST_DEVICE_ID        # optional numeric ST device ID; auto-discovered via /stations if unset
```
