#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: EvoHome Heating Controller — Indigo plugin main class
#              Converted from EvoHome_Radiator_Update.py v8.14
# Author:      CliveS & Claude Opus 4.8
# Date:        04-07-2026
# Version:     1.7.2
#
# v1.7.2 (04-07-2026): Deep-review LOW batch. (1) A changed OWM API key OR location
# now takes effect on config-save without a restart — WeatherData rebuilds its
# request URL via set_credentials() (the key was previously never re-applied either).
# (2) timestampEnabled is coerced by value, not truthiness (bool("false") was truthy).
# (3) _load_state no longer re-asserts En Suite floor heat ON during a summer lockout.
# (4) Overheat status readers snapshot the history dict so a menu-thread read can't
# hit 'dict changed size' against the cycle writer; overheat tracking is reset once on
# summer-lockout entry so no room stays stuck alert_sent across the season. (5) The
# critical-alert valve-status line reports the ACTUAL backoff, not a hard-coded 6degC.
# (6) Solcast values looked up BY NAME (hard-coded ids removed); the Clive-only Ecowitt
# device-id defaults removed (blank field just skips the section). (7) Setpoints round
# to the nearest 0.5degC (RAMSES resolution) instead of a whole degree. +3 tests -> 27.
#
# v1.7.1 (03-07-2026): Deep-review MEDIUM batch. (1) _load_state now tolerates a
# malformed/legacy plugin_state.json (catches TypeError/AttributeError + naive-vs-
# aware datetime compares) so a corrupt state file can no longer crash __init__ and
# stop the plugin loading. (2) plugin_state.json, the setpoint cache, the overheat
# history and the weather cache are all written atomically (temp file + fsync +
# os.replace) so a crash mid-write can't corrupt them and silently drop an active
# 24h force-on or all overheat history. (3) The critical-overheat alert no longer
# crashes when the outdoor temperature is unavailable (None) — it would otherwise
# raise every cycle. (4) A missing TRV temperature reading now skips that zone for
# the cycle (TRV holds its last setpoint) instead of being treated as 0degC, which
# made a room look freezing and defeated overheat detection. (5) Door contacts are
# now read through the same _contact_is_open() reader as windows, so a Zigbee2MQTT
# door contact is read correctly rather than via the raw onOffState.ui. (6) The OWM
# fetch-error log redacts the API key that requests can echo in the request URL.
# menuForceFullLog's log-buffer swap is serialised with the cycle via a lock. +4
# regression tests -> 24.
#
# v1.7.0 (03-07-2026): Deep-review HIGH batch. (1) runConcurrentThread now isolates
# each tick (log-and-continue, re-raise StopThread) and each of the 12 zones
# (_safe_process_room) so one transient error can no longer silently kill the 24/7
# heating loop. (2) Every pluginPrefs int()/float() on the hot path is now guarded
# via _safe_int/_safe_float + a clamped _run_interval_mins() helper (a blank/zero
# config field previously raised on the next tick and stopped the loop; "0" would
# ZeroDivision the OverheatMonitor timers). (3) String log levels ("WARNING"/"ERROR")
# were being silently downgraded to Info by Indigo — all four modules now translate
# to logging ints (_to_level / _slog). (4) The five timed-boost/run-now/away actions
# were gated behind a Heating Controller device that does not exist on this install,
# so they were unusable — deviceFilter dropped, they are now plugin-level/scriptable.
#
# v1.6.1 (07-06-2026): Added showSummerStatus action (callable via executeAction
# from the Dashboards heating page control panel; mirrors menuShowSummerStatus).
# v1.6.0 (06-06-2026): Whole-house summer shut-off. When enabled (PluginConfig,
# default 1 Jun -> 30 Sep) every radiator is held at RADIATORS_OFF_TEMP (8 degC)
# and the En Suite floor heating is switched off; the normal per-room cycle and
# the En Suite morning boost are skipped while the window is active. A 24-hour
# "Force Heating On" action / menu item overrides the shut-off and restores
# fully normal heating, auto-reverting after 24h. The force expiry is persisted
# to plugin_state.json so it survives a plugin restart. New plugin-level actions
# forceHeatingOn24h / cancelForcedHeating, three menu items, two custom events
# (summerForceStarted / summerForceEnded) and a summerStatus device state. The
# off-window dates are configurable in PluginConfig with a master enable toggle.
#
# v1.5.5 (03-06-2026): Outdoor-temp high/low record variables are now referenced
# by NAME, not hard-coded id (Average_Outside_Temp_Highest / _Highest_Time /
# _Lowest / _Lowest_Time). The hard-coded ids broke when those variables were
# recreated, spamming "could not find ... element ID" errors every cycle. The
# get_variable_value / update_variable helpers already accept a name, so by-name
# lookup is immune to future id changes. Records feature only — no heating impact.
#
# v1.5.4 (29-05-2026): Hourly event-log dump (weather header + full room
# table) now fires on the first cycle of each new clock hour instead of
# gating on minute == 0. The heating cycle is dispatched on a time-delta and
# drifts ~10-12s/hour, so the old minute == 0 gate was missed for whole days
# once the firing phase crept past the :00 boundary — the hourly radiator
# report silently stopped a few hours after every restart. Tracking the clock
# hour is immune to that drift and to any runIntervalMins value.
#
# v1.5.2 (23-05-2026): Millisecond timestamp [HH:MM:SS.mmm] prefix on every
# log line via plugin_utils.install_timestamp_filter() — matches Device
# Activity Monitor convention. Module-level _log helper already used ms
# precision. New "Toggle Timestamps in Log" menu item.
#
# v1.5.1 (23-05-2026): weather.py OWMWeather default lat/lon switched from
#                       Clive's Medomsley coords (54.882, -1.818) to 0.0, 0.0
#                       so direct instantiation no longer leaks the developer
#                       location. Plugin startup path always passes real values.
#
# v1.5 (23-05-2026):
# - En Suite warm-morning skip: at 06:00, if outdoor temperature is at or above
#   EN_SUITE_WARM_MORNING_THRESHOLD (10 degC) the 22 degC morning slot is not
#   activated. Radiator stays off (held at RADIATORS_OFF_TEMP by extended
#   en_suite_special_rules logic for the remainder of 06-10); floor heating
#   switch is not turned on and floor thermostat is not modified. New
#   cancellation reason "warm_outdoor" set in store. New message code 24
#   ("Warm morning skip") logged for the radiator state.
#
# v1.4 (13-05-2026):
# - Overheat alert email moved to IndigoSecrets.OVERHEAT_ALERT_EMAIL with
#   PluginConfig fallback. Hardcoded "overheat-alert@strudwick.co.uk" removed
#   from plugin.py (2 places) and PluginConfig.xml defaultValue.
# - Location (lat/lon) moved to IndigoSecrets.LATITUDE / LONGITUDE with
#   PluginConfig fallback. Hardcoded 54.882 / -1.818 removed.
# - Ecowitt outdoor + indoor device ID defaults removed from PluginConfig.xml
#   (user-specific values — must now be entered or left to plugin defaults).
# - Removed `_OLD_OVERHEAT_HIST` legacy migration constant pointing at
#   Indigo 2025.1 — that path no longer exists and the migration is complete.
# - Silent `except Exception: pass` in Ecowitt indoor/outdoor sensor lookups
#   now log at debug level (no more silent device-lookup failures).

import os
import sys
import json
import shutil
import time
import logging
import threading
import functools
from datetime import datetime, timedelta

import indigo

# ---------------------------------------------------------------------------
# Startup banner (bundled copy — no shared/system dependency)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.getcwd())
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None
try:
    from plugin_utils import install_timestamp_filter
except ImportError:
    install_timestamp_filter = None

# ---------------------------------------------------------------------------
# OWM API key from IndigoSecrets.py (overrides PluginConfig if present)
# ---------------------------------------------------------------------------
sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from IndigoSecrets import OWM_API_KEY as _SECRETS_OWM_KEY
except ImportError:
    _SECRETS_OWM_KEY = ""

# Try to import Pushover user key from secrets too
try:
    from IndigoSecrets import PUSHOVER_USER_TOKEN as _SECRETS_PUSHOVER_KEY
except ImportError:
    _SECRETS_PUSHOVER_KEY = ""

# Overheat alert email — secrets-first, PluginConfig fallback
try:
    from IndigoSecrets import OVERHEAT_ALERT_EMAIL as _SECRETS_OVERHEAT_EMAIL
except ImportError:
    _SECRETS_OVERHEAT_EMAIL = ""

# Location (lat/lon) — secrets-first, PluginConfig fallback
try:
    from IndigoSecrets import LATITUDE as _SECRETS_LATITUDE
except ImportError:
    _SECRETS_LATITUDE = None
try:
    from IndigoSecrets import LONGITUDE as _SECRETS_LONGITUDE
except ImportError:
    _SECRETS_LONGITUDE = None

# ---------------------------------------------------------------------------
# Plugin modules
# ---------------------------------------------------------------------------
from weather          import WeatherData
from overheat_monitor import OverheatMonitor
from heating_logic    import (
    process_room_temperature,
    validate_configuration,
    calculate_temp_offset,
    update_variable,
    get_variable_value,
    conservatory_special_rules,
    dining_room_special_rules,
    en_suite_special_rules,
    VAR_BOTH_OUT_ID, VAR_GUEST_2_ID, VAR_GUEST_3_ID,
    VAR_AV_OUT_TEMP_HI_ID, VAR_AV_OUT_TEMP_HI_TIME_ID,
    VAR_AV_OUT_TEMP_LO_ID, VAR_AV_OUT_TEMP_LO_TIME_ID,
    VAR_TEMP_OFFSET_ID, VAR_HOME_AWAY_ID, VAR_BOOST_ID,
    DEV_BATHROOM_WINDOW_ID, DEV_BEDROOM_1_WINDOW_ID, DEV_BEDROOM_2_WINDOW_ID,
    DEV_BEDROOM_3_WINDOW_ID, DEV_EN_SUITE_WINDOW_ID,
    DEV_EN_SUITE_FLOOR_HEAT_ID, DEV_EN_SUITE_FLOOR_THERMOSTAT_ID,
    DEV_GARDEN_WINDOW_L_ID, DEV_GARDEN_WINDOW_R_ID, DEV_GARDEN_DOOR_ID,
    DEV_LIVING_ROOM_R_WIN_ID, DEV_LIVING_ROOM_L_WIN_ID,
    DEV_UTILITY_WINDOW_ID, DEV_UTILITY_DOOR_ID,
    DEV_BATHROOM_ID, DEV_BEDROOM_1_ID, DEV_BEDROOM_2_ID, DEV_BEDROOM_3_ID,
    DEV_CONSERVATORY_ID, DEV_DINING_ROOM_ID, DEV_EN_SUITE_ID,
    DEV_HALL_BEDROOM_ID, DEV_HALL_KITCHEN_ID,
    DEV_LIVING_ROOM_DOOR_ID, DEV_LIVING_ROOM_FRONT_ID, DEV_UTILITY_ROOM_ID,
    EN_SUITE_MORNING_TEMP,
    EN_SUITE_WARM_MORNING_THRESHOLD,
    ALL_RADIATOR_IDS,
    RADIATORS_OFF_TEMP,
    TEMP_CHANGE_TOLERANCE,
    is_within_summer_off,
)
import schedules

