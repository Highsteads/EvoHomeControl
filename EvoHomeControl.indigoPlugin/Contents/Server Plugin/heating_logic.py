#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    heating_logic.py
# Description: Core heating logic — room processing, overheat detection, special rules
#              Ported from EvoHome_Radiator_Update.py v8.14
# Author:      CliveS & Claude Sonnet 4.6
# Date:        15-04-2026
# Version:     1.0

from datetime import datetime as dt

import indigo  # noqa — available in plugin context

import schedules

# ---------------------------------------------------------------------------
# DEVICE IDs — contact sensors and radiators (RAMSES ESP zones)
# ---------------------------------------------------------------------------

# Windows / Doors / Floor heating
DEV_BATHROOM_WINDOW_ID     = 470834502
DEV_BEDROOM_1_WINDOW_ID    = 398804951
DEV_BEDROOM_2_WINDOW_ID    = 431560729
DEV_BEDROOM_3_WINDOW_ID    = 980886156
DEV_EN_SUITE_WINDOW_ID     = 566450110   # contact state: False = open
DEV_EN_SUITE_FLOOR_HEAT_ID = 69786879    # "En Suite Floor Heating Switch"
DEV_GARDEN_WINDOW_L_ID     = 682946229
DEV_GARDEN_WINDOW_R_ID     = 495298132
DEV_GARDEN_DOOR_ID         = 1901554452
DEV_SLIDE_DOOR_ID          = 837399077
DEV_LIVING_ROOM_R_WIN_ID   = 988734901
DEV_LIVING_ROOM_L_WIN_ID   = 1085940495
DEV_UTILITY_WINDOW_ID      = 181963388
DEV_UTILITY_DOOR_ID        = 1627038252

# Radiators — RAMSES ESP thermostat devices (zone index in comment)
DEV_BATHROOM_ID            = 1886011292  # Zone  5
DEV_BEDROOM_1_ID           = 545736860   # Zone  1
DEV_BEDROOM_2_ID           = 72187173    # Zone  4
DEV_BEDROOM_3_ID           = 1006487156  # Zone  7
DEV_CONSERVATORY_ID        = 430908914   # Zone  2
DEV_DINING_ROOM_ID         = 82851831    # Zone  9
DEV_EN_SUITE_ID            = 766064835   # Zone  6
DEV_HALL_BEDROOM_ID        = 228383134   # Zone 10
DEV_HALL_KITCHEN_ID        = 1138438804  # Zone  3
DEV_LIVING_ROOM_DOOR_ID    = 963505712   # Zone  0
DEV_LIVING_ROOM_FRONT_ID   = 110516814   # Zone 11
DEV_UTILITY_ROOM_ID        = 1376483274  # Zone  8

# ---------------------------------------------------------------------------
# Indigo variable IDs
# ---------------------------------------------------------------------------
VAR_BOTH_OUT_ID            = 901855906
VAR_GUEST_2_ID             = 127473296
VAR_GUEST_3_ID             = 785954068
VAR_AV_OUT_TEMP_HI_ID      = 1680034901
VAR_AV_OUT_TEMP_HI_TIME_ID = 1668580986
VAR_AV_OUT_TEMP_LO_ID      = 94565580
VAR_AV_OUT_TEMP_LO_TIME_ID = 50347848
VAR_TEMP_OFFSET_ID         = 1079983379
VAR_HOME_AWAY_ID           = 437369347
VAR_BOOST_ID               = 1067614282

# ---------------------------------------------------------------------------
# TEMPERATURE CONSTANTS
# ---------------------------------------------------------------------------
RADIATORS_OFF_TEMP          =  8.0
OUTDOOR_TEMP_TRIGGER        = 14.0
WARM_WEATHER_TRIGGER        =  9.0
WARM_WEATHER_REDUCTION      =  2.0
WARM_WEATHER_TRIGGER_LOW    =  8.0
WARM_WEATHER_REDUCTION_LOW  =  1.0
AWAY_TEMP                   = 14.0
BOTH_OUT_OFFSET             = -4
MAX_ROOM_TEMP               = 30.0
TEMP_CHANGE_TOLERANCE       =  0.1

