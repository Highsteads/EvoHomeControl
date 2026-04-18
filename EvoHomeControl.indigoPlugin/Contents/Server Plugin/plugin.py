#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: EvoHome Heating Controller — Indigo plugin main class
#              Converted from EvoHome_Radiator_Update.py v8.14
# Author:      CliveS & Claude Sonnet 4.6
# Date:        15-04-2026
# Version:     1.0

import os
import sys
import json
import shutil
import time
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

# ---------------------------------------------------------------------------
# OWM API key from secrets.py (overrides PluginConfig if present)
# ---------------------------------------------------------------------------
sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from secrets import OWM_API_KEY as _SECRETS_OWM_KEY
except ImportError:
    _SECRETS_OWM_KEY = ""

# Try to import Pushover user key from secrets too
try:
    from secrets import PUSHOVER_USER_TOKEN as _SECRETS_PUSHOVER_KEY
except ImportError:
    _SECRETS_PUSHOVER_KEY = ""

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
    OUTDOOR_TEMP_TRIGGER,
    EN_SUITE_MORNING_TEMP,
)
import schedules

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PLUGIN_NAME     = "EvoHome Heating Controller"
PLUGIN_VERSION  = "1.0"
POLL_SLEEP_SECS = 30   # runConcurrentThread inner sleep

# Legacy cache file paths (Python Scripts folder — migrate on first run)
_OLD_SETPOINT_CACHE = "/Library/Application Support/Perceptive Automation/Python Scripts/Radiator_setpoint_cache.json"
_OLD_WEATHER_CACHE  = "/Library/Application Support/Perceptive Automation/Python Scripts/Radiator_weather_cache.json"
_OLD_OVERHEAT_HIST  = "/Library/Application Support/Perceptive Automation/Indigo 2025.1/Logs/overheat_history.json"

# Daily log file handles (module-level so they survive across _tick() calls)
_heating_log_fh  = None
_changes_log_fh  = None
_log_date        = None


def _log(message, level="INFO"):
    """Log with timestamp to Indigo event log."""
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", level=level)


