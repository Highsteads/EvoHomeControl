# EvoHome Heating Controller

An Indigo home automation plugin that provides intelligent 24/7 control of Evohome TRV heating zones via the [RAMSES ESP](https://github.com/Highsteads/RAMSES_ESP) bridge plugin.

Converted from a scheduled Python script to a persistent plugin, adding timed boost, En Suite morning schedule, warm-morning skip, and window-aware floor heating control.

## Features

- **12-zone heating control** — processes all Evohome TRV zones every 5 minutes via `runConcurrentThread`
- **Overheat prevention** — detects rooms overheating and reduces setpoints; 3-tier logic (predictive, trigger, hysteresis)
- **Window/door detection** — closes valves when windows or doors are open; restores on close
- **Timed boost** — raise Dining Room, Living Room (door + front), and Hall Kitchen by +2°C for 1 or 2 hours; auto-reverts at expiry
- **En Suite morning schedule** — automatic 22°C from 06:00–10:00 daily with floor heating; cancelled immediately if En Suite window opens; **also skipped entirely on warm mornings** (outdoor ≥ 10 °C at 06:00 → radiator stays off, floor heat not turned on)
- **Weather integration** — OpenWeatherMap API with local Ecowitt bypass option
- **Away / Both-Out / Guest modes** — freeze protection and alternative schedules
- **Daily rotating logs** — append-only daily log files with 14-day retention
- **State persistence** — timed boost and En Suite state survive plugin reloads

## Requirements

- Indigo 2025.2 or later (Python 3.13)
- [RAMSES ESP](https://github.com/Highsteads/RAMSES_ESP) plugin (for Evohome TRV control via RAMSES-II — replaces the earlier HA Agent dependency)
- OpenWeatherMap API key (free tier sufficient)
- Ecowitt outdoor weather sensor (optional but recommended — used by warm-morning skip and overheat logic)
- Pushover plugin (optional, for alerts)
- Email+ plugin (optional, for alerts)

## Installation

1. Go to the [Releases](https://github.com/Highsteads/EvoHomeControl/releases) page and download `EvoHomeControl.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `EvoHomeControl.indigoPlugin`
3. Double-click `EvoHomeControl.indigoPlugin` — Indigo will install it automatically
4. In Indigo, go to **Plugins → Manage Plugins** and enable **EvoHome Heating Controller**
5. Create a **EvoHome Heating Controller** device (Plugins → EvoHome Heating Controller → New Device)
6. Configure the plugin preferences (API key, location, intervals)

## Credentials — `IndigoSecrets.py` vs `IndigoSecrets_example.py`

This plugin (along with all CliveS Indigo plugins) reads sensitive values from
a shared master credentials file at:

`/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

| File | Purpose | Real data? | Committed to GitHub? |
|------|---------|------------|----------------------|
| `IndigoSecrets.py` | Working file the plugin reads at runtime. Keep a backup in a password manager. | YES | **NO** — listed in `.gitignore` |
| `IndigoSecrets_example.py` | Template only — empty placeholders. Shipped in the plugin bundle. | NO | YES |

If you do not have `IndigoSecrets.py`, copy `IndigoSecrets_example.py` from
the plugin bundle to that location and fill in your values. Or skip
`IndigoSecrets.py` entirely and enter values via the plugin's configuration
dialog — `IndigoSecrets.py` wins over the dialog when both are set.

If a required value is set in NEITHER source the plugin logs an ERROR
pointing the user to either fill in the matching field or add the key to
`IndigoSecrets.py`.
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

### Warm-morning skip (v1.5+)

At 06:00 the plugin checks the current outdoor temperature. If it is at or above the warm-morning threshold (**10 °C**, hardcoded in `heating_logic.py:EN_SUITE_WARM_MORNING_THRESHOLD`):

- The 22 °C morning slot is **not activated** — `enSuiteMorningActive` stays `false`
- The floor heating switch is **not turned on**
- The floor thermostat is **not modified**
- The radiator is held at **8 °C** (`RADIATORS_OFF_TEMP`) for the remainder of 06:00–09:59 — otherwise the schedule's 19–20 °C values for those hours would still run
- `cancelled_reason` in plugin state is set to `"warm_outdoor"` (visible via `_log_modes_section`)
- Event log shows: `Warm morning skip  (out >=10degC, rad+floor off)` (message code 24)

If outdoor drops below 10 °C on a cold morning, the normal 22 °C slot runs as usual. The threshold is a single constant — edit `heating_logic.py:EN_SUITE_WARM_MORNING_THRESHOLD` to tune for a different installation.

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

CliveS & Claude (model identity tracked per release in the version history below)

## Logging

Every log line is prefixed with a millisecond timestamp `[HH:MM:SS.mmm]` so
events can be correlated tightly with other CliveS plugins (Device Activity
Monitor uses the same convention).

To turn the prefix off (or back on) at any time:

**Plugins → EvoHome Heating Controller → Toggle Timestamps in Log (on/off)**

The setting is stored in `pluginPrefs` (`timestampEnabled`) and persists across
restarts. Defaults to ON.

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 1.5.2 | 23-05-2026 | Millisecond timestamp `[HH:MM:SS.mmm]` prefix on every `self.logger` line via `plugin_utils.install_timestamp_filter()`; new "Toggle Timestamps in Log" menu item. |
| 1.5.1 | 23-05-2026 | Secrets-policy housekeeping — `weather.py` `OWMWeather` constructor default lat/lon switched from CliveS coords (54.882, -1.818) to `0.0, 0.0`. The plugin startup path always passes real values resolved from `IndigoSecrets` / PluginConfig; the defensive default just stops the developer location leaking if anyone ever instantiates the class directly. No user-visible behaviour change. |
| 1.5 | 23-05-2026 | En Suite warm-morning skip — if outdoor ≥ 10 °C at 06:00 the morning slot is not activated (radiator stays off, floor heat off, floor thermostat untouched). New `cancelled_reason` value `"warm_outdoor"` and new event-log message code 24. Co-authored with Claude Opus 4.7. |
| 1.4 | 13-05-2026 | Overheat alert email moved to `IndigoSecrets.OVERHEAT_ALERT_EMAIL`. Location (lat/lon) moved to `IndigoSecrets.LATITUDE/LONGITUDE`. Removed hardcoded Ecowitt device IDs from PluginConfig. Cleaned legacy 2025.1 migration paths. |
| 1.0 | 15-04-2026 | Initial release — full port from EvoHome_Radiator_Update.py v8.14 with timed boost and En Suite morning schedule |
