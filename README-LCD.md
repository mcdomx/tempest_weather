# LCD Status Display (I2C 1602) — Setup Guide

This project can drive a **Hosyond I2C IIC 1602 LCD (16x2, PCF8574 backpack)**
attached to the Raspberry Pi to show service health and live weather metrics at
a glance — no browser or screen needed.

The display is **completely optional**. If the LCD is unplugged, the library is
missing, or the I2C bus errors, the application keeps running and serving the API
normally. You can wire it up at any time.

## What it shows

A fixed 16x2 layout (refreshes every ~5 s):

```
72F 55% 9mph NW      <- temperature(F)  humidity(%)  wind(mph)  wind direction
UV3 12klx R:N OK     <- UV index  illuminance(lux)  rain(R:Y/R:N)  health(OK/--)
```

- **Health** comes from the service's own `/health` endpoint. It shows `OK` when
  the API responds, and `--` when it doesn't.
- **Rain** is `R:Y` while rain is being measured (`rain_prev_min_mm > 0` or a
  precip type is reported), otherwise `R:N`.
- The 10-minute wind average and last-rain timestamp are **not** on the LCD (a
  1602 only holds 32 characters) — they remain available via the API.

## 1. Wiring

The module has a 4-pin I2C backpack. Connect it to the Pi 40-pin header:

| LCD pin | Pi pin            | Pi signal      |
|---------|-------------------|----------------|
| VCC     | Pin 2 (or 4)      | 5V             |
| GND     | Pin 6             | GND            |
| SDA     | Pin 3             | GPIO2 / SDA1   |
| SCL     | Pin 5             | GPIO3 / SCL1   |

> The 1602 needs **5V** on VCC for a usable backlight/contrast. SDA/SCL are 3.3V
> logic from the Pi; the PCF8574 backpack tolerates this fine.

```
 Pi header (top-left corner)
  1  2 (5V)  --> VCC
  3 (SDA) ----> SDA
  5 (SCL) ----> SCL
  6 (GND) ----> GND
```

## 2. Enable I2C on the Pi

```bash
sudo raspi-config        # Interface Options -> I2C -> Enable
sudo reboot
```

(Equivalent: ensure `dtparam=i2c_arm=on` in `/boot/firmware/config.txt`.)

## 3. Find the I2C address

```bash
sudo apt install -y i2c-tools
i2cdetect -y 1
```

You should see the device at `27` (the default) or `3f`. If it shows `3f`, set
`LCD_I2C_ADDRESS=0x3f` in `.env`.

## 4. Permissions for the service

The systemd service runs as `mcdomx`, which must be in the `i2c` group to open
`/dev/i2c-1`:

```bash
sudo usermod -aG i2c mcdomx
sudo systemctl restart tempest-weather
```

## 5. Dependencies

The LCD libraries (`RPLCD`, `smbus2`) are declared in the `Pipfile` with a
`sys_platform == 'linux'` marker, so they install automatically on the Pi and are
skipped on macOS dev machines. The existing CI/CD deploy installs them:

```bash
pipenv install --deploy
```

(They are pulled in on the next CI/CD `git pull` automatically.)

## 6. Configuration (`.env`)

All optional — defaults work for a standard Hosyond module at `0x27`:

| Variable             | Default                        | Purpose                                              |
|----------------------|--------------------------------|------------------------------------------------------|
| `LCD_ENABLED`        | `auto`                         | `auto` (use LCD if present), `true`, or `false`      |
| `LCD_I2C_ADDRESS`    | `0x27`                         | I2C address from `i2cdetect` (`0x27` or `0x3f`)      |
| `LCD_I2C_PORT`       | `1`                            | I2C bus number (`1` on all modern Pis)               |
| `LCD_UPDATE_SECONDS` | `5`                            | Display refresh interval                             |
| `HEALTH_URL`         | `http://127.0.0.1:8766/health` | Endpoint polled for the health indicator             |

In `auto` mode (the default), the app enables the display only if the library
imports and the LCD initializes; otherwise it logs a line and runs without it.
Set `LCD_ENABLED=false` to force it off even when an LCD is attached.

## Troubleshooting

- **Blank / dim screen with a lit backlight** — adjust the small blue
  potentiometer on the backpack to set contrast.
- **`i2cdetect` shows nothing** — re-check wiring (SDA/SCL not swapped), confirm
  I2C is enabled and the Pi was rebooted.
- **Wrong characters / garbled text** — usually a contrast issue or the wrong
  address; verify `LCD_I2C_ADDRESS` matches `i2cdetect`.
- **`Permission denied` on `/dev/i2c-1`** — add the service user to the `i2c`
  group (step 4) and restart the service.
- **Health shows `--`** — the `/health` endpoint isn't responding; check the
  service is running (`systemctl status tempest-weather`) and `HEALTH_URL`.
- **Confirm graceful operation** — unplug the LCD and restart the service; the
  API continues to work and the logs note the display was not detected.
