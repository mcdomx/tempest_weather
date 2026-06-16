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
| GET | `/weather/history?minutes=60` | Historical observations from the Tempest cloud API |
| GET | `/weather/forecast/daily` | 10-day forecast from the Tempest cloud API |
| GET | `/weather/forecast/hourly` | Hourly forecast (~10 days) from the Tempest cloud API |

The `minutes` parameter for `/weather/history` accepts 1–1440 (default 60). The forecast and history endpoints require `TEMPEST_PERSONAL_TOKEN`.

```bash
curl http://localhost:8766/health
curl http://localhost:8766/weather/latest
curl "http://localhost:8766/weather/history?minutes=120"
curl http://localhost:8766/weather/forecast/daily
curl http://localhost:8766/weather/forecast/hourly
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

# Historical observations (last 2 hours)
history = requests.get("http://localhost:8766/weather/history?minutes=120").json()
for obs in history["observations"]:
    print(obs["timestamp"], obs["air_temp_c"])

# 10-day daily forecast
daily = requests.get("http://localhost:8766/weather/forecast/daily").json()
for day in daily["forecast"]:
    print(day["day_start_local"], day["conditions"], day["air_temp_high"], day["air_temp_low"])

# Hourly forecast
hourly = requests.get("http://localhost:8766/weather/forecast/hourly").json()
for hour in hourly["forecast"]:
    print(hour["time"], hour["air_temperature"], hour["wind_avg"])
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

`.env` is used for cloud REST API credentials (not required for UDP-only use):

```
TEMPEST_CLIENT_ID
TEMPEST_SECRET
TEMPEST_PERSONAL_TOKEN   # required for /weather/history and /weather/forecast/*
WEATHER_PORT             # host port for docker-compose (default: 8766)
STATION_TIMEZONE         # IANA timezone for timestamps (default: America/New_York)
TEMPEST_STATION_ID       # optional numeric station ID; auto-discovered if unset
TEMPEST_DEVICE_ID        # optional numeric device ID; auto-discovered if unset
CICD_INTERVAL_MINUTES    # how often the CI/CD script polls GitHub (default: 15)
```

## CI/CD — Automatic Deployment (Raspberry Pi)

`scripts/cicd_update.py` polls GitHub for new commits on `main` and automatically pulls, reinstalls dependencies, and restarts the service. It is designed to run on the production Raspberry Pi only.

### How it works

A cron job fires every minute. The script checks `CICD_INTERVAL_MINUTES` (default 15) against the last run time and exits silently if not enough time has passed. When an interval elapses, it fetches `origin/main`, compares the commit hash with local `HEAD`, and deploys only if something changed.

The script only runs when `ENVIRONMENT=production` is set. If that variable is missing or set to anything else, the script logs a message and exits — making accidental runs safe.

### Raspberry Pi setup

```bash
# 1. Clone the repo
cd /home/mcdomx
git clone https://github.com/mcdomx/tempest_weather.git
cd tempest_weather

# 2. Configure environment
nano .env   # add tokens and set CICD_INTERVAL_MINUTES as needed

# 3. Install dependencies
pip3 install pipenv
PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

# 4. Install and start the systemd service
#    Verify ExecStart path matches `which pipenv` on your Pi
sudo cp deploy/tempest-weather.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tempest-weather
sudo systemctl start tempest-weather

# 5. Allow the cron job to restart the service without a password prompt
sudo visudo -f /etc/sudoers.d/tempest-weather
# Add this line:
# mcdomx ALL=(ALL) NOPASSWD: /bin/systemctl restart tempest-weather

# 6. Install the cron job (runs as the mcdomx user)
(crontab -l 2>/dev/null; echo "* * * * * ENVIRONMENT=production /usr/bin/python3 /home/mcdomx/tempest_weather/scripts/cicd_update.py") | crontab -
```

### Manual trigger

```bash
./scripts/run_cicd.sh
```

### Pause / resume automation without editing cron

```bash
# Pause
touch /home/mcdomx/tempest_weather/.cicd_disabled

# Resume
rm /home/mcdomx/tempest_weather/.cicd_disabled
```

### Logs

```bash
tail -f /home/mcdomx/tempest_weather/logs/cicd.log
```