# ---------------------------------------------------------------------------
# OVERHEAT PREVENTION CONSTANTS
# ---------------------------------------------------------------------------
OVERHEAT_TRIGGER_THRESHOLD  =  0.25
OVERHEAT_RECOVERY_THRESHOLD =  0.15
OVERHEAT_RATE_THRESHOLD     =  0.15  # degC per 15 min (normalised)
OVERHEAT_USE_RADIATOR_OFF   =  False
OVERHEAT_BACKOFF            =  6.0
OVERHEAT_MIN_SETPOINT       = 12.0
OVERHEAT_MIN_OFF_CYCLES     =  9     # 45 min at 5-min interval (scaled by run_interval_mins at call site)
OVERHEAT_REOPEN_FLOOR       =  0.3
OVERHEAT_PREDICTIVE_MARGIN  =  0.1
OVERHEAT_COAST_MARGIN       =  0.5

# Per-room coast margins
ROOM_COAST_MARGINS = {
    "Bathroom":          0.0,
    "En Suite":          0.0,
    "Conservatory":      0.8,
    "Bedroom 2":         0.8,
    "Hall Bedroom":      0.7,
    "Hall Kitchen":      0.6,
    "Living Room Front": 0.7,
    "Living Room Door":  0.7,
    "Utility Room":      0.6,
}

# Per-room rate thresholds (degC per 15 min)
ROOM_SPECIFIC_RATE_THRESHOLDS = {
    "En Suite":          0.20,
    "Bathroom":          0.20,
    "Conservatory":      0.05,
    "Bedroom 2":         0.01,
    "Bedroom 3":         0.01,
    "Hall Bedroom":      0.03,
    "Hall Kitchen":      0.01,
    "Living Room Front": 0.01,
    "Utility Room":      0.01,
}

# Rooms excluded from complex overheat logic (stateless threshold check only)
OVERHEAT_EXCLUDED_ROOMS = {"Bedroom 3"}

# Message codes that trigger an immediate event-log entry on non-hourly runs
# 1=window open  2=both windows  3=door open  4=door+window  5=slide door closed
# 17=overheat (radiator contributing)  19=window/door closed  20=window open (reduced)
# 21=door open (reduced)  22=En Suite morning schedule
# 23=above target (passive warmth — solar/internal gain, valve has been off 3+ cycles)
ALERT_LOG_MESSAGES = {1, 2, 3, 4, 5, 17, 19, 20, 21, 22}

# En Suite morning schedule temperature
EN_SUITE_MORNING_TEMP = 22.0

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def _log(message, level="INFO", log_buffer=None):
    """Log to Indigo event log and optionally to a buffer list."""
    formatted = f"[{dt.now().strftime('%H:%M:%S')}] {message}"
    indigo.server.log(formatted, level=level)
    if log_buffer is not None:
        log_buffer.append(formatted)


def validate_configuration():
    """Validate that all required devices and variables exist. Returns True on success."""
    errors = []
    required_vars = [
        (VAR_BOTH_OUT_ID,   "Both_Out"),
        (VAR_HOME_AWAY_ID,  "Away"),
        (VAR_BOOST_ID,      "Boost"),
        (VAR_TEMP_OFFSET_ID,"varTempOffset"),
        (VAR_GUEST_2_ID,    "varGuest2"),
        (VAR_GUEST_3_ID,    "varGuest3"),
    ]
    for var_id, var_name in required_vars:
        try:
            indigo.variables[var_id]
        except Exception:
            errors.append(f"Missing required variable: {var_name} (ID: {var_id})")
    for error in errors:
        indigo.server.log(error, level="ERROR")
    return len(errors) == 0


def update_variable(var_id_or_name, value):
    """Update Indigo variable by ID or name. All values stored as strings."""
    try:
        indigo.variable.updateValue(var_id_or_name, str(value))
    except Exception as e:
        indigo.server.log(f"[heating_logic] Error updating variable {var_id_or_name}: {e}", level="ERROR")


def get_variable_value(var_id_or_name, default=None):
    """Get Indigo variable value by ID or name, with default fallback."""
    try:
        return indigo.variables[var_id_or_name].value
    except Exception:
        return default


def calculate_temp_offset(outdoor_temp):
    """
    Return temperature offset applied to all room setpoints.
    Graduated reduction based on outdoor temperature:
      > WARM_WEATHER_TRIGGER     -> -WARM_WEATHER_REDUCTION  (-2°C)
      > WARM_WEATHER_TRIGGER_LOW -> -WARM_WEATHER_REDUCTION_LOW (-1°C)
      otherwise                  -> 0.0
    """
    if outdoor_temp is None:
        return 0.0
    if outdoor_temp > WARM_WEATHER_TRIGGER:
        return -WARM_WEATHER_REDUCTION
    if outdoor_temp > WARM_WEATHER_TRIGGER_LOW:
        return -WARM_WEATHER_REDUCTION_LOW
    return 0.0


