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

pip3 install --user pipenv --break-system-packages
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Verify Python 3.13 is available:

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
PIPENV_VENV_IN_PROJECT=1 pipenv lock && pipenv install --deploy
```

`pipenv lock` regenerates `Pipfile.lock` for the Pi's Python version. `--deploy` then enforces those exact versions.

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

The CI/CD script calls `sudo systemctl restart tempest-weather` non-interactively, and the `/admin/reboot` endpoint calls `sudo reboot`, so the `mcdomx` user needs passwordless sudo permission for both commands.

```bash
sudo visudo -f /etc/sudoers.d/tempest-weather
```

Add these lines:

```
mcdomx ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart tempest-weather
mcdomx ALL=(ALL) NOPASSWD: /usr/sbin/reboot
```

Then install the cron job:

```bash
(crontab -l 2>/dev/null; echo "* * * * * ENVIRONMENT=production /usr/bin/python3 /home/mcdomx/tempest_weather/scripts/cicd_update.py") | crontab -
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

## 10. Watchdog & Freeze Diagnostics

The service's `Type=notify`/`WatchdogSec=30` (in `deploy/tempest-weather.service`)
makes systemd restart the app if its own event loop or UDP listener thread
hangs. That alone won't save you from a full system-level freeze (kernel
wedge, OOM thrashing), so also do this **once, now, while the Pi is still
reachable** — it can't be pushed through CI/CD:

**Hardware watchdog** — makes the Pi reboot itself if the kernel itself
becomes unresponsive:
```bash
echo "dtparam=watchdog=on" | sudo tee -a /boot/firmware/config.txt
sudo tee -a /etc/systemd/system.conf <<< "RuntimeWatchdogSec=10s"
sudo reboot
```
After reboot, confirm it's active: `sudo wdctl /dev/watchdog`.

**Persistent, capped journal** — so `journalctl -u tempest-weather -b -1`
(logs from the *previous* boot) survives an auto-reboot instead of being
wiped:
```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
printf "Storage=persistent\nSystemMaxUse=200M\n" | sudo tee -a /etc/systemd/journald.conf
sudo systemctl restart systemd-journald
```

**Resource-snapshot cron job** — records system + process + app metrics
every 2 minutes to `logs/resource_monitor.log` (self-rotating, capped),
independently of the app process, so there's something to look at after a
freeze:
```bash
(crontab -l 2>/dev/null; echo "*/2 * * * * /usr/bin/python3 /home/mcdomx/tempest_weather/scripts/resource_monitor.py") | crontab -
```

**After a freeze (auto-reboot or manual power-cycle), to find the cause:**
```bash
journalctl -u tempest-weather -b -1 --no-pager | tail -200   # app's last logs before the reboot
tail -100 logs/resource_monitor.log                          # RSS/FD/load/disk trend leading up to it
```
A steady climb in `rss_kb`/`fd_count` before the gap points at a subscriber
leak; climbing swap + load average points at OOM thrashing; disk near-full
points at log growth; a clean stop with nothing anomalous points at a
hardware/kernel-level wedge instead.

---

## Troubleshooting

**No weather data** — The Tempest hub and Pi must be on the same subnet. UDP broadcasts don't cross router boundaries.

**Port blocked** — Allow UDP port 50222:
```bash
sudo ufw allow 50222/udp
```

**pipenv not found in CI/CD** — Check `which pipenv` on the Pi and compare to `PIPENV` in `scripts/cicd_update.py`. Update the path if they differ.