# ===========================================================================
class Plugin(indigo.PluginBase):
# ===========================================================================

    def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
        super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs)

        if log_startup_banner:
            log_startup_banner(plugin_id, plugin_display_name, plugin_version)
        else:
            indigo.server.log(f"{plugin_display_name} v{plugin_version} starting")

        self.debug = plugin_prefs.get("showDebugInfo", False)

        # Data directory for JSON persistence and log files
        self.data_dir = self._get_data_dir()

        # ----------------------------------------------------------------
        # All mutable state in self.store (never use global variables)
        # ----------------------------------------------------------------
        self.store = {}

        # Poll timer
        self.store["last_heating_cycle"] = 0.0

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

        # Plugin modules — fully initialised in startup()
        self.weather  = None
        self.overheat = None

        # Load persisted state from previous run
        self._load_state()

    # -----------------------------------------------------------------------
    # Indigo lifecycle
    # -----------------------------------------------------------------------

    def startup(self):
        self._check_libraries()
        _log(f"{PLUGIN_NAME} v{PLUGIN_VERSION} starting")

        run_interval = int(self.pluginPrefs.get("runIntervalMins", 5))

        # OWM API key: secrets.py wins over PluginConfig
        owm_key = _SECRETS_OWM_KEY or self.pluginPrefs.get("owmApiKey", "")
        if not owm_key:
            _log("[Startup] No OWM API key found in secrets.py or PluginConfig", level="WARNING")

        # Resolve Pushover key
        pushover_key = _SECRETS_PUSHOVER_KEY or self.pluginPrefs.get("pushoverUserKey", "")

        # Weather module
        self.weather = WeatherData(
            api_key      = owm_key,
            cache_path   = os.path.join(self.data_dir, "weather_cache.json"),
            lat          = float(self.pluginPrefs.get("owmLatitude",    54.882)),
            lon          = float(self.pluginPrefs.get("owmLongitude",  -1.818)),
            bypass       = self.pluginPrefs.get("weatherBypass", True),
            bypass_temp  = float(self.pluginPrefs.get("weatherBypassTemp", 6.0)),
        )

        # Overheat monitor
        self.overheat = OverheatMonitor(
            history_path      = os.path.join(self.data_dir, "overheat_history.json"),
            run_interval_mins = run_interval,
        )
        self.overheat.pushover_user_key = pushover_key
        self.overheat.email_address     = self.pluginPrefs.get(
            "alertEmailAddress", "overheat-alert@strudwick.co.uk"
        )

        # Validate Indigo variable IDs before first cycle
        if not validate_configuration():
            _log("[Startup] WARNING: Some Indigo variables are missing — check IDs in heating_logic.py",
                 level="WARNING")

        # Set initial device states
        for dev in indigo.devices.iter("self"):
            self._set_device_initial_state(dev)

        _log(f"{PLUGIN_NAME} ready (cycle every {run_interval} min, poll every {POLL_SLEEP_SECS}s)")

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

    def closedPrefsConfigUi(self, values_dict, user_cancelled):
        if not user_cancelled:
            self.debug = values_dict.get("showDebugInfo", False)
            # Re-init modules with new prefs
            if self.weather:
                owm_key = _SECRETS_OWM_KEY or values_dict.get("owmApiKey", "")
                self.weather.api_key     = owm_key
                self.weather.bypass      = values_dict.get("weatherBypass", True)
                self.weather.bypass_temp = float(values_dict.get("weatherBypassTemp", 6.0))
            if self.overheat:
                self.overheat.pushover_user_key = (
                    _SECRETS_PUSHOVER_KEY or values_dict.get("pushoverUserKey", "")
                )
                self.overheat.email_address = values_dict.get(
                    "alertEmailAddress", "overheat-alert@strudwick.co.uk"
                )
                run_interval = int(values_dict.get("runIntervalMins", 5))
                self.overheat.run_interval_mins        = run_interval
                self.overheat.critical_duration_cycles = (6 * 60) // run_interval
                self.overheat.all_clear_cycles         = max(2, 30 // run_interval)

    # -----------------------------------------------------------------------
    # Main polling loop
    # -----------------------------------------------------------------------

    def runConcurrentThread(self):
        try:
            while True:
                now = time.time()
                self._tick(now)
                self.sleep(POLL_SLEEP_SECS)
        except self.StopThread:
            pass

    def _tick(self, now):
        """Called every POLL_SLEEP_SECS. Dispatches timed tasks."""
        run_interval_secs = int(self.pluginPrefs.get("runIntervalMins", 5)) * 60

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
        """Execute one full heating cycle across all 12 zones."""
        now_dt  = datetime.now()
        hour    = now_dt.hour
        minute  = now_dt.minute

        # Clear per-run buffers
        self.store["log_buffer"]     = []
        self.store["changes_buffer"] = []

        # Read Indigo mode variables
        self._read_mode_variables()

        # Update weather (uses cache if fresh)
        if self.weather:
            self.weather.update()

        # Get outdoor temperature and calculate offset
        outdoor_temp = self.weather.get_outdoor_temp() if self.weather else None
        temp_offset  = calculate_temp_offset(outdoor_temp)
        update_variable(VAR_TEMP_OFFSET_ID, temp_offset)

        # Update high/low temperature records
        self._update_temp_records(outdoor_temp)

        # Hourly full log header (minute == 0)
        if minute == 0:
            self._log_hourly_header(outdoor_temp, temp_offset)

        # Process all 12 rooms
        run_interval = int(self.pluginPrefs.get("runIntervalMins", 5))
        self._process_all_rooms(hour, minute, temp_offset, outdoor_temp, run_interval)

        # Save state
        self.overheat.save_history()
        self._save_setpoint_cache()

        # Write log files
        self._flush_log_buffers(minute)

        # Update heatingController device states
        self._update_controller_device(outdoor_temp, temp_offset)

        if self.debug:
            _log(f"[Debug] Cycle complete — {datetime.now().strftime('%H:%M:%S')}")

    def _process_all_rooms(self, hour, minute, temp_offset, outdoor_temp, run_interval):
        """Dispatch process_room_temperature() for all 12 RAMSES zones."""
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
        )

        # 1. Bathroom
        process_room_temperature(
            room_name      = "Bathroom",
            room_schedule  = schedules.Bathroom,
            guest_schedule = schedules.Bathroom_Guest if guest_active else None,
            window_devices = [DEV_BATHROOM_WINDOW_ID],
            ha_device_id   = DEV_BATHROOM_ID,
            is_guest       = guest_active,
            **common,
        )

        # 2. Bedroom 1
        process_room_temperature(
            room_name      = "Bedroom 1",
            room_schedule  = schedules.Bedroom_1,
            window_devices = [DEV_BEDROOM_1_WINDOW_ID],
            ha_device_id   = DEV_BEDROOM_1_ID,
            **common,
        )

        # 3. Bedroom 2
        process_room_temperature(
            room_name      = "Bedroom 2",
            room_schedule  = schedules.Bedroom_2,
            guest_schedule = schedules.Bedroom_2_Guest if guest_2 else None,
            window_devices = [DEV_BEDROOM_2_WINDOW_ID],
            ha_device_id   = DEV_BEDROOM_2_ID,
            is_guest       = guest_2,
            **common,
        )

        # 4. Bedroom 3
        process_room_temperature(
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
        process_room_temperature(
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
        process_room_temperature(
            room_name      = "Conservatory",
            room_schedule  = schedules.Conservatory,
            window_devices = [DEV_GARDEN_WINDOW_L_ID, DEV_GARDEN_WINDOW_R_ID],
            door_devices   = [DEV_GARDEN_DOOR_ID],
            special_rules  = conservatory_special_rules,
            ha_device_id   = DEV_CONSERVATORY_ID,
            **common,
        )

        # 7. Dining Room (garden window/door reduces rather than closes valve)
        process_room_temperature(
            room_name      = "Dining Room",
            room_schedule  = schedules.Dining_Room,
            window_devices = [DEV_GARDEN_WINDOW_L_ID, DEV_GARDEN_WINDOW_R_ID],
            door_devices   = [DEV_GARDEN_DOOR_ID],
            special_rules  = dining_room_special_rules,
            ha_device_id   = DEV_DINING_ROOM_ID,
            **common,
        )

        # 8. Hall Bedroom
        process_room_temperature(
            room_name     = "Hall Bedroom",
            room_schedule = schedules.Hall_Bedroom,
            ha_device_id  = DEV_HALL_BEDROOM_ID,
            **common,
        )

        # 9. Hall Kitchen
        process_room_temperature(
            room_name     = "Hall Kitchen",
            room_schedule = schedules.Hall_Kitchen,
            ha_device_id  = DEV_HALL_KITCHEN_ID,
            **common,
        )

        # 10. Living Room Front
        process_room_temperature(
            room_name      = "Living Room Front",
            room_schedule  = schedules.Living_Room_Front,
            window_devices = [DEV_LIVING_ROOM_L_WIN_ID, DEV_LIVING_ROOM_R_WIN_ID],
            ha_device_id   = DEV_LIVING_ROOM_FRONT_ID,
            **common,
        )

        # 11. Living Room Door
        process_room_temperature(
            room_name      = "Living Room Door",
            room_schedule  = schedules.Living_Room_Door,
            window_devices = [DEV_LIVING_ROOM_L_WIN_ID, DEV_LIVING_ROOM_R_WIN_ID],
            ha_device_id   = DEV_LIVING_ROOM_DOOR_ID,
            **common,
        )

        # 12. Utility Room
        process_room_temperature(
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

    def _start_timed_boost(self, hours):
        """Activate timed boost for 1 or 2 hours on TIMED_BOOST_ROOMS."""
        expiry = datetime.now() + timedelta(hours=hours)
        self.store["timed_boost_active"] = True
        self.store["timed_boost_expiry"] = expiry
        self.store["timed_boost_hours"]  = hours
        rooms  = ", ".join(sorted(schedules.TIMED_BOOST_ROOMS))
        _log(f"[TimedBoost] {hours}h boost started — "
             f"expires at {expiry.strftime('%H:%M')} — rooms: {rooms}")
        self._save_state()

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
        """
        hour  = datetime.now().hour
        today = datetime.now().strftime("%Y-%m-%d")

        # Auto-start: 06:00-09:59, not already active, not cancelled by window today
        cancelled_today = self.store.get("en_suite_morning_cancelled_date") == today
        if (6 <= hour < 10
                and not self.store["en_suite_morning_active"]
                and not cancelled_today):
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

        # Reset cancelled_date at midnight so tomorrow auto-starts again
        if hour == 0 and self.store.get("en_suite_morning_cancelled_date") not in (None, today):
            self.store["en_suite_morning_cancelled_date"] = None

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
        if self.store["is_away"]:
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
        """Update all-time outdoor temperature high/low Indigo variables."""
        if current_temp is None:
            return
        try:
            av_high = float(get_variable_value(VAR_AV_OUT_TEMP_HI_ID, "999"))
            av_low  = float(get_variable_value(VAR_AV_OUT_TEMP_LO_ID, "-999"))
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
    # Hourly log header
    # -----------------------------------------------------------------------

    def _log_hourly_header(self, outdoor_temp, temp_offset):
        """Log full weather header and mode status (minute == 0 only)."""
        buf = self.store["log_buffer"]

        def _b(msg, level="INFO"):
            formatted = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
            indigo.server.log(formatted, level=level)
            buf.append(formatted)

        _b("")
        _b(f"Todays Weather on {datetime.now().strftime('%A %d %B %Y at %H:%M:%S')}")
        _b("--------------------------------------------------")
        _b("")

        # High/low records
        try:
            hi   = float(get_variable_value(VAR_AV_OUT_TEMP_HI_ID,      "0"))
            lo   = float(get_variable_value(VAR_AV_OUT_TEMP_LO_ID,       "0"))
            hi_t = get_variable_value(VAR_AV_OUT_TEMP_HI_TIME_ID, "N/A")
            lo_t = get_variable_value(VAR_AV_OUT_TEMP_LO_TIME_ID, "N/A")
            _b(f"Outside Temp High             {hi}degC on {hi_t}")
            _b(f"Outside Temp Low              {lo}degC on {lo_t}")
        except Exception:
            pass
        _b("")

        # OWM current conditions
        if self.weather and self.weather.current:
            w = self.weather
            desc    = w.get_current("weather", [{}])[0].get("description", "N/A").title()
            temp_c  = w.get_current("temp", "N/A")
            feels   = w.get_current("feels_like", "N/A")
            humid   = w.get_current("humidity", "N/A")
            _b(f"OWMap Conditions              {desc}")
            _b(f"OWMap Temperature             {temp_c}degC  (feels like {feels}degC)")
            _b(f"OWMap Humidity                {humid}%")
        else:
            _b("OpenWeatherMap data unavailable")

        if outdoor_temp is not None:
            _b(f"Temperature Offset            {temp_offset:+.1f}degC  (outdoor: {outdoor_temp:.1f}degC)")
        _b("")

        # Active mode summary
        modes_on  = []
        modes_off = []
        for flag, label in [
            (self.store["is_away"],              "AWAY"),
            (self.store["is_boost"],             "GLOBAL BOOST"),
            (self.store["timed_boost_active"],   "TIMED BOOST"),
            (self.store["is_both_out"],          "BOTH OUT"),
            (self.store["en_suite_morning_active"], "EN SUITE MORNING"),
        ]:
            (modes_on if flag else modes_off).append(label)
        _b(f"Active modes: {', '.join(modes_on) or 'None'}"
           f"  |  Inactive: {', '.join(modes_off)}")
        _b("OVERHEAT prevention enabled")
        _b("")

        _b("Processing room temperature updates...")
        _b("")
        _b("Room               Current   Schedule    New     Action")
        _b("=" * 80)

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

    def _flush_log_buffers(self, minute):
        """Write accumulated log and changes buffers to daily log files."""
        try:
            self._ensure_logs()
        except Exception as e:
            _log(f"[Logs] Could not open log files: {e}", level="WARNING")
            return

        log_buf     = self.store["log_buffer"]
        changes_buf = self.store["changes_buffer"]

        if log_buf and _heating_log_fh:
            try:
                if minute != 0:
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
                indigo.server.log(f"[EvoHomeControl] Setpoint cache migration failed: {e}", level="WARNING")

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

        # --- Overheat history migration ---
        hist_path = os.path.join(self.data_dir, "overheat_history.json")
        if not os.path.exists(hist_path) and os.path.exists(_OLD_OVERHEAT_HIST):
            try:
                shutil.copy2(_OLD_OVERHEAT_HIST, hist_path)
                indigo.server.log("[EvoHomeControl] Migrated overheat history from Logs dir")
            except Exception as e:
                indigo.server.log(f"[EvoHomeControl] Overheat history migration failed: {e}", level="WARNING")

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
                except ValueError:
                    pass

            # Restore En Suite morning only if still within 06:00-09:59
            if st.get("en_suite_morning_active") and 6 <= datetime.now().hour < 10:
                self.store["en_suite_morning_active"] = True
                _log("[EnSuiteMorning] Restored from state — still within morning window")

            self.store["en_suite_morning_cancelled_date"] = st.get("en_suite_morning_cancelled_date")

        except (OSError, ValueError):
            pass  # no previous state — fresh start

    def _save_state(self):
        """Persist timed boost and En Suite morning state to plugin_state.json."""
        state_path = os.path.join(self.data_dir, "plugin_state.json")
        expiry     = self.store.get("timed_boost_expiry")
        data = {
            "timed_boost_active":           self.store["timed_boost_active"],
            "timed_boost_expiry":           expiry.isoformat() if expiry else None,
            "timed_boost_hours":            self.store.get("timed_boost_hours", 0),
            "en_suite_morning_active":      self.store["en_suite_morning_active"],
            "en_suite_morning_cancelled_date": self.store.get("en_suite_morning_cancelled_date"),
        }
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            _log(f"[State] Write error: {e}", level="WARNING")

    def _save_setpoint_cache(self):
        """Persist per-room setpoint and message cache."""
        cache_path = os.path.join(self.data_dir, "setpoint_cache.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "setpoints": self.store["last_setpoints"],
                    "messages":  self.store["last_messages"],
                }, f)
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
        try:
            import pytz  # noqa
        except ImportError:
            missing.append("pytz")
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

    def actionRunCycleNow(self, action):
        """Action: Force an immediate heating cycle."""
        _log("[Action] Manual heating cycle triggered")
        self.store["last_heating_cycle"] = 0.0  # force _tick() to run cycle next poll

    def actionSetAwayMode(self, action):
        """Action: Set or clear away mode via Indigo variable."""
        active = action.props.get("awayActive", "true").lower() == "true"
        update_variable(VAR_HOME_AWAY_ID, "true" if active else "false")
        _log(f"[Action] Away mode {'activated' if active else 'deactivated'}")

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
        if self.overheat:
            rooms = self.overheat.get_overheating_rooms()
            _log(f"  Overheating rooms:   {', '.join(rooms) if rooms else 'None'}")
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
        """Menu: Toggle debug logging."""
        self.debug = not self.debug
        self.pluginPrefs["showDebugInfo"] = self.debug
        _log(f"[Debug] Debug logging {'enabled' if self.debug else 'disabled'}")
        return True

    def showPluginInfo(self, values_dict=None, type_id=None):
        """Menu: Re-display startup banner and current status."""
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion)
        else:
            _log(f"{self.pluginDisplayName} v{self.pluginVersion}")
        # Also show current status
        self.menuShowStatus(values_dict, type_id)
