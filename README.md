# EvoHome Heating Controller

An Indigo home automation plugin that provides intelligent 24/7 control of Evohome TRV heating zones via the [RAMSES ESP](https://github.com/Highsteads/RAMSES_ESP) bridge plugin.

It began life as a scheduled Python script and became a plugin that stays running, which brought timed boost, the En Suite morning schedule, the warm-morning skip, a whole-house summer shut-off, and window-aware floor heating control.

## Features

- **12-zone heating control** — processes all Evohome TRV zones every 5 minutes via `runConcurrentThread`
- **Overheat prevention** — spots a room getting too warm and drops its setpoint, using three tiers of logic (predictive, trigger, hysteresis)
- **Window/door detection** — closes the valves while a window or door is open, and restores them when it shuts
- **Timed boost** — lifts Dining Room, Living Room (door + front) and Hall Kitchen by +2°C for one or two hours, then reverts on its own
- **Whole-house summer shut-off** — turns the whole house off for summer (default 1 June to 30 September): every radiator is held at the 8 °C frost setpoint and the En Suite floor heating is switched off. Dates are configurable and there is a master on/off toggle. A 24-hour **Force Heating On** action or menu item brings everything back to normal for a day, then it reverts on its own
- **En Suite morning schedule** — 22°C from 06:00 to 10:00 every day with the floor heating on, cancelled the moment the En Suite window opens, and **skipped altogether on warm mornings** (outdoor ≥ 10 °C at 06:00 leaves the radiator off and the floor heat untouched)
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

This plugin, like every CliveS Indigo plugin, reads sensitive values from one
shared master file:

`/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

| File | Purpose | Real data? | Committed to GitHub? |
|------|---------|------------|----------------------|
| `IndigoSecrets.py` | Working file the plugin reads at runtime. Keep a backup in a password manager. | YES | **NO** — listed in `.gitignore` |
| `IndigoSecrets_example.py` | Template only — empty placeholders. Shipped in the plugin bundle. | NO | YES |

If you don't have `IndigoSecrets.py`, copy `IndigoSecrets_example.py` out of
the plugin bundle into `/Library/Application Support/Perceptive Automation/`,
rename it to `IndigoSecrets.py`, and fill in your values. Or skip the file
altogether and type the values into the plugin's configuration dialog — where
both are set, `IndigoSecrets.py` wins.

If neither source supplies a value the plugin needs, it logs an ERROR naming
the key and telling you to either fill in the matching field or add the key to
`IndigoSecrets.py`.

## Actions

| Action | Description |
|--------|-------------|
| Start Timed Boost (1 hour) | Raises Dining Room, Living Room, Hall Kitchen by +2°C for 1 hour |
| Start Timed Boost (2 hours) | Same rooms, 2 hour duration |
| Cancel Timed Boost | Immediately reverts boost rooms to schedule |
| Run Heating Cycle Now | Forces an immediate heating cycle |
| Set Away Mode | Activates or deactivates away mode |
| Force Heating On (24 hours) | Overrides the summer shut-off and restores fully normal heating for 24 hours, then auto-reverts |
| Cancel Forced Heating | Ends the 24-hour force-on early and re-applies the summer shut-off |

## En Suite Morning Schedule

- Activates automatically at **06:00** each day
- Sets En Suite radiator to **22°C** and turns on floor heating
- Cancelled immediately if the **En Suite window** is opened (window open = shower finished)
- Auto-expires at **10:00** if window was never opened
- Resets at midnight — active again the following morning

### Warm-morning skip (v1.5+)

At 06:00 the plugin checks the current outdoor temperature. If it is at or above the warm-morning threshold (**10 °C**, hardcoded in `heating_logic.py:EN_SUITE_WARM_MORNING_THRESHOLD`):

- The plugin skips the 22 °C morning slot — `enSuiteMorningActive` stays `false`
- It leaves the floor heating switch off
- It leaves the floor thermostat alone
- It holds the radiator at **8 °C** (`RADIATORS_OFF_TEMP`) for the rest of 06:00–09:59, because the schedule's 19–20 °C values for those hours would otherwise still run
- It sets `cancelled_reason` in plugin state to `"warm_outdoor"` (visible via `_log_modes_section`)
- Event log shows: `Warm morning skip  (out >=10degC, rad+floor off)` (message code 24)

On a colder morning, with outdoor below 10 °C, the normal 22 °C slot runs as usual. The threshold is a single constant — edit `heating_logic.py:EN_SUITE_WARM_MORNING_THRESHOLD` to tune for a different installation.

## Whole-house Summer Shut-off

Through the warmer months there is no need to run any heating, so the plugin can shut the whole house down for a fixed window each year.

- While the window is active (default **1 June to 30 September**) every radiator is held at the **8 °C** frost setpoint and the **En Suite floor heating** is switched off
- The normal per-room cycle and the En Suite morning boost are skipped for the duration, so nothing fights the shut-off
- Heating returns automatically on the **return date** — for example 30 September means off from 1 June to 29 September inclusive, with normal heating from the 30th
- The radiators sit at 8 °C rather than being forced fully shut, so genuine frost protection is still in place for the rare cold snap

### Forcing heating on for a day

If you want heat during the shut-off — a cold spell, guests, or drying towels — use **Force Heating On (24 hours)**, available as both an Indigo action and a Plugins-menu item. For the next 24 hours the whole house behaves exactly as it does outside the summer window, then it reverts to the shut-off on its own. **Cancel Forced Heating** ends the override early. The 24-hour timer is saved to disk, so it survives a plugin restart.

### Configuration

The four date fields and the master toggle live in **Plugins → EvoHome Heating Controller → Configure**:

| Setting | Default | Notes |
|---------|---------|-------|
| Enable summer shut-off | On | Master switch for the whole feature |
| Shut-off starts (month / day) | 1 June | First day the house goes off |
| Heating returns (month / day) | 30 September | Day normal heating comes back on (the window end is exclusive) |

A window whose start falls later in the year than its end (for example 1 November to 1 March) is handled correctly as a wrap across the year-end.

## Device States

The `heatingController` device exposes these states in Indigo:

| State | Description |
|-------|-------------|
| `activeMode` | Current mode: Schedule / Away / Both-Out / Boost / Timed Boost 1h / Timed Boost 2h / En Suite Morning / Summer Off / Forced On (summer) |
| `timedBoostActive` | True/False |
| `timedBoostExpiry` | HH:MM expiry time |
| `enSuiteMorningActive` | True/False |
| `summerStatus` | Human-readable summer shut-off state (e.g. "Summer shut-off ACTIVE…", "FORCED ON…") |
| `overheatRooms` | Comma-separated list of rooms currently suppressed |
| `outdoorTempC` | Current outdoor temperature used for control |
| `lastUpdate` | Timestamp of last heating cycle |

## Logging

Every log line carries a millisecond timestamp `[HH:MM:SS.mmm]`, so you can
line events up precisely against the other CliveS plugins — Device Activity
Monitor uses the same format.

To turn the prefix off, or back on, at any time:

**Plugins → EvoHome Heating Controller → Toggle Timestamps in Log (on/off)**

The plugin stores the setting in `pluginPrefs` (`timestampEnabled`) and it
survives a restart. It defaults to ON.

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 1.7.3 | 21-07-2026 | Housekeeping. Named log levels now map to the real logging levels — warnings and errors raised through the shared helper had been appearing as plain info lines, so amber and red entries people relied on for diagnosis never showed. Shared-utility refresh: calling the log timestamp filter twice no longer double-stamps every line, and the module imports cleanly outside Indigo. |
| 1.7.2 | 04-07-2026 | Final tidy-up pass from the review. Changing the OpenWeatherMap key or your location in the settings now takes effect straight away rather than only after a restart. The morning En Suite floor heating is no longer switched back on while the summer shut-off is holding everything off. The overheat monitor is a bit sturdier — its status readouts no longer trip over a reading arriving at the same moment, and it starts each heating season with a clean slate. Alerts now quote the actual amount a radiator was turned down by. Setpoints keep their half-degree precision instead of being rounded to the nearest whole degree. A couple of developer-specific device references were removed so the plugin behaves the same on anyone's system. Co-authored with Claude Opus 4.8. |
| 1.7.1 | 03-07-2026 | Second robustness pass from the same review. The saved state files (boost and force-on timers, the setpoint cache, the overheat history and the weather cache) are now written safely so a crash or power cut part-way through a save can no longer leave a corrupt file, and a corrupt or old state file is now shrugged off at startup rather than stopping the plugin from loading. The overheat alert no longer trips over a missing outdoor temperature. If a radiator briefly stops reporting its temperature the plugin now leaves that room on its current setting for the cycle rather than treating it as freezing cold. Door sensors are now read the same reliable way as window sensors. The weather error log no longer echoes the OpenWeatherMap key. Co-authored with Claude Opus 4.8. |
| 1.7.0 | 03-07-2026 | Robustness pass from a full multi-agent code review. The 24/7 control loop now shrugs off a one-off error instead of quietly dying — a single bad reading, a deleted variable or a blank setting used to stop all heating with the plugin still showing as running, and each five-minute tick and each of the twelve zones is now isolated so the rest carry on. Every numeric setting is read defensively, so a cleared or non-numeric config field can no longer halt the plugin or make it misbehave. Warning and error log lines now show up correctly as warnings and errors rather than being quietly filed as ordinary info. The **Start Timed Boost**, **Cancel Timed Boost**, **Run Heating Cycle Now** and **Set Away Mode** actions are now selectable from the action list and usable in scripts (they were previously hidden behind a device that this setup does not create). Co-authored with Claude Opus 4.8. |
| 1.6.2 | 10-06-2026 | Housekeeping — lint tidy-up and a continuous-integration check added as part of a fleet-wide audit. No behaviour change. |
| 1.6.1 | 07-06-2026 | Added a **Show Summer Shut-off Status** action so the heating dashboard can report the summer state on demand. |
| 1.6.0 | 06-06-2026 | Whole-house summer shut-off (default 1 Jun–30 Sep, configurable): all radiators held at 8 °C and the En Suite floor heating off for the window, with the normal cycle and En Suite morning boost skipped. New 24-hour **Force Heating On** / **Cancel Forced Heating** actions and menu items (override persists across restarts), two custom events, and a `summerStatus` device state. Co-authored with Claude Opus 4.8. |
| 1.5.2 | 23-05-2026 | Millisecond timestamp `[HH:MM:SS.mmm]` prefix on every `self.logger` line via `plugin_utils.install_timestamp_filter()`; new "Toggle Timestamps in Log" menu item. |
| 1.5.1 | 23-05-2026 | Secrets-policy housekeeping — `weather.py` `OWMWeather` constructor default lat/lon switched from CliveS coords (54.882, -1.818) to `0.0, 0.0`. The plugin startup path always passes real values resolved from `IndigoSecrets` / PluginConfig; the defensive default just stops the developer location leaking if anyone ever instantiates the class directly. No user-visible behaviour change. |
| 1.5 | 23-05-2026 | En Suite warm-morning skip — if outdoor ≥ 10 °C at 06:00 the morning slot is not activated (radiator stays off, floor heat off, floor thermostat untouched). New `cancelled_reason` value `"warm_outdoor"` and new event-log message code 24. Co-authored with Claude Opus 4.7. |
| 1.4 | 13-05-2026 | Overheat alert email moved to `IndigoSecrets.OVERHEAT_ALERT_EMAIL`. Location (lat/lon) moved to `IndigoSecrets.LATITUDE/LONGITUDE`. Removed hardcoded Ecowitt device IDs from PluginConfig. Cleaned legacy 2025.1 migration paths. |
| 1.0 | 15-04-2026 | Initial release — full port from EvoHome_Radiator_Update.py v8.14 with timed boost and En Suite morning schedule |

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