def _contact_is_open(dev_id):
    """
    Return True if a contact sensor device indicates 'open'.
    Handles Zigbee2MQTT contact sensors (states["contact"]: False = open)
    and legacy onOffState.ui fallback.
    """
    try:
        dev = indigo.devices[dev_id]
        contact_val = dev.states.get("contact")
        if contact_val is not None:
            return str(contact_val).lower() in ("false", "0", "open")
        # Legacy fallback (non-Zigbee devices)
        state_ui = dev.states.get("onOffState.ui", "closed").lower()
        return state_ui == "open"
    except Exception:
        return False  # assume closed on error (safer for heating)


# ---------------------------------------------------------------------------
# OVERHEAT DETECTION
# ---------------------------------------------------------------------------

def check_overheating(current_temp, target_temp, room_name,
                      overheat_monitor, run_interval_mins=5):
    """
    Three-tier overheat detection system.

    Tier 0 — Coast closure: close valve before reaching target while rising
    Tier 1 — Predictive:    close valve if rate of rise is too fast
    Tier 2 — Trigger:       close valve if already above threshold
    Tier 3 — Recovery:      reopen valve only after min time + floor temp met

    Returns: (is_overheating: bool, adjusted_setpoint: float, overheat_amount: float)
    """
    # Excluded rooms: simple stateless threshold check only (no timers/alerts)
    if room_name in OVERHEAT_EXCLUDED_ROOMS:
        overheat_amount = current_temp - target_temp
        if overheat_amount > OVERHEAT_TRIGGER_THRESHOLD:
            adjusted = max(OVERHEAT_MIN_SETPOINT, target_temp - OVERHEAT_BACKOFF)
            return True, adjusted, overheat_amount
        return False, target_temp, 0.0

    overheat_amount = current_temp - target_temp

    try:
        overheat_monitor.initialize_room(room_name)
        room_data = overheat_monitor.history[room_name]
    except Exception:
        # Fallback if monitor unavailable
        if overheat_amount > OVERHEAT_TRIGGER_THRESHOLD:
            adjusted = max(OVERHEAT_MIN_SETPOINT, target_temp - OVERHEAT_BACKOFF)
            return True, adjusted, overheat_amount
        return False, target_temp, 0.0

    # Update temperature history (3-point moving average)
    temp_history = room_data.get("temp_history", [])
    temp_history.append(current_temp)
    if len(temp_history) > 3:
        temp_history.pop(0)
    room_data["temp_history"] = temp_history

    # Normalise rate to degC per 15 min so thresholds stay human-readable
    # regardless of run interval (e.g. 5-min or 10-min polling)
    if len(temp_history) >= 2:
        raw_rate        = (temp_history[-1] - temp_history[0]) / (len(temp_history) - 1)
        temp_rise_rate  = raw_rate * (15.0 / run_interval_mins)
    else:
        temp_rise_rate = 0.0

    was_overheating   = room_data.get("consecutive_cycles", 0) > 0
    rate_threshold    = ROOM_SPECIFIC_RATE_THRESHOLDS.get(room_name, OVERHEAT_RATE_THRESHOLD)
    coast_margin      = ROOM_COAST_MARGINS.get(room_name, OVERHEAT_COAST_MARGIN)
    min_off_cycles    = max(1, 45 // run_interval_mins)

    # TIER 0: Coast closure
    if temp_rise_rate > 0 and overheat_amount > -coast_margin:
        room_data["is_coasting"]    = True
        room_data["off_since_cycle"] = room_data.get("off_since_cycle", 0) + 1
        adjusted = max(OVERHEAT_MIN_SETPOINT, target_temp - OVERHEAT_BACKOFF)
        return True, adjusted, overheat_amount

    # Coast complete: room stopped rising
    if room_data.get("is_coasting", False) and temp_rise_rate <= 0:
        room_data["is_coasting"]    = False
        room_data["off_since_cycle"] = 0
        return False, target_temp, 0.0

    room_data["is_coasting"] = False

    # TIER 1: Predictive closure
    if temp_rise_rate > rate_threshold and overheat_amount > -OVERHEAT_PREDICTIVE_MARGIN:
        room_data["off_since_cycle"] = room_data.get("off_since_cycle", 0) + 1
        adjusted = max(OVERHEAT_MIN_SETPOINT, target_temp - OVERHEAT_BACKOFF)
        return True, adjusted, overheat_amount

    # TIER 2 / TIER 3: Threshold and recovery
    if was_overheating:
        # Sanity gate: release immediately if room has cooled well below target
        if overheat_amount < -OVERHEAT_REOPEN_FLOOR:
            room_data["off_since_cycle"]    = 0
            room_data["consecutive_cycles"] = 0
            return False, target_temp, 0.0

        off_cycles = room_data.get("off_since_cycle", 0)
        room_data["off_since_cycle"] = off_cycles + 1

        min_time_elapsed = off_cycles >= min_off_cycles
        cooled_to_floor  = overheat_amount < -OVERHEAT_REOPEN_FLOOR

        if min_time_elapsed and cooled_to_floor:
            room_data["off_since_cycle"] = 0
            return False, target_temp, 0.0
        else:
            adjusted = max(OVERHEAT_MIN_SETPOINT, target_temp - OVERHEAT_BACKOFF)
            return True, adjusted, overheat_amount

    else:
        if overheat_amount > OVERHEAT_TRIGGER_THRESHOLD:
            room_data["off_since_cycle"] = 1
            adjusted = max(OVERHEAT_MIN_SETPOINT, target_temp - OVERHEAT_BACKOFF)
            return True, adjusted, overheat_amount

    room_data["off_since_cycle"] = 0
    room_data["is_coasting"]     = False
    return False, target_temp, 0.0


# ---------------------------------------------------------------------------
# LOGGING HELPERS
# ---------------------------------------------------------------------------

def get_log_message(message_code, room_name, current_setpoint, new_temp,
                    dev_temp=None, scheduled_temp=None, overheat_amount=None):
    """Generate a fixed-width tabular log line for a room update."""
    if message_code == 17 and overheat_amount is not None:
        temp_diff = overheat_amount
    elif dev_temp is not None and scheduled_temp is not None:
        temp_diff = dev_temp - scheduled_temp
    else:
        temp_diff = 0.0

    current_str  = f"{dev_temp:.1f}degC"    if dev_temp       is not None else "N/A"
    schedule_str = f"{scheduled_temp:.1f}degC" if scheduled_temp is not None else "N/A"
    newset_str   = f"{new_temp:.1f}degC"

    action_map = {
        1:  "Window open        (valve closed)",
        2:  "Windows open       (valve closed)",
        3:  "Door open          (valve closed)",
        4:  "Door+Window open   (valve closed)",
        5:  f"Door closed        (reduced 12degC)",
        6:  "Fixed at target",
        7:  f"Outdoor >{OUTDOOR_TEMP_TRIGGER}degC        (valve closed)",
        8:  "Away mode active",
        9:  f"Reduced   {abs(current_setpoint - new_temp):>5.1f}degC",
        10: f"Increase  {abs(new_temp):>5.1f}degC  (valve opened)",
        11: f"Heating   {temp_diff:>+5.1f}degC  (valve opened)",
        12: "Boost active",
        13: "Both out mode",
        14: "Radiator off",
        15: "Freeze protection",
        17: f"Overheat  {overheat_amount:>+5.1f}degC  (valve closed)" if overheat_amount is not None else "Overheat (valve closed)",
        18: "Capped at max temp",
        23: f"Above Target {overheat_amount:>+5.1f}degC  (solar gain)" if overheat_amount is not None else "Above Target   (solar gain)",
        19: "Window/door closed  (valve restored)",
        20: "Window open        (valve reduced)",
        21: "Door open          (valve reduced)",
        22: "En Suite morning   (22degC)",
    }

    action = action_map.get(message_code, "Status update")
    return f"{room_name.ljust(18)} {current_str.rjust(9)} {schedule_str.rjust(9)} {newset_str.rjust(9)}  {action}"


def get_reason_line(message_code, new_temp, overheat_amount=None):
    """Generate a short human-readable reason string for change log entries."""
    t = f"{int(new_temp)}degC" if new_temp == int(new_temp) else f"{new_temp:.1f}degC"

    reason_map = {
        1:  f"Set to {t} - Window opened",
        2:  f"Set to {t} - Both windows opened",
        3:  f"Set to {t} - Door opened",
        4:  f"Set to {t} - Door and window opened",
        5:  f"Reduced to {t} - Slide door closed",
        7:  f"Set to {t} - Outdoor temperature above {OUTDOOR_TEMP_TRIGGER}degC",
        8:  f"Reduced to {t} - Away mode active",
        9:  f"Reduced to {t} - Schedule step down",
        11: f"Raised to {t} - Schedule step up",
        12: f"Raised to {t} - Boost mode active",
        13: f"Reduced to {t} - Both out mode active",
        14: f"Set to {t} - Radiator turned off",
        15: f"Set to {t} - Freeze protection active",
        17: (f"Reduced to {t} - Overheat +{overheat_amount:.1f}degC above target"
             if overheat_amount else f"Reduced to {t} - Overheat prevention"),
        23: (f"Above target {t} - Solar/passive gain (+{overheat_amount:.1f}degC)"
             if overheat_amount else f"Above target {t} - Passive warmth"),
        18: f"Capped at {t} - Maximum temperature limit reached",
        19: f"Restored to {t} - Window/door closed",
        20: f"Reduced to {t} - Window opened",
        21: f"Reduced to {t} - Door opened",
        22: f"Set to {t} - En Suite morning schedule active",
    }
    return "  " + reason_map.get(message_code, f"Set to {t}")


# ---------------------------------------------------------------------------
# SETPOINT UPDATE
# ---------------------------------------------------------------------------

def update_radiator_setpoint(dev_radiator, new_temp, message, room_name,
                              last_setpoints, last_messages,
                              log_buffer, changes_buffer,
                              dev_temp=None, scheduled_temp=None,
                              overheat_amount=None, force_log=False):
    """
    Send new setpoint to RAMSES ESP thermostat and log if changed.

    force_log=True  -> always write the room log line (hourly full dump)
    force_log=False -> only write if setpoint calculation changed

    Uses last_setpoints cache (not RAMSES device state) for change detection,
    because RAMSES does not always update setpointHeat promptly after a W 2349.
    """
    try:
        if dev_radiator is None:
            _log(f"Error: device is None for {room_name}", level="ERROR", log_buffer=log_buffer)
            return

        # Read current device setpoint for W 2349 decision
        setpoint_str = dev_radiator.states.get("setpointHeat", "0")
        if setpoint_str in (None, "null", "None", "", "unavailable", "unknown"):
            setpoint_before = 0.0
        else:
            setpoint_before = float(setpoint_str)

        new_temp = float(new_temp)

        # Send W 2349 (permanent override) when setpoint changed OR zone_mode drifted
        zone_mode     = dev_radiator.states.get("zone_mode", "")
        not_permanent = (zone_mode != "permanent override")
        changed       = abs(setpoint_before - new_temp) > TEMP_CHANGE_TOLERANCE
        if changed or not_permanent:
            indigo.thermostat.setHeatSetpoint(dev_radiator, value=new_temp)

        # Change detection uses our own cache (not RAMSES device state)
        last_calc      = last_setpoints.get(room_name)
        script_changed = (last_calc is None) or (abs(last_calc - new_temp) > TEMP_CHANGE_TOLERANCE)
        last_setpoints[room_name] = new_temp
        last_messages[room_name]  = message

        # Changes log: every actual calculation change
        if script_changed and changes_buffer is not None:
            reason   = get_reason_line(message, new_temp, overheat_amount).strip()
            before_s = f"{setpoint_before:.1f}" if setpoint_before else "??"
            changes_buffer.append(
                f"[{dt.now().strftime('%H:%M:%S')}] {room_name:<20s}  "
                f"{before_s} -> {new_temp:.1f}  {reason}"
            )

        # Event log / log_buffer: hourly full dump or ALERT_LOG_MESSAGES events
        if force_log or (script_changed and message in ALERT_LOG_MESSAGES):
            log_line = get_log_message(
                message, room_name, setpoint_before, new_temp,
                dev_temp, scheduled_temp, overheat_amount
            )
            _log(log_line, log_buffer=log_buffer)
            if not force_log:
                _log(get_reason_line(message, new_temp, overheat_amount), log_buffer=log_buffer)

    except Exception as e:
        _log(f"Error updating {room_name}: {e}", level="ERROR", log_buffer=log_buffer)


# ---------------------------------------------------------------------------
# SPECIAL ROOM RULES
# ---------------------------------------------------------------------------

def conservatory_special_rules(temp, msg, windows_open, doors_open,
                                window_count, door_count, outdoor_temp, hour,
                                store=None):
    """
    Conservatory: sliding door closed reduces setpoint to 12°C.
    contact state "true" = door closed (contact made).
    """
    try:
        contact = str(indigo.devices[DEV_SLIDE_DOOR_ID].states.get("contact", "true")).lower()
        if contact == "true":
            temp = 12
            msg  = 5
    except Exception as e:
        indigo.server.log(f"[conservatory_rules] Error checking slide door: {e}", level="ERROR")
    return temp, msg


def dining_room_special_rules(temp, msg, windows_open, doors_open,
                               window_count, door_count, outdoor_temp, hour,
                               store=None):
    """
    Dining room: garden window/door open reduces to 16°C rather than closing valve.
    Uses message 20/21 (reduced) not 1/3 (closed).
    """
    if windows_open:
        return 16, 20
    if doors_open:
        return 16, 21
    return temp, msg


def en_suite_special_rules(temp, msg, windows_open, doors_open,
                            window_count, door_count, outdoor_temp, hour,
                            store=None):
    """
    En Suite morning schedule: hold 22°C from 06:00 to 09:59 if:
      - en_suite_morning_active flag is set in store
      - window is closed (contact state True)

    Window open: cancels morning schedule for the rest of today.
    Returns (temp, msg) — if window is open, returns unchanged so the
    standard windows_open branch in process_room_temperature closes the
    valve and turns off floor heating via the floor_heat_device parameter.
    """
    if store is None:
        return temp, msg

    morning_active = store.get("en_suite_morning_active", False)

    # Check En Suite window contact sensor directly
    window_open = _contact_is_open(DEV_EN_SUITE_WINDOW_ID)

    if morning_active:
        if window_open:
            # Window opened — cancel morning schedule for today, don't auto-resume
            today = dt.now().strftime("%Y-%m-%d")
            store["en_suite_morning_active"]           = False
            store["en_suite_morning_cancelled_date"]   = today
            store["en_suite_morning_cancelled_reason"] = "window_open"
            # Return unchanged — windows_open will be True in process_room_temperature
            # which then closes the valve and turns off floor heating
            return temp, msg

        if 6 <= hour < 10:
            return EN_SUITE_MORNING_TEMP, 22  # message 22 = En Suite morning schedule

        # Past 10am reached inside cycle — auto-cancel
        store["en_suite_morning_active"]           = False
        store["en_suite_morning_cancelled_reason"] = "10am_expired"

    return temp, msg


# ---------------------------------------------------------------------------
# MAIN ROOM PROCESSING
# ---------------------------------------------------------------------------

def process_room_temperature(
        room_name, room_schedule, guest_schedule=None,
        window_devices=None, door_devices=None,
        floor_heat_device=None, special_rules=None,
        ha_device_id=None,
        current_hour=None, current_minute=None, temp_offset=0.0,
        current_outdoor_temp=None, is_away=False, is_boost=False,
        is_both_out=False, is_guest=False,
        # Injected state (replaces module globals)
        last_setpoints=None, last_messages=None,
        log_buffer=None, changes_buffer=None,
        overheat_monitor=None, run_interval_mins=5,
        # Timed boost
        timed_boost_active=False, timed_boost_rooms=None,
        # Floor heat restore guard — only True when morning schedule is active
        floor_heat_restore_enabled=False,
):
    """
    Process temperature update for one room.

    Sends a W 2349 permanent-override setpoint to the RAMSES ESP thermostat
    device (ha_device_id). All state is injected; no module globals are used.

    Priority order (highest wins, subject to overheat exception):
      1. Overheat prevention (message 17) — always applies unless windows/doors override
      2. Special room rules (conservatory, dining room, en suite morning)
      3. Away mode (message 8 / 15 freeze protection)
      4. Windows open (message 1/2)
      5. Doors open (message 3/4)
      6. High outdoor temp (message 7)
      7. Boost / timed boost (message 12)
      8. Both-out (message 13)
      9. Normal schedule (message 11/9)
    """
    if last_setpoints is None:
        last_setpoints = {}
    if last_messages is None:
        last_messages = {}

    dev_radiator    = None
    dev_temp        = 0.0
    windows_open    = False
    doors_open      = False
    window_count    = 0
    door_count      = 0

    # --- Retrieve RAMSES thermostat device ---
    try:
        if not ha_device_id:
            _log(f"ERROR: No RAMSES device ID for {room_name}", level="ERROR", log_buffer=log_buffer)
            return
        dev_radiator = indigo.devices[ha_device_id]

        temp_str = dev_radiator.states.get("temperatureInput1", "0")
        if temp_str in (None, "null", "None", "", "unavailable", "unknown"):
            _log(f"{room_name}: temperature unavailable, using 0degC", level="WARNING", log_buffer=log_buffer)
            dev_temp = 0.0
        else:
            dev_temp = float(temp_str)

        setpoint_str = dev_radiator.states.get("setpointHeat", "0")
        dev_setpoint = 0.0 if setpoint_str in (None, "null", "None", "", "unavailable", "unknown") else float(setpoint_str)

    except KeyError:
        _log(f"ERROR: RAMSES device {ha_device_id} not found for {room_name}", level="ERROR", log_buffer=log_buffer)
        return
    except Exception as e:
        _log(f"Error retrieving device for {room_name}: {e}", level="ERROR", log_buffer=log_buffer)
        return

    # --- Check window states (Zigbee contact sensors) ---
    if window_devices:
        for dev_id in window_devices:
            try:
                if _contact_is_open(dev_id):
                    windows_open = True
                    window_count += 1
            except Exception as e:
                _log(f"Error accessing window {dev_id} in {room_name}: {e}",
                     level="ERROR", log_buffer=log_buffer)

    # --- Check door states ---
    if door_devices:
        for dev_id in door_devices:
            try:
                dev = indigo.devices[dev_id]
                state_ui = dev.states.get("onOffState.ui", "closed").lower()
                if state_ui == "open":
                    doors_open = True
                    door_count += 1
            except Exception as e:
                _log(f"Error accessing door {dev_id} in {room_name}: {e}",
                     level="ERROR", log_buffer=log_buffer)

    # --- Base temperature from schedule ---
    if guest_schedule:
        new_temp = guest_schedule[current_hour] + temp_offset
    else:
        new_temp = room_schedule[current_hour] + temp_offset

    # Apply bedroom max temp limit
    if room_name in schedules.MAX_TEMP_LIMITS:
        if is_guest and room_name in schedules.MAX_TEMP_LIMITS_GUEST:
            max_limit = schedules.MAX_TEMP_LIMITS_GUEST[room_name]
        else:
            max_limit = schedules.MAX_TEMP_LIMITS[room_name]
        if new_temp > max_limit:
            new_temp = max_limit

    original_scheduled_temp = new_temp
    overheat_amount         = 0.0

    # --- Determine initial message direction ---
    if dev_setpoint < (new_temp - TEMP_CHANGE_TOLERANCE):
        message = 11
    elif dev_setpoint > (new_temp + TEMP_CHANGE_TOLERANCE):
        message = 9
    else:
        message = 11

    # --- Overheat detection ---
    if dev_temp is not None and dev_temp > RADIATORS_OFF_TEMP:
        is_overheating, adjusted_temp, overheat_amt = check_overheating(
            dev_temp, new_temp, room_name, overheat_monitor, run_interval_mins
        )
        is_passive = False
        if is_overheating:
            new_temp        = adjusted_temp
            overheat_amount = overheat_amt
            # Passive warmth: valve has been off 3+ cycles — solar/internal gain, not TRV issue
            if overheat_monitor is not None:
                off_cycles = overheat_monitor.history.get(room_name, {}).get("off_since_cycle", 0)
                is_passive = off_cycles >= 3
            message = 23 if is_passive else 17

        if overheat_monitor is not None:
            overheat_monitor.update_room(
                room_name       = room_name,
                is_overheating  = is_overheating,
                overheat_amount = overheat_amt,
                current_temp    = dev_temp,
                target_temp     = original_scheduled_temp,
                outdoor_temp    = current_outdoor_temp,
                is_passive      = is_passive,
            )

    # --- Special room rules ---
    if special_rules and message != 17:
        new_temp, special_msg = special_rules(
            new_temp, message, windows_open, doors_open,
            window_count, door_count, current_outdoor_temp, current_hour
        )
        if special_msg is not None and special_msg != message:
            message = special_msg

    # --- Standard priority overrides ---

    # Away mode
    if is_away and message != 17:
        outdoor = current_outdoor_temp if current_outdoor_temp is not None else 10.0
        if outdoor < 3.0:
            new_temp = AWAY_TEMP + 2.0
            message  = 15  # freeze protection
        else:
            new_temp = AWAY_TEMP
            message  = 8

    # Windows open
    elif windows_open and message != 5:
        new_temp = RADIATORS_OFF_TEMP
        message  = 2 if window_count >= 2 else 1

        # Turn off floor heating when window is open
        if floor_heat_device:
            try:
                floor_dev = indigo.devices[floor_heat_device]
                if floor_dev.states.get("onOffState", False):
                    indigo.device.turnOff(floor_dev)
                    _log(f"{room_name}: floor heating turned off (window open)",
                         log_buffer=log_buffer)
            except Exception as e:
                _log(f"Error turning off floor heating in {room_name}: {e}",
                     level="ERROR", log_buffer=log_buffer)

    # Doors open
    elif doors_open and message != 5:
        new_temp = RADIATORS_OFF_TEMP
        message  = 4 if (windows_open and doors_open) else 3

    # Restore floor heating when window closes (En Suite only, morning schedule active)
    elif floor_heat_device and not windows_open and floor_heat_restore_enabled:
        try:
            floor_dev = indigo.devices[floor_heat_device]
            if not floor_dev.states.get("onOffState", True):
                # Floor heat is off, window is now closed, morning schedule active — restore
                indigo.device.turnOn(floor_dev)
                _log(f"{room_name}: floor heating restored (window closed)",
                     log_buffer=log_buffer)
        except Exception as e:
            _log(f"Error restoring floor heating in {room_name}: {e}",
                 level="ERROR", log_buffer=log_buffer)

    # High outdoor temperature
    if (current_outdoor_temp is not None and
            current_outdoor_temp > OUTDOOR_TEMP_TRIGGER and
            message not in (17, 5)):
        new_temp = RADIATORS_OFF_TEMP
        message  = 7

    # Boost / timed boost
    effective_boost = (
        is_boost
        or (timed_boost_active and room_name in (timed_boost_rooms or set()))
    )
    if effective_boost and room_name in schedules.BOOST_AMOUNTS and message not in (17, 5):
        new_temp += schedules.BOOST_AMOUNTS[room_name]
        message   = 12

    # Both-out
    if is_both_out and message not in (17, 5):
        new_temp += BOTH_OUT_OFFSET
        message   = 13

    # --- Clamp to valid range ---
    new_temp = max(RADIATORS_OFF_TEMP, min(round(new_temp), MAX_ROOM_TEMP))

    # --- Final bedroom max limit ---
    if room_name in schedules.MAX_TEMP_LIMITS and message not in (1, 2, 3, 4, 7, 8, 15, 17):
        if is_guest and room_name in schedules.MAX_TEMP_LIMITS_GUEST:
            max_limit = schedules.MAX_TEMP_LIMITS_GUEST[room_name]
        else:
            max_limit = schedules.MAX_TEMP_LIMITS[room_name]
        if new_temp > max_limit:
            new_temp = max_limit
            message  = 18

    # --- Message refinement ---
    _OPEN_MESSAGES = {1, 2, 3, 4, 20, 21}

    if dev_temp is not None and abs(dev_temp - new_temp) <= TEMP_CHANGE_TOLERANCE:
        if message not in (1, 2, 3, 4, 5, 7, 8, 12, 13, 14, 15, 17, 18, 22):
            message = 11

    elif abs(dev_setpoint - new_temp) <= TEMP_CHANGE_TOLERANCE:
        if message not in (1, 2, 3, 4, 5, 7, 8, 12, 13, 14, 15, 17, 18, 22):
            message = 11

    # Window/door closed transition (open -> closed detection)
    if message not in _OPEN_MESSAGES and message != 17:
        if last_messages.get(room_name) in _OPEN_MESSAGES:
            message = 19

    # --- Send setpoint ---
    update_radiator_setpoint(
        dev_radiator, new_temp, message, room_name,
        last_setpoints, last_messages,
        log_buffer, changes_buffer,
        dev_temp, original_scheduled_temp, overheat_amount,
        force_log=(current_minute == 0),
    )
