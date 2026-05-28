# Tempest Weather Station

Local UDP listener and HTTP API service for a WeatherFlow Tempest weather station hub on the same network. No cloud connection or API token required.

## Requirements

- WeatherFlow Tempest hub on the same local network
- Python 3.9
- `pipenv`
- Docker (optional)

## Setup

```bash
pipenv install
```

## Running

### Native (macOS / Linux)
Receives UDP broadcasts directly from the hub and serves the API on port 8766.

```bash
pipenv run python main.py
```

### Docker (Linux host)
Uses `network_mode: host` so the container can receive UDP broadcasts from the hub.

```bash
docker compose build
docker compose up
```

> On macOS, Docker Desktop cannot receive subnet UDP broadcasts. Use native mode on macOS.

### Jupyter Notebooks (exploration)
```bash
pipenv run jupyter notebook
```
Open `notebooks/tempest_udp.ipynb`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |
| GET | `/weather/latest` | Latest full weather observation |
| GET | `/weather/wind` | Latest wind speed and direction |
| GET | `/weather/status` | Hub and sensor heartbeat status |
| GET | `/weather/stream` | SSE stream — all message types |
| GET | `/weather/stream/obs` | SSE stream — observations only (~60s) |
| GET | `/weather/stream/wind` | SSE stream — wind only (every 3s) |

```bash
curl http://localhost:8766/health
curl http://localhost:8766/weather/latest
curl -N http://localhost:8766/weather/stream/wind
```

## Using the API from Python

With the service running, use any HTTP client (e.g. `requests`) against the existing endpoints:

```python
import requests

# Latest full weather observation
obs = requests.get("http://localhost:8766/weather/latest").json()
print(obs["air_temp_c"])

# Latest wind reading
wind = requests.get("http://localhost:8766/weather/wind").json()
print(wind["wind_speed_mph"])

# Hub and sensor status
status = requests.get("http://localhost:8766/weather/status").json()
print(status["hub"]["rssi"])
```

## How It Works

The Tempest hub broadcasts JSON messages on **UDP port 50222** to the local network. A background thread receives these messages, parses them, and stores the latest reading for each message type. FastAPI routes serve the current state and push updates to SSE subscribers.

### Message Types

| Type | Description | Frequency |
|------|-------------|-----------|
| `hub_status` | Hub heartbeat | Every 10 seconds |
| `device_status` | Tempest sensor heartbeat | Every minute |
| `obs_st` | Full weather observation (18 fields) | Every minute |
| `rapid_wind` | Wind speed and direction | Every 3 seconds |
| `evt_precip` | Rain start event | On event |
| `evt_strike` | Lightning strike | On event |

## Environment Variables

`.env` is used for cloud REST API credentials (not required for UDP):

```
TEMPEST_CLIENT_ID
TEMPEST_SECRET
TEMPEST_PERSONAL_TOKEN
WEATHER_PORT    # host port for docker-compose (default: 8766)
```
