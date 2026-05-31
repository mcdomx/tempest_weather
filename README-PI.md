# Raspberry Pi Setup — Tempest Weather

## 1. Flash the SD Card

### Install Raspberry Pi Imager

Download from **raspberrypi.com/software** (Mac, Windows, Linux).

### Flash

1. Insert your SD card (32GB+ recommended, Class 10 / A1 or faster)
2. Open Raspberry Pi Imager
3. **Choose Device** → your Pi model (e.g. Raspberry Pi 4)
4. **Choose OS** → Raspberry Pi OS Lite (64-bit)
5. **Choose Storage** → your SD card
6. Click **Next**, then **Edit Settings** when prompted

### Customize before flashing

**General tab:**
- Hostname: `tempest-pi` (or your preference)
- Username: `mcdomx` (must match `deploy/tempest-weather.service`)
- Password: set a strong password
- WiFi SSID and password

**Services tab:**
- Enable SSH → Use password authentication

Click **Save** → **Yes** → **Yes** to flash.

---

## 2. First Boot

Insert the SD card, power on the Pi, wait ~60 seconds, then SSH in:

```bash
ssh mcdomx@tempest-pi.local
```

If `.local` doesn't resolve, find the Pi's IP from your router and use that instead.

---

## 3. System Prerequisites

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip git -y

pip3 install --user pipenv
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Verify Python 3.9+ is available:

```bash
python3 --version
```

---

## 4. Clone the Repo

```bash
cd ~
git clone https://github.com/<your-repo>/tempest_weather.git
cd tempest_weather
```

---

## 5. Configure Environment

```bash
nano .env
```

Minimum contents:

```
TEMPEST_PERSONAL_TOKEN=your_token_here
STATION_TIMEZONE=America/New_York
```

See `CLAUDE.md` for the full list of supported env vars.

---

## 6. Install Dependencies

```bash
PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy
```

`--deploy` enforces `Pipfile.lock` — exact versions, no surprises.

---

## 7. Install and Start the systemd Service

```bash
sudo cp deploy/tempest-weather.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tempest-weather
sudo systemctl start tempest-weather

sudo systemctl status tempest-weather
```

Logs via:

```bash
journalctl -u tempest-weather -f
```

---

## 8. Set Up CI/CD (Auto-Deploy on New Commits)

Add to crontab (`crontab -e`):

```
* * * * * ENVIRONMENT=production /usr/bin/python3 /home/mcdomx/tempest_weather/scripts/cicd_update.py
```

This fires every minute but gates on `CICD_INTERVAL_MINUTES` (default: 15). Logs go to `logs/cicd.log`.

**Pause / resume without editing cron:**

```bash
touch .cicd_disabled   # pause
rm .cicd_disabled      # resume
```

**Manual trigger:**

```bash
./scripts/run_cicd.sh
```

---

## 9. Verify

```bash
curl http://localhost:8766/health
curl http://localhost:8766/weather/latest
```

Weather data populates after the first UDP broadcast from the Tempest hub (~10 seconds after service start).

---

## Troubleshooting

**No weather data** — The Tempest hub and Pi must be on the same subnet. UDP broadcasts don't cross router boundaries.

**Port blocked** — Allow UDP port 50222:
```bash
sudo ufw allow 50222/udp
```

**pipenv not found in CI/CD** — Check `which pipenv` on the Pi and compare to `PIPENV` in `scripts/cicd_update.py`. Update the path if they differ.