# Short month labels for summer-window status strings (index 1-12)
_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PLUGIN_NAME     = "EvoHome Heating Controller"
PLUGIN_VERSION  = "1.7.2"
POLL_SLEEP_SECS = 30   # runConcurrentThread inner sleep


def _safe_float(value, default=0.0):
    """Coerce a config value to float, falling back to default on blank/non-numeric input.
    Config textfields come back as strings (and can be blank), so float() must be guarded."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default=None):
    """Coerce a config value to int, returning default on blank/non-numeric input."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _atomic_write_json(path, obj, **dump_kwargs):
    """Write JSON to path atomically (temp file + os.replace).

    A crash or power loss mid-write must never leave a half-written file that the
    reader then trusts (a truncated plugin_state.json would silently drop an active
    24h force-on; a truncated setpoint cache would make every room re-log). os.replace
    is atomic on the same filesystem, so the reader always sees either the old file
    or the fully-written new one.
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, **dump_kwargs)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

# Ecowitt sensor device IDs come entirely from PluginConfig.xml
# (ecowittDeviceId = outdoor, ecowittIndoorDeviceId = indoor). A blank field
# simply skips that section — no hard-coded install-specific device id defaults.

# Solcast solar forecast variables are looked up BY NAME
# ("solcast_today_kwh" / "solcast_tomorrow_kwh") at the read site — no hard-coded
# ids, so a recreated or absent variable can never break the header.

# Legacy cache file paths (Python Scripts folder — migrate on first run).
# Overheat history migration was retired in v1.4 (Indigo 2025.1 install no
# longer exists; one-time migration already completed for this user).
_OLD_SETPOINT_CACHE = "/Library/Application Support/Perceptive Automation/Python Scripts/Radiator_setpoint_cache.json"
_OLD_WEATHER_CACHE  = "/Library/Application Support/Perceptive Automation/Python Scripts/Radiator_weather_cache.json"

# Daily log file handles (module-level so they survive across _tick() calls)
_heating_log_fh  = None
_changes_log_fh  = None
_log_date        = None


_LOG_LEVELS = {
    "INFO":    logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR":   logging.ERROR,
    "DEBUG":   logging.DEBUG,
    "CRITICAL": logging.CRITICAL,
}


def _to_level(level):
    """Translate a string log level to a Python logging int.

    indigo.server.log()'s level= expects a logging int; a STRING is silently
    ignored and the line is logged as Info. Callers throughout this plugin pass
    string levels ('WARNING'/'ERROR'), so translate here at the single choke point.
    """
    if isinstance(level, str):
        return _LOG_LEVELS.get(level.upper(), logging.INFO)
    return level


def _log(message, level="INFO"):
    """Log with timestamp to Indigo event log."""
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=_to_level(level))


def _wind_compass(degrees):
    """Convert wind bearing (degrees) to 16-point compass label."""
    try:
        labels = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        return labels[round(float(degrees) / 22.5) % 16]
    except (ValueError, TypeError):
        return "?"


# ===========================================================================
class Plugin(indigo.PluginBase):
# ===========================================================================

    def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
        super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs)

        # A saved dialog stores this as the string "false"/"true"; bool("false") is
        # truthy, so coerce by value (matching the showDebugInfo coercion) rather than
        # by truthiness. Missing/true -> enabled.
        self.timestamp_enabled = str(plugin_prefs.get("timestampEnabled", True)).strip().lower() \
            not in ("false", "0", "no", "off")
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

        # Library check happens here (not startup()) so a missing dependency
        # aborts before any half-initialised state is created.
        self._check_libraries()

        self.debug = str(plugin_prefs.get("showDebugInfo", "false")).lower() == "true"

        # Data directory for JSON persistence and log files
        self.data_dir = self._get_data_dir()

        # ----------------------------------------------------------------
        # All mutable state in self.store (never use global variables)
        # ----------------------------------------------------------------
        self.store = {}

        # Poll timer
        self.store["last_heating_cycle"] = 0.0

        # Clock hour of the last hourly event-log dump (header + full room
        # table). Tracked by clock hour rather than gating on minute == 0 so
        # the dump cannot be lost to cycle drift — see _run_heating_cycle.
        self.store["last_header_hour"] = None

        # Mode flags (read from Indigo variables each cycle)
        self.store["is_away"]     = False
        self.store["is_boost"]    = False
        self.store["is_both_out"] = False
        self.store["is_guest_2"]  = False
        self.store["is_guest_3"]  = False

        # Timed boost state (new requirement: 1h/2h boost for 4 living rooms)
        self.store["timed_boost_active"]  = False
        self.store["timed_boost_expiry"]  = None   # datetime object or None
        self.store["timed_boost_hours"]   = 0      # 1 or 2

        # Whole-house summer shut-off: 24h force-on override state.
        # When active, the seasonal lockout yields and normal heating resumes
        # until the expiry datetime, then auto-reverts to summer-off.
        self.store["summer_force_active"] = False
        self.store["summer_force_expiry"] = None   # datetime object or None

        # En Suite morning schedule (auto 22°C 06:00-09:59, cancelled by window open)
        self.store["en_suite_morning_active"]           = False
        self.store["en_suite_morning_cancelled_date"]   = None  # "YYYY-MM-DD"
        self.store["en_suite_morning_cancelled_reason"] = None

        # Per-room setpoint + message cache (replaces _last_setpoints/_last_messages globals)
        self.store["last_setpoints"] = {}  # {room_name: float}
        self.store["last_messages"]  = {}  # {room_name: int}

        # Per-run log accumulation buffers (replaces _log_buffer/_changes_buffer globals)
        self.store["log_buffer"]     = []
        self.store["changes_buffer"] = []

        # Snow forecast cache (updated each heating cycle)
        self.store["snow_forecast"]  = []

        # Plugin modules — fully initialised in startup()
        self.weather  = None
        self.overheat = None

        # Active event triggers — populated by triggerStartProcessing / triggerStopProcessing
        self.event_triggers = {}

        # Serialises the per-cycle log buffer between the runConcurrentThread cycle
        # and menu-thread callbacks that temporarily swap it (menuForceFullLog), so
        # menu output can't leak into the daily log or clobber a live cycle's lines.
        self._cycle_lock = threading.Lock()

        # Load persisted state from previous run
        self._load_state()

    # -----------------------------------------------------------------------
    # Indigo lifecycle
    # -----------------------------------------------------------------------

    def _run_interval_mins(self):
        """Configured heating-cycle interval in minutes, coerced and clamped to >= 1.

        Config textfields come back as strings (blank after a dialog save), so a bare
        int() would raise on the hot path; a 0 would ZeroDivision the OverheatMonitor
        timers. Route every read of runIntervalMins through here.
        """
        n = _safe_int(self.pluginPrefs.get("runIntervalMins", 5), 5)
        return max(1, n)

    def startup(self):
        _log(f"{PLUGIN_NAME} v{PLUGIN_VERSION} starting")

        run_interval = self._run_interval_mins()

        # OWM API key: IndigoSecrets.py wins over PluginConfig
        owm_key = _SECRETS_OWM_KEY or self.pluginPrefs.get("owmApiKey", "")
        if not owm_key:
            _log("[Startup] No OWM API key found in IndigoSecrets.py or PluginConfig", level="WARNING")

        # Resolve Pushover key
        pushover_key = _SECRETS_PUSHOVER_KEY or self.pluginPrefs.get("pushoverUserKey", "")

        # Weather module
        ecowitt_raw    = self.pluginPrefs.get("ecowittDeviceId", "")
        ecowitt_dev_id = _safe_int(ecowitt_raw, None) if ecowitt_raw else None

        lat = _SECRETS_LATITUDE if _SECRETS_LATITUDE is not None else _safe_float(self.pluginPrefs.get("owmLatitude"), 0.0)
        lon = _SECRETS_LONGITUDE if _SECRETS_LONGITUDE is not None else _safe_float(self.pluginPrefs.get("owmLongitude"), 0.0)

        self.weather = WeatherData(
            api_key        = owm_key,
            cache_path     = os.path.join(self.data_dir, "weather_cache.json"),
            lat            = lat,
            lon            = lon,
            bypass         = self.pluginPrefs.get("weatherBypass", False),
            bypass_temp    = _safe_float(self.pluginPrefs.get("weatherBypassTemp"), 6.0),
            ecowitt_dev_id = ecowitt_dev_id,
        )

        # Overheat monitor
        self.overheat = OverheatMonitor(
            history_path      = os.path.join(self.data_dir, "overheat_history.json"),
            run_interval_mins = run_interval,
        )
        self.overheat.pushover_user_key = pushover_key
        self.overheat.email_address     = (
            _SECRETS_OVERHEAT_EMAIL or self.pluginPrefs.get("alertEmailAddress", "")
        )
        if not self.overheat.email_address:
            _log(
                "No overheat-alert email configured. Set OVERHEAT_ALERT_EMAIL in "
                "IndigoSecrets.py OR fill the Alert Email field in Plugin Preferences.",
                level="ERROR",
            )
        # Wire up Indigo plugin events for overheat alert / all-clear
        self.overheat.event_callback    = self._fire_event

        # Validate Indigo variable IDs before first cycle
        if not validate_configuration():
            _log("[Startup] WARNING: Some Indigo variables are missing — check IDs in heating_logic.py",
                 level="WARNING")

        # Set initial device states
        for dev in indigo.devices.iter("self"):
            self._set_device_initial_state(dev)

        _log(f"{PLUGIN_NAME} ready (cycle every {run_interval} min, poll every {POLL_SLEEP_SECS}s)")
        _log(f"[Summer] {self._summer_status_str()}")

    def shutdown(self):
        global _heating_log_fh, _changes_log_fh
        _log(f"{PLUGIN_NAME} shutting down")
        for fh in (_heating_log_fh, _changes_log_fh):
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass
        _heating_log_fh = None
        _changes_log_fh = None

    def deviceStartComm(self, dev):
        self._set_device_initial_state(dev)

    def deviceStopComm(self, dev):
        pass

    @staticmethod
    def didDeviceCommPropertyChange(oldDevice, newDevice):
        """Suppress unnecessary deviceStopComm/deviceStartComm cycles.

        Devices in this plugin are created and managed internally; there are
        no user-editable pluginProps that justify a comm restart. Returning
        False prevents Indigo from cycling comm on every internal
        replacePluginPropsOnServer write.
        """
        return False

    def closedPrefsConfigUi(self, values_dict, user_cancelled):
        if not user_cancelled:
            self.debug = str(values_dict.get("showDebugInfo", "false")).lower() == "true"
            # Re-init modules with new prefs
            if self.weather:
                owm_key = _SECRETS_OWM_KEY or values_dict.get("owmApiKey", "")
                # Re-resolve coordinates (IndigoSecrets wins) and rebuild the request
                # URL, so a changed key OR location takes effect now — not only after
                # a restart (the URL bakes in key+lat+lon at construction time).
                lat = _SECRETS_LATITUDE if _SECRETS_LATITUDE is not None else _safe_float(values_dict.get("owmLatitude"), self.weather.lat)
                lon = _SECRETS_LONGITUDE if _SECRETS_LONGITUDE is not None else _safe_float(values_dict.get("owmLongitude"), self.weather.lon)
                self.weather.set_credentials(owm_key, lat, lon)
                self.weather.bypass         = values_dict.get("weatherBypass", False)
                self.weather.bypass_temp    = _safe_float(values_dict.get("weatherBypassTemp", 6.0), 6.0)
                ecowitt_raw                 = values_dict.get("ecowittDeviceId", "")
                self.weather.ecowitt_dev_id = _safe_int(ecowitt_raw, None) if ecowitt_raw else None
            if self.overheat:
                self.overheat.pushover_user_key = (
                    _SECRETS_PUSHOVER_KEY or values_dict.get("pushoverUserKey", "")
                )
                self.overheat.email_address = (
                    _SECRETS_OVERHEAT_EMAIL or values_dict.get("alertEmailAddress", "")
                )
                run_interval = max(1, _safe_int(values_dict.get("runIntervalMins", 5), 5))
                self.overheat.run_interval_mins        = run_interval
                self.overheat.critical_duration_cycles = (6 * 60) // run_interval
                self.overheat.all_clear_cycles         = max(2, 30 // run_interval)
            # Force an immediate cycle so any change (interval, sources, alerts)
            # takes effect now rather than at the next scheduled cycle.
            self.store["last_heating_cycle"] = 0.0

    # -----------------------------------------------------------------------
    # Main polling loop
    # -----------------------------------------------------------------------

    def runConcurrentThread(self):
        while True:
            try:
                self._tick(time.time())
            except self.StopThread:
                raise
            except Exception as e:
                # Per-tick isolation: one transient error (blank pref, deleted
                # variable, a bad zone, a weather edge case) must NOT permanently
                # kill the 24/7 heating loop. Log and carry on to the next tick.
                self.logger.exception(f"[Cycle] Unhandled error in heating tick — continuing: {e}")
            try:
                self.sleep(POLL_SLEEP_SECS)
            except self.StopThread:
                raise

    def _tick(self, now):
        """Called every POLL_SLEEP_SECS. Dispatches timed tasks."""
        run_interval_secs = self._run_interval_mins() * 60

        # Summer 24h force-on expiry check (every tick) — revert to shut-off
        self._check_summer_force_expiry()

        # En Suite morning auto-start / auto-cancel (every tick for responsiveness)
        self._check_en_suite_morning()

        # Timed boost expiry check (every tick)
        self._check_timed_boost_expiry()

        # Main heating cycle (time-delta dispatch)
        if now - self.store["last_heating_cycle"] >= run_interval_secs:
            self._run_heating_cycle()
            self.store["last_heating_cycle"] = now

    # -----------------------------------------------------------------------
    # Heating cycle
    # -----------------------------------------------------------------------

    def _run_heating_cycle(self):
        """Run one heating cycle while holding the cycle lock, so a menu-thread
        buffer swap (menuForceFullLog) can't race the per-cycle log buffer."""
        with self._cycle_lock:
            self._run_heating_cycle_body()

    def _run_heating_cycle_body(self):
        """Execute one full heating cycle across all 12 zones."""
        now_dt  = datetime.now()
        hour    = now_dt.hour
        minute  = now_dt.minute

        # Clear per-run buffers
        self.store["log_buffer"]     = []
        self.store["changes_buffer"] = []

        # ----------------------------------------------------------------
        # Whole-house summer shut-off gate
        # ----------------------------------------------------------------
        # When the seasonal window is active (and no 24h force-on override is
        # running) skip the entire normal cycle: every radiator is held at
        # RADIATORS_OFF_TEMP and the En Suite floor heating is off. A concise
        # status line is logged once per clock hour to avoid 5-min spam.
        if self._summer_lockout_active():
            # Reset overheat tracking ONCE on lockout entry: update_room stops being
            # called during lockout, so a room left mid-alert would otherwise keep a
            # stale alert_sent for the whole season.
            if self.overheat and not self.store.get("summer_overheat_cleared"):
                self.overheat.reset_all_tracking()
                self.store["summer_overheat_cleared"] = True
            self._apply_summer_off()
            if self.store.get("last_header_hour") != hour:
                _log(f"[Summer] Whole-house heating OFF for summer — all radiators "
                     f"at {RADIATORS_OFF_TEMP:.0f}degC, En Suite floor heat off. "
                     f"Resumes {self._summer_on_date_str()}.")
                self.store["last_header_hour"] = hour
            self._update_controller_device(None, 0.0)
            return

        # Not in summer lockout — re-arm the one-time reset for the next lockout entry.
        self.store["summer_overheat_cleared"] = False

        # Read Indigo mode variables
        self._read_mode_variables()

        # Update weather (uses cache if fresh) — guard against unexpected
        # exceptions so a transient network failure cannot abort the cycle.
        if self.weather:
            try:
                self.weather.update()
            except Exception as e:
                _log(f"[Weather] update() raised {type(e).__name__}: {e} — using stale data",
                     level="WARNING")

        # Get outdoor temperature and calculate offset
        outdoor_temp  = self.weather.get_outdoor_temp() if self.weather else None
        snow_forecast = self._get_snow_forecast()
        self.store["snow_forecast"] = snow_forecast
        temp_offset   = calculate_temp_offset(outdoor_temp)
        if snow_forecast and self.pluginPrefs.get("snowHeatingEnabled", True):
            snow_boost   = _safe_float(self.pluginPrefs.get("snowHeatingBoost", "1.0"), 1.0)
            temp_offset += snow_boost
            _log(f"[Snow] Forecast detected — applying +{snow_boost:.1f}degC heating boost")
            # Fire only on rising edge (was no snow last cycle, snow this cycle)
            if not self.store.get("_snow_event_fired"):
                self._fire_event("snowForecastDetected")
                self.store["_snow_event_fired"] = True
        elif not snow_forecast:
            self.store["_snow_event_fired"] = False
        update_variable(VAR_TEMP_OFFSET_ID, temp_offset)

        # Update high/low temperature records
        self._update_temp_records(outdoor_temp)

        # Hourly full event-log dump (header + full room table). Fire on the
        # FIRST cycle of each new clock hour rather than gating on minute == 0:
        # the cycle is dispatched on a time-delta and drifts ~10-12s/hour, so a
        # minute == 0 gate is missed for whole days once the phase creeps past
        # the :00 boundary. Tracking the clock hour is immune to that drift and
        # to any runIntervalMins value.
        do_hourly = (self.store.get("last_header_hour") != hour)
        if do_hourly:
            self._log_hourly_header(outdoor_temp, temp_offset)
            self.store["last_header_hour"] = hour

        # Process all 12 rooms
        run_interval = self._run_interval_mins()
        self._process_all_rooms(hour, minute, temp_offset, outdoor_temp, run_interval,
                                force_hourly=do_hourly)

        # Save state
        self.overheat.save_history()
        self._save_setpoint_cache()

        # Write log files
        self._flush_log_buffers(do_hourly)

        # Update heatingController device states
        self._update_controller_device(outdoor_temp, temp_offset)

        if self.debug:
            _log(f"[Debug] Cycle complete — {datetime.now().strftime('%H:%M:%S')}")

    def _safe_process_room(self, **kwargs):
        """Per-room isolation wrapper: one failing zone (missing device, bad sensor
        read) must not abort the remaining zones or the save/flush tail of the cycle."""
        room = kwargs.get("room_name", "?")
        try:
            process_room_temperature(**kwargs)
        except Exception as e:
            _log(f"[Cycle] Room '{room}' processing failed — skipped this cycle: {e}",
                 level="ERROR")

    def _process_all_rooms(self, hour, minute, temp_offset, outdoor_temp, run_interval,
                           force_hourly=False):
        """Dispatch process_room_temperature() for all 12 RAMSES zones.

        force_hourly: when True this is the first cycle of a new clock hour, so
        every room's line is forced to the event log (the hourly full dump),
        regardless of the wall-clock minute.
        """
        guest_2 = self.store["is_guest_2"]
        guest_3 = self.store["is_guest_3"]
        guest_active = guest_2 or guest_3

        # En Suite special rules need access to self.store
        en_suite_rules = functools.partial(en_suite_special_rules, store=self.store)

        common = dict(
            current_hour         = hour,
            current_minute       = minute,
            temp_offset          = temp_offset,
            current_outdoor_temp = outdoor_temp,
            is_away              = self.store["is_away"],
            is_boost             = self.store["is_boost"],
            is_both_out          = self.store["is_both_out"],
            last_setpoints       = self.store["last_setpoints"],
            last_messages        = self.store["last_messages"],
            log_buffer           = self.store["log_buffer"],
            changes_buffer       = self.store["changes_buffer"],
            overheat_monitor     = self.overheat,
            run_interval_mins    = run_interval,
            timed_boost_active   = self.store["timed_boost_active"],
            timed_boost_rooms    = schedules.TIMED_BOOST_ROOMS,
            force_log_override   = force_hourly,
        )

        # 1. Bathroom
        self._safe_process_room(
            room_name      = "Bathroom",
            room_schedule  = schedules.Bathroom,
            guest_schedule = schedules.Bathroom_Guest if guest_active else None,
            window_devices = [DEV_BATHROOM_WINDOW_ID],
            ha_device_id   = DEV_BATHROOM_ID,
            is_guest       = guest_active,
            **common,
        )

        # 2. Bedroom 1
        self._safe_process_room(
            room_name      = "Bedroom 1",
            room_schedule  = schedules.Bedroom_1,
            window_devices = [DEV_BEDROOM_1_WINDOW_ID],
            ha_device_id   = DEV_BEDROOM_1_ID,
            **common,
        )

        # 3. Bedroom 2
        self._safe_process_room(
            room_name      = "Bedroom 2",
            room_schedule  = schedules.Bedroom_2,
            guest_schedule = schedules.Bedroom_2_Guest if guest_2 else None,
            window_devices = [DEV_BEDROOM_2_WINDOW_ID],
            ha_device_id   = DEV_BEDROOM_2_ID,
            is_guest       = guest_2,
            **common,
        )

        # 4. Bedroom 3
        self._safe_process_room(
            room_name      = "Bedroom 3",
            room_schedule  = schedules.Bedroom_3,
            guest_schedule = schedules.Bedroom_3_Guest if guest_3 else None,
            window_devices = [DEV_BEDROOM_3_WINDOW_ID],
            ha_device_id   = DEV_BEDROOM_3_ID,
            is_guest       = guest_3,
            **common,
        )

        # 5. En Suite (with morning schedule special rules + floor heating)
        morning_active = self.store.get("en_suite_morning_active", False)
        self._safe_process_room(
            room_name                  = "En Suite",
            room_schedule              = schedules.En_Suite,
            window_devices             = [DEV_EN_SUITE_WINDOW_ID],
            floor_heat_device          = DEV_EN_SUITE_FLOOR_HEAT_ID,
            special_rules              = en_suite_rules,
            ha_device_id               = DEV_EN_SUITE_ID,
            floor_heat_restore_enabled = morning_active,
            # When morning schedule is active, use 22°C as the overheat baseline
            # so the room is not falsely flagged as overheating below 22°C
            overheat_target_override   = EN_SUITE_MORNING_TEMP if morning_active else None,
            **common,
        )

        # 6. Conservatory
        self._safe_process_room(
            room_name      = "Conservatory",
            room_schedule  = schedules.Conservatory,
            window_devices = [DEV_GARDEN_WINDOW_L_ID, DEV_GARDEN_WINDOW_R_ID],
            door_devices   = [DEV_GARDEN_DOOR_ID],
            special_rules  = conservatory_special_rules,
            ha_device_id   = DEV_CONSERVATORY_ID,
            **common,
        )

        # 7. Dining Room (garden window/door reduces rather than closes valve)
        self._safe_process_room(
            room_name      = "Dining Room",
            room_schedule  = schedules.Dining_Room,
            window_devices = [DEV_GARDEN_WINDOW_L_ID, DEV_GARDEN_WINDOW_R_ID],
            door_devices   = [DEV_GARDEN_DOOR_ID],
            special_rules  = dining_room_special_rules,
            ha_device_id   = DEV_DINING_ROOM_ID,
            **common,
        )

        # 8. Hall Bedroom
        self._safe_process_room(
            room_name     = "Hall Bedroom",
            room_schedule = schedules.Hall_Bedroom,
            ha_device_id  = DEV_HALL_BEDROOM_ID,
            **common,
        )

        # 9. Hall Kitchen
        self._safe_process_room(
            room_name     = "Hall Kitchen",
            room_schedule = schedules.Hall_Kitchen,
            ha_device_id  = DEV_HALL_KITCHEN_ID,
            **common,
        )

        # 10. Living Room Front
        self._safe_process_room(
            room_name      = "Living Room Front",
            room_schedule  = schedules.Living_Room_Front,
            window_devices = [DEV_LIVING_ROOM_L_WIN_ID, DEV_LIVING_ROOM_R_WIN_ID],
            ha_device_id   = DEV_LIVING_ROOM_FRONT_ID,
            **common,
        )

        # 11. Living Room Door
        self._safe_process_room(
            room_name      = "Living Room Door",
            room_schedule  = schedules.Living_Room_Door,
            window_devices = [DEV_LIVING_ROOM_L_WIN_ID, DEV_LIVING_ROOM_R_WIN_ID],
            ha_device_id   = DEV_LIVING_ROOM_DOOR_ID,
            **common,
        )

        # 12. Utility Room
        self._safe_process_room(
            room_name      = "Utility Room",
            room_schedule  = schedules.Utility_Room,
            window_devices = [DEV_UTILITY_WINDOW_ID],
            door_devices   = [DEV_UTILITY_DOOR_ID],
            ha_device_id   = DEV_UTILITY_ROOM_ID,
            **common,
        )

    # -----------------------------------------------------------------------
    # Timed boost
    # -----------------------------------------------------------------------

    def triggerStartProcessing(self, trigger):
        self.event_triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.event_triggers.pop(trigger.id, None)

    def _fire_event(self, event_id):
        """Fire all Indigo triggers configured for this plugin event."""
        try:
            for trigger in self.event_triggers.values():
                if trigger.pluginTypeId == event_id:
                    indigo.trigger.execute(trigger)
        except Exception as e:
            _log(f"[Events] Could not fire {event_id}: {e}", level="WARNING")

    def _start_timed_boost(self, hours):
        """Activate timed boost for 1 or 2 hours on TIMED_BOOST_ROOMS."""
        if self._summer_lockout_active():
            _log("[TimedBoost] Ignored — whole-house summer shut-off is active. "
                 "Use 'Force Heating On (24h)' first if you need heat now.",
                 level="WARNING")
            return
        expiry = datetime.now() + timedelta(hours=hours)
        self.store["timed_boost_active"] = True
        self.store["timed_boost_expiry"] = expiry
        self.store["timed_boost_hours"]  = hours
        rooms  = ", ".join(sorted(schedules.TIMED_BOOST_ROOMS))
        _log(f"[TimedBoost] {hours}h boost started — "
             f"expires at {expiry.strftime('%H:%M')} — rooms: {rooms}")
        self._save_state()
        self._fire_event("timedBoostStarted")

    def _cancel_timed_boost(self, reason="expired"):
        """Cancel timed boost and log reason."""
        if self.store["timed_boost_active"]:
            self.store["timed_boost_active"] = False
            self.store["timed_boost_expiry"] = None
            self.store["timed_boost_hours"]  = 0
            _log(f"[TimedBoost] Cancelled ({reason}) — rooms reverting to schedule")
            self._save_state()
            # Log what the 4 rooms will revert to on the next cycle
            self._log_boost_revert_summary()
            self._fire_event("timedBoostEnded")

    def _check_timed_boost_expiry(self):
        """Cancel timed boost if its expiry datetime has passed."""
        if not self.store["timed_boost_active"]:
            return
        expiry = self.store.get("timed_boost_expiry")
        if expiry and datetime.now() >= expiry:
            self._cancel_timed_boost("timer expired")

    def _log_boost_revert_summary(self):
        """Log what each boosted room will revert to on the next cycle."""
        now_hour = datetime.now().hour
        try:
            outdoor_temp = self.weather.get_outdoor_temp() if self.weather else None
            from heating_logic import calculate_temp_offset
            offset = calculate_temp_offset(outdoor_temp)
            lines = ["[TimedBoost] Revert summary (next cycle setpoints):"]
            for room_name in sorted(schedules.TIMED_BOOST_ROOMS):
                sched_map = {
                    "Dining Room":       schedules.Dining_Room,
                    "Living Room Door":  schedules.Living_Room_Door,
                    "Living Room Front": schedules.Living_Room_Front,
                    "Hall Kitchen":      schedules.Hall_Kitchen,
                }
                sched = sched_map.get(room_name)
                if sched:
                    target = sched[now_hour] + offset
                    lines.append(f"  {room_name:<22s}  -> {target:.0f}degC (schedule + offset)")
            for line in lines:
                _log(line)
        except Exception:
            pass  # non-critical

    # -----------------------------------------------------------------------
    # Whole-house summer shut-off
    # -----------------------------------------------------------------------

    def _summer_enabled(self):
        """True if the summer shut-off feature is switched on in prefs."""
        return str(self.pluginPrefs.get("summerLockoutEnabled", True)).lower() in ("true", "1", "yes")

    def _summer_window(self):
        """Return (start_month, start_day, on_month, on_day) from prefs, coerced.

        Config values round-trip as strings after a dialog save, so every read
        is funnelled through _safe_int with a sensible default."""
        start_m = _safe_int(self.pluginPrefs.get("summerOffStartMonth", 6),  6)
        start_d = _safe_int(self.pluginPrefs.get("summerOffStartDay",   1),  1)
        on_m    = _safe_int(self.pluginPrefs.get("summerOnMonth",       9),  9)
        on_d    = _safe_int(self.pluginPrefs.get("summerOnDay",        30), 30)
        return start_m, start_d, on_m, on_d

    def _summer_lockout_active(self):
        """True when the whole-house shut-off should be enforced right now:
        feature enabled, today inside the off-window, and no 24h force override."""
        if not self._summer_enabled():
            return False
        if self.store.get("summer_force_active"):
            return False
        start_m, start_d, on_m, on_d = self._summer_window()
        return is_within_summer_off(datetime.now().date(), start_m, start_d, on_m, on_d)

    def _summer_on_date_str(self):
        _, _, on_m, on_d = self._summer_window()
        abbr = _MONTH_ABBR[on_m] if 1 <= on_m <= 12 else str(on_m)
        return f"{on_d} {abbr}"

    def _summer_off_start_str(self):
        start_m, start_d, _, _ = self._summer_window()
        abbr = _MONTH_ABBR[start_m] if 1 <= start_m <= 12 else str(start_m)
        return f"{start_d} {abbr}"

    def _summer_status_str(self):
        """One-line human-readable summary of the summer shut-off state."""
        if not self._summer_enabled():
            return "Summer shut-off DISABLED — heating follows the normal schedule year-round"
        if self.store.get("summer_force_active"):
            exp = self.store.get("summer_force_expiry")
            if exp:
                secs = max(0, (exp - datetime.now()).total_seconds())
                hrs  = int(secs // 3600)
                mins = int((secs % 3600) // 60)
                return (f"FORCED ON — full heating for {hrs}h {mins}m more "
                        f"(reverts to summer shut-off {exp.strftime('%a %d %b %H:%M')})")
            return "FORCED ON — full heating (24h override)"
        if self._summer_lockout_active():
            return (f"Summer shut-off ACTIVE — all radiators off, "
                    f"heating resumes {self._summer_on_date_str()}")
        return (f"In-season — heating normal. Summer shut-off runs "
                f"{self._summer_off_start_str()} to {self._summer_on_date_str()}")

    def _apply_summer_off(self):
        """Hold every radiator at RADIATORS_OFF_TEMP and turn the En Suite floor
        heating off. Idempotent — only writes a TRV when its setpoint differs
        from the off temperature or its zone mode has drifted, mirroring the
        W 2349 decision in process_room_temperature() to avoid RAMSES spam."""
        for dev_id in ALL_RADIATOR_IDS:
            try:
                dev = indigo.devices[dev_id]
            except Exception as e:
                _log(f"[Summer] Radiator {dev_id} not found: {e}", level="WARNING")
                continue
            setpoint_str = dev.states.get("setpointHeat", "0")
            available    = setpoint_str not in (None, "null", "None", "", "unavailable", "unknown")
            try:
                before = float(setpoint_str) if available else None
            except (ValueError, TypeError):
                before = None
            zone_mode     = dev.states.get("zoneMode", "")
            not_permanent = (zone_mode != "permanent override")
            changed       = (before is None) or (abs(before - RADIATORS_OFF_TEMP) > TEMP_CHANGE_TOLERANCE)
            if changed or not_permanent:
                try:
                    indigo.thermostat.setHeatSetpoint(dev, value=RADIATORS_OFF_TEMP)
                except Exception as e:
                    _log(f"[Summer] Could not set radiator {dev.name} to "
                         f"{RADIATORS_OFF_TEMP:.0f}degC: {e}", level="WARNING")

        # En Suite floor heating switch off (idempotent on onState)
        try:
            floor = indigo.devices[DEV_EN_SUITE_FLOOR_HEAT_ID]
            if floor.onState:
                indigo.device.turnOff(DEV_EN_SUITE_FLOOR_HEAT_ID)
                _log("[Summer] En Suite floor heating switched OFF")
        except Exception as e:
            _log(f"[Summer] Could not turn off En Suite floor heat: {e}", level="WARNING")

        # Clear any lingering En Suite morning mode so it can't fight the lockout
        if self.store.get("en_suite_morning_active"):
            self.store["en_suite_morning_active"] = False
            self._save_state()

    def _start_summer_force(self, hours=24):
        """Start a 24h force-on: suspend the summer shut-off and resume fully
        normal heating until the expiry, then auto-revert."""
        if not self._summer_enabled():
            _log("[Summer] Force-on requested but the summer shut-off feature is "
                 "disabled — nothing to override.", level="WARNING")
            return
        expiry = datetime.now() + timedelta(hours=hours)
        self.store["summer_force_active"] = True
        self.store["summer_force_expiry"] = expiry
        _log(f"[Summer] Force-on START — full heating restored for {hours}h, "
             f"reverts to summer shut-off at {expiry.strftime('%a %d %b %H:%M')}")
        self._save_state()
        self._fire_event("summerForceStarted")
        # Apply normal heating immediately rather than waiting for the next cycle
        self.store["last_heating_cycle"] = 0.0

    def _cancel_summer_force(self, reason="expired"):
        """End the 24h force-on and (if still in-window) re-assert the shut-off."""
        if self.store.get("summer_force_active"):
            self.store["summer_force_active"] = False
            self.store["summer_force_expiry"] = None
            _log(f"[Summer] Force-on END ({reason}) — {self._summer_status_str()}")
            self._save_state()
            self._fire_event("summerForceEnded")
            # Re-evaluate immediately so the lockout re-applies this cycle
            self.store["last_heating_cycle"] = 0.0

    def _check_summer_force_expiry(self):
        """Cancel the 24h force-on once its expiry datetime has passed."""
        if not self.store.get("summer_force_active"):
            return
        exp = self.store.get("summer_force_expiry")
        if exp and datetime.now() >= exp:
            self._cancel_summer_force("24h timer expired")

    def _log_summer_status(self):
        """Log the current summer shut-off status (menu / on-demand)."""
        _log("=== Summer Shut-off Status ===")
        _log(f"  {self._summer_status_str()}")
        _log(f"  Off window:   {self._summer_off_start_str()} -> {self._summer_on_date_str()} "
             f"(heating returns on the end date)")
        _log(f"  Enabled:      {self._summer_enabled()}")
        _log(f"  Lockout now:  {self._summer_lockout_active()}")
        _log(f"  Force active: {self.store.get('summer_force_active', False)}")

    # -----------------------------------------------------------------------
    # En Suite morning schedule
    # -----------------------------------------------------------------------

    def _check_en_suite_morning(self):
        """
        Auto-start En Suite morning schedule at 06:00 and auto-cancel at 10:00.
        Window-open cancellation is handled inside en_suite_special_rules().

        The plugin owns the floor heating switch completely:
          - Turned ON here at 6am start (so Indigo schedules for this are redundant)
          - Turned OFF here at 10am cancel (so Indigo schedules for this are redundant)
          - Also turned OFF inside process_room_temperature() when window opens

        Cheap-out fast paths so the check is essentially free outside the
        morning window — _tick() runs this every POLL_SLEEP_SECS.
        """
        # Summer shut-off in force (and not overridden) — never start the
        # morning floor-heat boost; the lockout owns the En Suite.
        if self._summer_lockout_active():
            return

        hour  = datetime.now().hour

        # Outside 06:00-10:00 and 00:00 (midnight reset) the rest of the
        # function is a no-op — return early to avoid pointless work.
        in_morning_window = 6 <= hour < 10
        is_midnight       = hour == 0
        is_after_window   = hour == 10  # one-shot 10am cancel band
        if not (in_morning_window or is_midnight or is_after_window):
            return

        today = datetime.now().strftime("%Y-%m-%d")

        # Auto-start: 06:00-09:59, not already active, not cancelled by window today
        cancelled_today = self.store.get("en_suite_morning_cancelled_date") == today
        if (6 <= hour < 10
                and not self.store["en_suite_morning_active"]
                and not cancelled_today):

            # Warm-morning skip: if outdoor temperature is at/above the warm
            # threshold at activation time, the en suite room is already
            # comfortable and the floor is not cold to the touch. Skip the
            # 22degC morning slot entirely — radiator stays off, floor switch
            # stays off, floor thermostat is not touched. en_suite_special_rules
            # forces the radiator to RADIATORS_OFF_TEMP for the remaining 06-10
            # hours (otherwise the schedule's 19-20degC values would still run).
            outdoor_temp = self.weather.get_outdoor_temp() if self.weather else None
            if (outdoor_temp is not None
                    and outdoor_temp >= EN_SUITE_WARM_MORNING_THRESHOLD):
                self.store["en_suite_morning_cancelled_date"]   = today
                self.store["en_suite_morning_cancelled_reason"] = "warm_outdoor"
                _log(
                    f"[EnSuiteMorning] 6am — outdoor {outdoor_temp:.1f}degC >= "
                    f"{EN_SUITE_WARM_MORNING_THRESHOLD:.0f}degC: skipping morning "
                    f"schedule (radiator + floor heat stay off)"
                )
                self._save_state()
                self._fire_event("enSuiteMorningCancelled")
                return  # Don't activate; don't touch floor switch or thermostat

            self.store["en_suite_morning_active"]           = True
            self.store["en_suite_morning_cancelled_reason"] = None
            _log("[EnSuiteMorning] 6am — starting 22degC morning schedule")
            # Turn on floor heating switch immediately (don't wait for next heating cycle)
            try:
                indigo.device.turnOn(DEV_EN_SUITE_FLOOR_HEAT_ID)
                _log("[EnSuiteMorning] Floor heating switch turned ON")
            except Exception as e:
                _log(f"[EnSuiteMorning] Floor heat switch on error: {e}", level="ERROR")
            # Set floor thermostat to heat mode at 14degC — self-regulates until switch off
            try:
                therm = indigo.devices[DEV_EN_SUITE_FLOOR_THERMOSTAT_ID]
                indigo.thermostat.setHvacMode(therm, value=indigo.kHvacMode.Heat)
                indigo.thermostat.setHeatSetpoint(therm, value=14.0)
                _log("[EnSuiteMorning] Floor thermostat set to Heat / 14degC")
            except Exception as e:
                _log(f"[EnSuiteMorning] Floor thermostat set error: {e}", level="ERROR")
            self._save_state()
            self._fire_event("enSuiteMorningStarted")

        # Auto-cancel at 10am
        if self.store["en_suite_morning_active"] and hour >= 10:
            self.store["en_suite_morning_active"]           = False
            self.store["en_suite_morning_cancelled_reason"] = "10am_expired"
            _log("[EnSuiteMorning] 10am — reverting to normal schedule")
            # Turn off floor heating immediately
            try:
                indigo.device.turnOff(DEV_EN_SUITE_FLOOR_HEAT_ID)
                _log("[EnSuiteMorning] Floor heating switch turned OFF")
            except Exception as e:
                _log(f"[EnSuiteMorning] Floor heat off error: {e}", level="ERROR")
            self._save_state()
            self._fire_event("enSuiteMorningCancelled")

        # Reset cancelled_date at midnight so tomorrow auto-starts again.
        # Must persist to disk — otherwise a plugin restart before the next
        # _save_state() call would restore the cancelled_date and silently
        # block tomorrow's auto-start.
        if hour == 0 and self.store.get("en_suite_morning_cancelled_date") not in (None, today):
            self.store["en_suite_morning_cancelled_date"] = None
            self._save_state()

    # -----------------------------------------------------------------------
    # Device state helpers
    # -----------------------------------------------------------------------

    def _set_device_initial_state(self, dev):
        if dev.deviceTypeId == "heatingController":
            dev.updateStateOnServer("activeMode", value="Starting")
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def _update_controller_device(self, outdoor_temp, temp_offset):
        """Push current status into heatingController device states."""
        dev = self._find_device("heatingController")
        if not dev:
            return

        # Determine active mode display string (priority order)
        if self.store.get("summer_force_active"):
            mode = "Forced On (summer)"
        elif self._summer_lockout_active():
            mode = "Summer Off"
        elif self.store["is_away"]:
            mode = "Away"
        elif self.store["is_both_out"]:
            mode = "Both-Out"
        elif self.store["timed_boost_active"]:
            hrs  = self.store.get("timed_boost_hours", 1)
            mode = f"Timed Boost {hrs}h"
        elif self.store["is_boost"]:
            mode = "Boost"
        elif self.store["en_suite_morning_active"]:
            mode = "En Suite Morning"
        else:
            mode = "Schedule"

        overheating = self.overheat.get_overheating_rooms() if self.overheat else []
        overheat_str = ", ".join(overheating) if overheating else "None"

        expiry_str = ""
        if self.store["timed_boost_active"] and self.store.get("timed_boost_expiry"):
            expiry_str = self.store["timed_boost_expiry"].strftime("%H:%M")

        now_str = datetime.now().strftime("%d %b %Y %H:%M:%S")

        dev.updateStatesOnServer([
            {"key": "activeMode",          "value": mode},
            {"key": "outdoorTempC",        "value": f"{outdoor_temp:.1f}" if outdoor_temp is not None else "N/A"},
            {"key": "tempOffset",          "value": f"{temp_offset:.1f}"},
            {"key": "isAway",              "value": str(self.store["is_away"])},
            {"key": "isBothOut",           "value": str(self.store["is_both_out"])},
            {"key": "isBoost",             "value": str(self.store["is_boost"])},
            {"key": "timedBoostActive",    "value": str(self.store["timed_boost_active"])},
            {"key": "timedBoostExpiry",    "value": expiry_str},
            {"key": "enSuiteMorningActive","value": str(self.store["en_suite_morning_active"])},
            {"key": "summerStatus",        "value": self._summer_status_str()},
            {"key": "overheatRooms",       "value": overheat_str},
            {"key": "lastCycleTime",       "value": now_str},
            {"key": "lastUpdate",          "value": now_str},
        ])

        img = (indigo.kStateImageSel.SensorTripped
               if overheating
               else indigo.kStateImageSel.SensorOn)
        dev.updateStateImageOnServer(img)

    def _find_device(self, type_id):
        """Return the first enabled device of the given typeId, or None."""
        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId == type_id and dev.enabled:
                return dev
        return None

    # -----------------------------------------------------------------------
    # Mode variable reading
    # -----------------------------------------------------------------------

    def _read_mode_variables(self):
        """Read current mode flags from Indigo variables into self.store."""
        self.store["is_away"]     = get_variable_value(VAR_HOME_AWAY_ID,  "false").lower() == "true"
        self.store["is_boost"]    = get_variable_value(VAR_BOOST_ID,      "no").lower()    == "yes"
        self.store["is_both_out"] = get_variable_value(VAR_BOTH_OUT_ID,   "no").lower()    == "yes"
        self.store["is_guest_2"]  = get_variable_value(VAR_GUEST_2_ID,    "false").lower() == "true"
        self.store["is_guest_3"]  = get_variable_value(VAR_GUEST_3_ID,    "false").lower() == "true"

    # -----------------------------------------------------------------------
    # Temperature records
    # -----------------------------------------------------------------------

    def _update_temp_records(self, current_temp):
        """Update all-time outdoor temperature high/low Indigo variables.

        Defaults are inverted so the FIRST reading on a fresh install always
        sets both records: high default -999 (so any reading is higher),
        low default +999 (so any reading is lower).
        """
        if current_temp is None:
            return
        try:
            av_high = float(get_variable_value(VAR_AV_OUT_TEMP_HI_ID, "-999"))
            av_low  = float(get_variable_value(VAR_AV_OUT_TEMP_LO_ID,  "999"))
        except (ValueError, TypeError):
            return

        ts = datetime.now().strftime("%A %d %b %Y %H:%M:%S")
        if current_temp <= av_low:
            update_variable(VAR_AV_OUT_TEMP_LO_ID,      current_temp)
            update_variable(VAR_AV_OUT_TEMP_LO_TIME_ID, ts)
        if current_temp >= av_high:
            update_variable(VAR_AV_OUT_TEMP_HI_ID,      current_temp)
            update_variable(VAR_AV_OUT_TEMP_HI_TIME_ID, ts)

    # -----------------------------------------------------------------------
    # Snow forecast helper
    # -----------------------------------------------------------------------

    def _get_snow_forecast(self):
        """Return snow forecast list, or [] if disabled / no snow expected."""
        if not self.weather:
            return []
        hours = _safe_int(self.pluginPrefs.get("snowForecastHours", "12"), 12)
        return self.weather.get_snow_forecast(hours)

    # -----------------------------------------------------------------------
    # Menu: force full log output
    # -----------------------------------------------------------------------

    def menuForceFullLog(self, valuesDict=None, typeId=None):
        """Immediately emit a full weather + status log, as if it were the top of the hour.

        Uses a throw-away buffer so the menu output never leaks into the next
        cycle's daily log file via _flush_log_buffers().
        """
        if self.weather:
            try:
                self.weather.update()
            except Exception as e:
                _log(f"[Weather] update() raised {type(e).__name__}: {e}", level="WARNING")
        outdoor_temp  = self.weather.get_outdoor_temp() if self.weather else None
        snow_forecast = self._get_snow_forecast()
        # Don't pollute the running cycle's snow_forecast cache from a menu click
        temp_offset   = calculate_temp_offset(outdoor_temp)
        if snow_forecast and self.pluginPrefs.get("snowHeatingEnabled", True):
            temp_offset += _safe_float(self.pluginPrefs.get("snowHeatingBoost", "1.0"), 1.0)

        # Swap the log buffer for a throwaway one for the duration of this call.
        # Hold the cycle lock so a concurrent heating cycle can't observe the
        # throwaway buffer (menu lines leaking into the daily log) or have its own
        # buffer clobbered by the restore.
        with self._cycle_lock:
            saved_buf = self.store["log_buffer"]
            saved_snow = self.store.get("snow_forecast")
            self.store["log_buffer"]    = []
            self.store["snow_forecast"] = snow_forecast
            try:
                self._log_hourly_header(outdoor_temp, temp_offset, menu_mode=True)
            finally:
                self.store["log_buffer"]    = saved_buf
                self.store["snow_forecast"] = saved_snow

    # -----------------------------------------------------------------------
    # Hourly log header
    # -----------------------------------------------------------------------

    def _log_hourly_header(self, outdoor_temp, temp_offset, menu_mode=False):
        """Log full weather header and mode status.

        menu_mode=True: omits the room-processing header lines — used by the
        'Show Full Weather Log' menu item which has no per-room table to
        precede.

        Split into focused helpers (_b emits to both Indigo log and the
        per-cycle log buffer):
          _log_weather_section  - Ecowitt + OWM + Solcast + snow + offset + suntimes
          _log_records_section  - all-time high/low
          _log_modes_section    - per-mode active/inactive + overheat status
        """
        def _b(msg, level="INFO"):
            formatted = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
            indigo.server.log(formatted, level=_to_level(level))
            self.store["log_buffer"].append(formatted)

        _b("")
        _b(f"Todays Weather on {datetime.now().strftime('%A %d %B %Y at %H:%M:%S')}")
        _b("--------------------------------------------------")
        _b("")

        self._log_weather_section(_b, outdoor_temp, temp_offset)
        _b("")
        self._log_records_section(_b)
        _b("")
        self._log_modes_section(_b)

        if not menu_mode:
            _b("")
            _b("Processing room temperature updates...")
            _b("")
            _b("Room               Current   Schedule    New     Action")
            _b("=" * 80)

    def _log_weather_section(self, _b, outdoor_temp, temp_offset):
        """Emit weather lines: Ecowitt (active) + OWM (reference) + Solcast + snow + offset."""
        # Active outdoor temperature source
        using_ecowitt = bool(
            self.weather and not self.weather.bypass and self.weather.ecowitt_dev_id
        )
        if using_ecowitt and outdoor_temp is not None:
            _b(f"Ecowitt Temperature           {outdoor_temp:.1f}degC  (active source)")
        elif outdoor_temp is not None:
            _b(f"OWM Temperature               {outdoor_temp:.1f}degC  (active source)")

        # Ecowitt outdoor humidity (uses the CONFIGURED outdoor device, not a hardcoded ID)
        if using_ecowitt:
            try:
                out_dev = indigo.devices[self.weather.ecowitt_dev_id]
                out_hum = out_dev.states.get("humidity")
                if out_hum is not None:
                    _b(f"Ecowitt Humidity              {out_hum}%  (outdoor)")
            except Exception as exc:
                self.logger.debug(f"Ecowitt outdoor humidity lookup failed (dev_id={self.weather.ecowitt_dev_id}): {exc}")

        # Ecowitt indoor sensor — pressure + indoor temp/humidity (configurable ID).
        # Default None (matching the outdoor path + the empty XML default): a blank
        # field simply skips the indoor section rather than reading a device id that
        # only exists on the developer's install.
        indoor_id_raw = self.pluginPrefs.get("ecowittIndoorDeviceId", "")
        indoor_id     = _safe_int(indoor_id_raw, None) if indoor_id_raw else None
        if indoor_id:
            try:
                in_dev  = indigo.devices[indoor_id]
                press   = in_dev.states.get("pressureRelative")
                p_unit  = in_dev.states.get("pressureRelativeUnit", "hPa")
                in_temp = in_dev.states.get("temperature")
                in_hum  = in_dev.states.get("humidity")
                if press is not None:
                    _b(f"Ecowitt Pressure              {press}{p_unit}")
                if in_temp is not None and in_hum is not None:
                    _b(f"Ecowitt Indoor                {in_temp}degC  /  {in_hum}% humidity")
            except Exception as exc:
                self.logger.debug(f"Ecowitt indoor sensor lookup failed (dev_id={indoor_id}): {exc}")

        # OWM current conditions (reference — always shown for cloud/wind/UV context)
        if self.weather and self.weather.current:
            w          = self.weather
            desc       = w.get_current("weather", [{}])[0].get("description", "N/A").title()
            temp_c     = w.get_current("temp",       "N/A")
            feels      = w.get_current("feels_like", "N/A")
            humid      = w.get_current("humidity",   "N/A")
            wind_spd   = w.get_current("wind_speed")   # m/s
            wind_deg   = w.get_current("wind_deg")
            wind_gust  = w.get_current("wind_gust")    # m/s, optional
            uvi        = w.get_current("uvi")

            _b(f"OWM Conditions                {desc}")
            rain_1h = (w.get_current("rain") or {}).get("1h")
            snow_1h = (w.get_current("snow") or {}).get("1h")
            if snow_1h:
                _b(f"OWM Precipitation             {float(snow_1h):.1f}mm/h  SNOW")
            elif rain_1h:
                _b(f"OWM Precipitation             {float(rain_1h):.1f}mm/h  rain")
            if not using_ecowitt:
                _b(f"OWM Temperature               {temp_c}degC  (feels like {feels}degC)")
                _b(f"OWM Humidity                  {humid}%")

            # Wind speed + direction
            if wind_spd is not None:
                try:
                    mph        = float(wind_spd) * 2.237
                    compass    = _wind_compass(wind_deg)
                    wind_str   = f"{mph:.1f}mph {compass}"
                    if wind_gust is not None:
                        wind_str += f"  (gusting {float(wind_gust) * 2.237:.1f}mph)"
                    _b(f"OWM Wind                      {wind_str}")
                except Exception:
                    pass

            # UV Index
            if uvi is not None:
                _b(f"OWM UV Index                  {uvi}")

            # Solcast solar forecast — looked up BY NAME (not hard-coded id) so a
            # recreated/absent variable can't break it, and it silently omits the
            # lines on any install where the Solcast feed isn't present.
            try:
                sol_today    = get_variable_value("solcast_today_kwh")
                sol_tomorrow = get_variable_value("solcast_tomorrow_kwh")
                if sol_today is not None and sol_tomorrow is not None:
                    _b(f"Solcast Today                 {float(sol_today):.1f} kWh")
                    _b(f"Solcast Tomorrow              {float(sol_tomorrow):.1f} kWh")
            except Exception:
                pass
        else:
            _b("OpenWeatherMap data unavailable")

        # Snow forecast warning (from cached forecast computed during cycle)
        snow_forecast = self.store.get("snow_forecast", [])
        if snow_forecast:
            first     = snow_forecast[0]
            total_mm  = sum(h["mm"] for h in snow_forecast)
            count     = len(snow_forecast)
            mm_str    = f", {total_mm:.1f}mm total" if total_mm > 0.0 else ""
            _b(f"** SNOW FORECAST: starts {first['time_str']}, "
               f"{count}h affected{mm_str} **", level="WARNING")

        if outdoor_temp is not None:
            _b(f"Temperature Offset            {temp_offset:+.1f}degC")

        # Sunrise / Sunset (OWM — shown last)
        if self.weather:
            try:
                sunrise_ts = self.weather.get_current("sunrise")
                sunset_ts  = self.weather.get_current("sunset")
                if sunrise_ts and sunset_ts:
                    sr = datetime.fromtimestamp(int(sunrise_ts)).strftime("%H:%M")
                    ss = datetime.fromtimestamp(int(sunset_ts)).strftime("%H:%M")
                    _b(f"Sunrise / Sunset              {sr}  /  {ss}")
            except Exception:
                pass

    def _log_records_section(self, _b):
        """Emit all-time outdoor temperature high/low records."""
        try:
            hi_raw = get_variable_value(VAR_AV_OUT_TEMP_HI_ID, None)
            lo_raw = get_variable_value(VAR_AV_OUT_TEMP_LO_ID, None)
            hi_t   = get_variable_value(VAR_AV_OUT_TEMP_HI_TIME_ID, "N/A")
            lo_t   = get_variable_value(VAR_AV_OUT_TEMP_LO_TIME_ID, "N/A")
            hi_str = f"{float(hi_raw):.1f}degC" if hi_raw not in (None, "") else "no record yet"
            lo_str = f"{float(lo_raw):.1f}degC" if lo_raw not in (None, "") else "no record yet"
            _b(f"Outside Temp Highest          {hi_str} on {hi_t}")
            _b(f"Outside Temp Lowest           {lo_str} on {lo_t}")
        except Exception:
            pass

    def _log_modes_section(self, _b):
        """Emit one line per active mode + overheat status."""
        for flag, label in [
            (self.store["is_away"],                 "AWAY"),
            (self.store["is_boost"],                "GLOBAL BOOST"),
            (self.store["timed_boost_active"],      "TIMED BOOST"),
            (self.store["is_both_out"],             "BOTH OUT"),
            (self.store["en_suite_morning_active"], "EN SUITE MORNING"),
        ]:
            status = "Active" if flag else "Inactive"
            _b(f"{label:<30}{status}")
        _b(f"{'OVERHEAT PREVENTION':<30}Enabled")

    # -----------------------------------------------------------------------
    # Log file management
    # -----------------------------------------------------------------------

    def _ensure_logs(self):
        """Open daily log file handles, rotating when date changes."""
        global _heating_log_fh, _changes_log_fh, _log_date
        today = datetime.now().strftime("%Y-%m-%d")
        if _log_date == today:
            return
        for fh in (_heating_log_fh, _changes_log_fh):
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass
        log_dir = os.path.join(self.data_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        _heating_log_fh = open(os.path.join(log_dir, f"radiator_{today}.log"), "a", encoding="utf-8")
        _changes_log_fh = open(os.path.join(log_dir, f"changes_{today}.log"),  "a", encoding="utf-8")
        _log_date = today
        self._purge_old_logs(log_dir, days=14)

    def _purge_old_logs(self, log_dir, days=14):
        """Delete log files older than `days` days."""
        cutoff = time.time() - days * 86400
        try:
            for fname in os.listdir(log_dir):
                if not fname.endswith(".log"):
                    continue
                fpath = os.path.join(log_dir, fname)
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
        except Exception as e:
            _log(f"[Logs] Purge error: {e}", level="WARNING")

    def _flush_log_buffers(self, is_hourly):
        """Write accumulated log and changes buffers to daily log files.

        is_hourly: True on the first cycle of a new clock hour. On the hourly
        dump the table header is already present in log_buffer (added by
        _log_hourly_header), so it is not written again; on non-hourly cycles
        the header line is prepended here so each block is self-describing.
        """
        try:
            self._ensure_logs()
        except Exception as e:
            _log(f"[Logs] Could not open log files: {e}", level="WARNING")
            return

        log_buf     = self.store["log_buffer"]
        changes_buf = self.store["changes_buffer"]

        if log_buf and _heating_log_fh:
            try:
                if not is_hourly:
                    _heating_log_fh.write("Room               Current   Schedule    New     Action\n")
                    _heating_log_fh.write("=" * 80 + "\n")
                _heating_log_fh.write(datetime.now().strftime("%d %b %Y at %H:%M:%S") + "\n")
                for line in log_buf:
                    _heating_log_fh.write(line + "\n")
                _heating_log_fh.write("\n")
                _heating_log_fh.flush()
            except Exception as e:
                _log(f"[Logs] Heating log write error: {e}", level="WARNING")

        if changes_buf and _changes_log_fh:
            try:
                for line in changes_buf:
                    _changes_log_fh.write(line + "\n")
                _changes_log_fh.flush()
            except Exception as e:
                _log(f"[Logs] Changes log write error: {e}", level="WARNING")

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _get_data_dir(self):
        """Return (and create if needed) the plugin's data directory."""
        data_dir = os.path.join(
            indigo.server.getInstallFolderPath(),
            "Preferences", "Plugins",
            "com.clives.indigoplugin.evohomecontrol"
        )
        os.makedirs(data_dir, exist_ok=True)
        return data_dir

    def _load_state(self):
        """
        Load persisted state on startup:
          - Setpoint cache (with one-time migration from Python Scripts dir)
          - Timed boost + En Suite morning state (plugin_state.json)
        """
        # --- Setpoint cache ---
        cache_path = os.path.join(self.data_dir, "setpoint_cache.json")
        if not os.path.exists(cache_path) and os.path.exists(_OLD_SETPOINT_CACHE):
            try:
                shutil.copy2(_OLD_SETPOINT_CACHE, cache_path)
                indigo.server.log("[EvoHomeControl] Migrated setpoint cache from Python Scripts dir")
            except Exception as e:
                indigo.server.log(f"[EvoHomeControl] Setpoint cache migration failed: {e}", level=_to_level("WARNING"))

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and "setpoints" in raw:
                self.store["last_setpoints"] = raw.get("setpoints", {})
                self.store["last_messages"]  = raw.get("messages",  {})
            else:
                self.store["last_setpoints"] = raw if isinstance(raw, dict) else {}
                self.store["last_messages"]  = {}
        except (OSError, ValueError):
            pass  # fresh start — all rooms log once on first cycle

        # --- Timed boost + En Suite morning (plugin_state.json) ---
        state_path = os.path.join(self.data_dir, "plugin_state.json")
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)

            # Restore timed boost only if expiry is still in the future
            expiry_str = st.get("timed_boost_expiry")
            if expiry_str:
                try:
                    expiry = datetime.fromisoformat(expiry_str)
                    if expiry > datetime.now():
                        self.store["timed_boost_active"] = True
                        self.store["timed_boost_expiry"] = expiry
                        self.store["timed_boost_hours"]  = st.get("timed_boost_hours", 1)
                        _log(f"[TimedBoost] Restored from state — expires {expiry.strftime('%H:%M')}")
                except (ValueError, TypeError):
                    # Malformed/legacy value, or a tz-aware string compared to a
                    # naive now() — ignore the stale boost rather than crash startup.
                    pass

            # Restore summer 24h force-on only if expiry is still in the future
            force_expiry_str = st.get("summer_force_expiry")
            if force_expiry_str:
                try:
                    fexp = datetime.fromisoformat(force_expiry_str)
                    if fexp > datetime.now():
                        self.store["summer_force_active"] = True
                        self.store["summer_force_expiry"] = fexp
                        _log(f"[Summer] Force-on restored from state — "
                             f"reverts {fexp.strftime('%a %d %b %H:%M')}")
                except (ValueError, TypeError):
                    pass

            # Restore En Suite morning only if still within 06:00-09:59 AND the
            # summer shut-off is not active. Re-assert floor heat ON to match the
            # restored mode — but never during summer lockout, which holds the floor
            # heating OFF (re-asserting it on here would fight the lockout).
            if (st.get("en_suite_morning_active") and 6 <= datetime.now().hour < 10
                    and not self._summer_lockout_active()):
                self.store["en_suite_morning_active"] = True
                _log("[EnSuiteMorning] Restored from state — still within morning window")
                try:
                    indigo.device.turnOn(DEV_EN_SUITE_FLOOR_HEAT_ID)
                except Exception as e:
                    _log(f"[EnSuiteMorning] Could not re-assert floor heat: {e}", level="WARNING")

            self.store["en_suite_morning_cancelled_date"] = st.get("en_suite_morning_cancelled_date")

        except (OSError, ValueError, TypeError, AttributeError) as e:
            # Missing/corrupt/legacy plugin_state.json must never crash __init__ —
            # a malformed file just means a fresh start for the persisted flags.
            _log(f"[State] Could not restore plugin_state.json ({type(e).__name__}) — fresh start",
                 level="WARNING")

    def _save_state(self):
        """Persist timed boost and En Suite morning state to plugin_state.json."""
        state_path = os.path.join(self.data_dir, "plugin_state.json")
        expiry     = self.store.get("timed_boost_expiry")
        force_exp  = self.store.get("summer_force_expiry")
        data = {
            "timed_boost_active":           self.store["timed_boost_active"],
            "timed_boost_expiry":           expiry.isoformat() if expiry else None,
            "timed_boost_hours":            self.store.get("timed_boost_hours", 0),
            "summer_force_active":          self.store.get("summer_force_active", False),
            "summer_force_expiry":          force_exp.isoformat() if force_exp else None,
            "en_suite_morning_active":      self.store["en_suite_morning_active"],
            "en_suite_morning_cancelled_date": self.store.get("en_suite_morning_cancelled_date"),
        }
        try:
            _atomic_write_json(state_path, data, indent=2)
        except OSError as e:
            _log(f"[State] Write error: {e}", level="WARNING")

    def _save_setpoint_cache(self):
        """Persist per-room setpoint and message cache."""
        cache_path = os.path.join(self.data_dir, "setpoint_cache.json")
        try:
            _atomic_write_json(cache_path, {
                "setpoints": self.store["last_setpoints"],
                "messages":  self.store["last_messages"],
            })
        except OSError as e:
            _log(f"[SetpointCache] Write error: {e}", level="WARNING")

    # -----------------------------------------------------------------------
    # Library guard
    # -----------------------------------------------------------------------

    def _check_libraries(self):
        """Abort startup if required third-party libraries are missing."""
        missing = []
        try:
            import requests  # noqa
        except ImportError:
            missing.append("requests")
        if missing:
            fix = f"pip3 install {' '.join(missing)}"
            indigo.server.log(
                f"[EvoHomeControl] Missing libraries: {', '.join(missing)} — "
                f"Fix: open Terminal and run: {fix}",
                isError=True
            )
            raise RuntimeError(f"Missing libraries: {', '.join(missing)}")

    # -----------------------------------------------------------------------
    # Action callbacks
    # -----------------------------------------------------------------------

    def actionStartTimedBoost1h(self, action):
        """Action: Start 1-hour timed boost on Dining/Living/HallKitchen."""
        self._start_timed_boost(hours=1)

    def actionStartTimedBoost2h(self, action):
        """Action: Start 2-hour timed boost on Dining/Living/HallKitchen."""
        self._start_timed_boost(hours=2)

    def actionCancelTimedBoost(self, action):
        """Action: Cancel timed boost immediately."""
        self._cancel_timed_boost(reason="manual cancel")

    def actionForceHeatingOn24h(self, action):
        """Action: Force whole-house heating on for 24h (override summer shut-off)."""
        self._start_summer_force(hours=24)

    def actionCancelForcedHeating(self, action):
        """Action: Cancel the 24h force-on and revert to the summer shut-off."""
        self._cancel_summer_force(reason="manual cancel")

    def actionShowSummerStatus(self, action):
        """Action: Log the whole-house summer shut-off status (dashboard-invocable)."""
        self._log_summer_status()

    def actionRunCycleNow(self, action):
        """Action: Force an immediate heating cycle."""
        _log("[Action] Manual heating cycle triggered")
        self.store["last_heating_cycle"] = 0.0  # force _tick() to run cycle next poll

    def actionSetAwayMode(self, action):
        """Action: Set or clear away mode via Indigo variable.

        Forces an immediate heating cycle so the change applies now rather
        than waiting up to runIntervalMins minutes for the next scheduled cycle.
        """
        active = str(action.props.get("awayActive", "true")).lower() == "true"
        update_variable(VAR_HOME_AWAY_ID, "true" if active else "false")
        _log(f"[Action] Away mode {'activated' if active else 'deactivated'} — forcing immediate cycle")
        self.store["last_heating_cycle"] = 0.0

    # -----------------------------------------------------------------------
    # Menu callbacks
    # -----------------------------------------------------------------------

    def menuStartTimedBoost1h(self, values_dict=None, type_id=None):
        """Menu: Start 1-hour timed boost."""
        self._start_timed_boost(hours=1)
        return True

    def menuStartTimedBoost2h(self, values_dict=None, type_id=None):
        """Menu: Start 2-hour timed boost."""
        self._start_timed_boost(hours=2)
        return True

    def menuCancelTimedBoost(self, values_dict=None, type_id=None):
        """Menu: Cancel timed boost immediately."""
        self._cancel_timed_boost(reason="menu cancel")
        return True

    def menuForceHeatingOn24h(self, values_dict=None, type_id=None):
        """Menu: Force whole-house heating on for 24h (override summer shut-off)."""
        self._start_summer_force(hours=24)
        return True

    def menuCancelForcedHeating(self, values_dict=None, type_id=None):
        """Menu: Cancel the 24h force-on and revert to the summer shut-off."""
        self._cancel_summer_force(reason="menu cancel")
        return True

    def menuShowSummerStatus(self, values_dict=None, type_id=None):
        """Menu: Show the whole-house summer shut-off status."""
        self._log_summer_status()
        return True

    def menuRunCycleNow(self, values_dict=None, type_id=None):
        """Menu: Run heating cycle now."""
        _log("[Menu] Manual heating cycle triggered")
        self.store["last_heating_cycle"] = 0.0
        return True

    def menuShowStatus(self, values_dict=None, type_id=None):
        """Menu: Show current heating controller status."""
        _log("=== EvoHome Heating Controller Status ===")
        _log(f"  Away mode:           {self.store['is_away']}")
        _log(f"  Both-Out mode:       {self.store['is_both_out']}")
        _log(f"  Global boost:        {self.store['is_boost']}")
        _log(f"  Timed boost active:  {self.store['timed_boost_active']}")
        if self.store["timed_boost_active"]:
            expiry = self.store.get("timed_boost_expiry")
            _log(f"  Timed boost expiry:  {expiry.strftime('%H:%M') if expiry else 'N/A'}")
        _log(f"  En Suite morning:    {self.store['en_suite_morning_active']}")
        _log(f"  Summer shut-off:     {self._summer_status_str()}")
        if self.overheat:
            rooms = self.overheat.get_overheating_rooms()
            if not rooms:
                _log("  Overheating rooms:   None")
            else:
                _log("  Overheating rooms:")
                for room in rooms:
                    data        = self.overheat.history.get(room, {})
                    current     = data.get("current_temp")
                    setpoint    = data.get("target_temp")
                    cur_str = f"{current:.1f}degC" if current is not None else "N/A"
                    set_str = f"{setpoint:.1f}degC" if setpoint is not None else "N/A"
                    _log(f"    {room:<24}  temp: {cur_str:<10}  setpoint: {set_str}")
        return True

    def menuShowOverheatStatus(self, values_dict=None, type_id=None):
        """Menu: Show overheat monitor status."""
        if self.overheat:
            for line in self.overheat.get_status_summary().split("\n"):
                _log(line)
        else:
            _log("[OverheatMonitor] Not yet initialised")
        return True

    def menuShowTimedBoostStatus(self, values_dict=None, type_id=None):
        """Menu: Show timed boost status."""
        if self.store["timed_boost_active"]:
            expiry = self.store.get("timed_boost_expiry")
            hrs    = self.store.get("timed_boost_hours", 0)
            rooms  = ", ".join(sorted(schedules.TIMED_BOOST_ROOMS))
            _log(f"[TimedBoost] ACTIVE — {hrs}h boost, "
                 f"expires {expiry.strftime('%H:%M') if expiry else 'N/A'}")
            _log(f"[TimedBoost] Rooms: {rooms}")
        else:
            _log("[TimedBoost] Not active")
        return True

    def menuToggleDebug(self, values_dict=None, type_id=None):
        """Menu: Toggle debug logging.

        PluginPrefs round-trip as strings — store "true"/"false" for consistency.
        """
        self.debug = not self.debug
        self.pluginPrefs["showDebugInfo"] = "true" if self.debug else "false"
        _log(f"[Debug] Debug logging {'enabled' if self.debug else 'disabled'}")
        return True

    def showPluginInfo(self, values_dict=None, type_id=None):
        """Menu: Re-display startup banner and current status."""
        extras = [("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF")]
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=extras)
        else:
            _log(f"{self.pluginDisplayName} v{self.pluginVersion}")
            for label, value in extras:
                _log(f"  {label} {value}")
        # Also show current status
        self.menuShowStatus(values_dict, type_id)

    def menuToggleTimestamps(self, values_dict=None, type_id=None):
        self.timestamp_enabled = not self.timestamp_enabled
        self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")
        return True
