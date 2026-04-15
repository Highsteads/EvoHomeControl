# EvoHome Heating Controller

An Indigo home automation plugin that provides intelligent 24/7 control of Evohome TRV heating zones via the Home Assistant Agent plugin.

Converted from a scheduled Python script to a persistent plugin, adding timed boost, En Suite morning schedule, and window-aware floor heating control.

## Features

- **12-zone heating control** — processes all Evohome TRV zones every 5 minutes via `runConcurrentThread`
- **Overheat prevention** — detects rooms overheating and reduces setpoints; 3-tier logic (predictive, trigger, hysteresis)
- **Window/door detection** — closes valves when windows or doors are open; restores on close
- **Timed boost** — raise Dining Room, Living Room (door + front), and Hall Kitchen by +2°C for 1 or 2 hours; auto-reverts at expiry
- **En Suite morning schedule** — automatic 22°C from 06:00–10:00 daily with floor heating; cancelled immediately if En Suite window opens
- **Weather integration** — OpenWeatherMap API with local Ecowitt bypass option
- **Away / Both-Out / Guest modes** — freeze protection and alternative schedules
- **Daily rotating logs** — append-only daily log files with 14-day retention
- **State persistence** — timed boost and En Suite state survive plugin reloads

## Requirements

- Indigo 2025.1 or later
- Home Assistant Agent plugin (for Evohome TRV control via RAMSES-II)
- OpenWeatherMap API key (free tier sufficient)
- Pushover plugin (optional, for alerts)
- Email+ plugin (optional, for alerts)

## Installation

1. Go to the [Releases](https://github.com/Highsteads/EvoHomeControl/releases) page and download `EvoHomeControl.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `EvoHomeControl.indigoPlugin`
3. Double-click `EvoHomeControl.indigoPlugin` — Indigo will install it automatically
4. In Indigo, go to **Plugins → Manage Plugins** and enable **EvoHome Heating Controller**
5. Create a **EvoHome Heating Controller** device (Plugins → EvoHome Heating Controller → New Device)
6. Configure the plugin preferences (API key, location, intervals)

## Credentials

This plugin uses `secrets.py` for the OpenWeatherMap API key.

Add to your master secrets file at `/Library/Application Support/Perceptive Automation/secrets.py`:

```python
OWM_API_KEY = "your-openweathermap-api-key-here"
```

A template is provided at `Contents/Server Plugin/secrets_example.py`.

If `secrets.py` is not present, the API key falls back to the value entered in Plugin Preferences.

## Actions

| Action | Description |
|--------|-------------|
| Start Timed Boost (1 hour) | Raises Dining Room, Living Room, Hall Kitchen by +2°C for 1 hour |
| Start Timed Boost (2 hours) | Same rooms, 2 hour duration |
| Cancel Timed Boost | Immediately reverts boost rooms to schedule |
| Run Heating Cycle Now | Forces an immediate heating cycle |
| Set Away Mode | Activates or deactivates away mode |

## En Suite Morning Schedule

- Activates automatically at **06:00** each day
- Sets En Suite radiator to **22°C** and turns on floor heating
- Cancelled immediately if the **En Suite window** is opened (window open = shower finished)
- Auto-expires at **10:00** if window was never opened
- Resets at midnight — active again the following morning

## Device States

The `heatingController` device exposes these states in Indigo:

| State | Description |
|-------|-------------|
| `activeMode` | Current mode: Schedule / Away / Both-Out / Boost / Timed Boost 1h / Timed Boost 2h / En Suite Morning |
| `timedBoostActive` | True/False |
| `timedBoostExpiry` | HH:MM expiry time |
| `enSuiteMorningActive` | True/False |
| `overheatRooms` | Comma-separated list of rooms currently suppressed |
| `outdoorTempC` | Current outdoor temperature used for control |
| `lastUpdate` | Timestamp of last heating cycle |

## Author

CliveS & Claude Sonnet 4.6

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 15-04-2026 | Initial release — full port from EvoHome_Radiator_Update.py v8.14 with timed boost and En Suite morning schedule |
