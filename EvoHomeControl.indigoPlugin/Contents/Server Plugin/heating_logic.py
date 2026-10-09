#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    heating_logic.py
# Description: Core heating logic — room processing, overheat detection, special rules
#              Ported from EvoHome_Radiator_Update.py v8.14
# Author:      CliveS & Claude Sonnet 4.6
# Date:        30-04-2026
# Version:     1.7

import logging
import time
from datetime import datetime as dt, timedelta
from zoneinfo import ZoneInfo

import indigo  # noqa — available in plugin context

from log_stamp import stamp as _stamp, now_stamp as _now_stamp

import schedules

# indigo.server.log()'s level= wants a Python logging int; a STRING is silently
# ignored and the line logs as Info. Translate string levels at the choke points.
_LOG_LEVELS = {
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "ERROR":    logging.ERROR,
    "DEBUG":    logging.DEBUG,
    "CRITICAL": logging.CRITICAL,
}


def _to_level(level):
    if isinstance(level, str):
        return _LOG_LEVELS.get(level.upper(), logging.INFO)
    return level

# ---------------------------------------------------------------------------
# DEVICE IDs — contact sensors and radiators (RAMSES ESP zones)
# ---------------------------------------------------------------------------

# Windows / Doors / Floor heating
DEV_BATHROOM_WINDOW_ID     = 470834502
DEV_BEDROOM_1_WINDOW_ID    = 398804951
DEV_BEDROOM_2_WINDOW_ID    = 431560729
DEV_BEDROOM_3_WINDOW_ID    = 980886156
DEV_EN_SUITE_WINDOW_ID     = 566450110   # contact state: False = open
# The switch only POWERS the floor thermostat (1.21.0): the floor is turned on and off
# through the thermostat, and the switch is turned on when the floor is wanted, never off.
DEV_EN_SUITE_FLOOR_HEAT_ID       = 69786879    # "En Suite Floor Heating Switch"
DEV_EN_SUITE_FLOOR_THERMOSTAT_ID = 152351167   # "En Suite Floor Heating Thermostat" (Z-Wave TF021)
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

# Every RAMSES TRV device ID — used by the whole-house summer shut-off to force
# each radiator to RADIATORS_OFF_TEMP. Kept in sync with the device list in
# validate_configuration() below.
ALL_RADIATOR_IDS = (
    DEV_BATHROOM_ID, DEV_BEDROOM_1_ID, DEV_BEDROOM_2_ID, DEV_BEDROOM_3_ID,
    DEV_CONSERVATORY_ID, DEV_DINING_ROOM_ID, DEV_EN_SUITE_ID,
    DEV_HALL_BEDROOM_ID, DEV_HALL_KITCHEN_ID,
    DEV_LIVING_ROOM_DOOR_ID, DEV_LIVING_ROOM_FRONT_ID, DEV_UTILITY_ROOM_ID,
)

# ---------------------------------------------------------------------------
# Indigo variable IDs
# ---------------------------------------------------------------------------
VAR_BOTH_OUT_ID            = 901855906
VAR_GUEST_2_ID             = 127473296
VAR_GUEST_3_ID             = 785954068
# Referenced by NAME (not id) so recreating the variable can't break the link.
# get_variable_value / update_variable both accept a name or an id.
VAR_AV_OUT_TEMP_HI_ID      = "Average_Outside_Temp_Highest"
VAR_AV_OUT_TEMP_HI_TIME_ID = "Average_Outside_Temp_Highest_Time"
VAR_AV_OUT_TEMP_LO_ID      = "Average_Outside_Temp_Lowest"
VAR_AV_OUT_TEMP_LO_TIME_ID = "Average_Outside_Temp_Lowest_Time"
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

# A zone RAMSES has not heard from for this long is not trusted. MEASURED 28-09-2026
# over 14 days: the zone's lastSeen state updated at least every 6 minutes 99% of
# the time, and the longest gap was 72 minutes, once, on all 12 zones together (a
# gateway blip). When the gateway wedged from 26 to 31 May 2026 every zone kept its
# last temperature for five days and the plugin went on acting on them.
# trvLastSeen is NOT used: an idle valve can go 8 hours without a message of its
# own while the controller keeps reporting the zone.
#
# 1.18.0: the age is of the TEMPERATURE, from RAMSES ESP 1.16.0's temperatureSeen.
# lastSeen also moves on the controller's setpoint and mode reports, so a zone whose
# temperature had stopped kept looking fresh while its setpoints still arrived.
# MEASURED 02-10-2026: the controller sends its 30C9 temperatures for all 12 zones in
# the same burst as its 2309 setpoints, so the 45 minutes holds for the new state.
ZONE_STALE_MINUTES          = 45

# ---------------------------------------------------------------------------
# OVERHEAT PREVENTION CONSTANTS
# ---------------------------------------------------------------------------
OVERHEAT_TRIGGER_THRESHOLD  =  0.25
OVERHEAT_RECOVERY_THRESHOLD =  0.15
OVERHEAT_RATE_THRESHOLD     =  0.15  # degC per 15 min (normalised)
OVERHEAT_USE_RADIATOR_OFF   =  False
OVERHEAT_BACKOFF            =  6.0
OVERHEAT_MIN_SETPOINT       = 12.0
OVERHEAT_MIN_OFF_MINUTES    = 45     # min time valve must be off before reopen — scaled by run_interval_mins
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
# 25=En Suite drying run (radiator held warm to dry the room out)
ALERT_LOG_MESSAGES = {1, 2, 3, 4, 5, 17, 19, 20, 21, 22, 23, 25}

# En Suite morning schedule temperature, 06:00-09:59 every day for the morning shower.
# 1.20.0 (CliveS, 09-10-2026): "I would like the EnSuite to be 20 each day for the
# morning shower". Was 22, and skipped whenever it was 10 degC or more outside at 6am
# (message 24) - which left the room at 16 on a 14.5 degC morning. The skip is gone,
# and the morning is exempt from the mild-weather cut-off (OUTDOOR_TEMP_TRIGGER) as the
# drying run is. Its message code 24 is retired; do not reuse it.
EN_SUITE_MORNING_TEMP = 20.0

# ---------------------------------------------------------------------------
# EN SUITE DRYING RUN
# ---------------------------------------------------------------------------
# A daily warm-through to dry the room out. Wet towels keep the En Suite humid,
# and it sits above the humidity sensor's own comfort ceiling of 60% (measured
# 70.9% at 13:54 on 12-09-2026, from a sensor with under four hours of history,
# so nothing is claimed here about the usual MORNING figure - the run logs its
# own start and end readings precisely so that a threshold can be chosen from
# real mornings later).
#
# Deliberately separate from the morning schedule above, and RADIATOR ONLY: the
# En Suite floor heating is CliveS's to switch by hand and this run must never
# touch it (his instruction, 12-09-2026).
#
# It is exempt from the summer shut-off, from the warm-morning skip and from the
# OUTDOOR_TEMP_TRIGGER cut-off, because a warm damp morning still leaves wet
# towels. Away mode still wins - an empty house has no wet towels - and an open
# window still closes the valve.
EN_SUITE_DRYING_TEMP       = 22.0
# Only dry the room on a cold morning. MEASURED on the Ecowitt outdoor sensor
# (device 889210700) on 15-09-2026: 16.9 degC at 06:00, falling to 14.7 by 08:00 —
# a mild September morning on which the radiator ran for three and a half hours.
# 12 is CliveS's figure, set that evening. It is a pref; this is only its default.
EN_SUITE_DRYING_MAX_OUTDOOR = 12.0
# ...or on a morning when the room itself is cold, whatever it is doing outside.
# MEASURED 13 to 30-09-2026 on the En Suite sensor at 05:00: on 30-09 the room was
# 17.8 degC with 17.1 outside, no run started, and the room was cold; on 15-09 it was
# already 21.2 with 16.9 outside and a run was not wanted. Same weather, opposite
# answer - the room is what tells them apart. 19 sits between the two. A pref.
EN_SUITE_DRYING_ROOM_BELOW = 19.0
EN_SUITE_DRYING_START_HOUR = 5
EN_SUITE_DRYING_END_HOUR   = 10

# ---------------------------------------------------------------------------
# HOW LONG A SETPOINT HOLDS (timed overrides, 1.13.0)
# ---------------------------------------------------------------------------
# A setpoint is sent as a TEMPORARY override that Evohome ends by itself, so if
# Indigo, this plugin or RAMSES ESP stops, each room goes back to the Evohome
# timetable instead of holding its last setting indefinitely (CliveS, 28-09-2026).
# The cycle renews it once less than OVERRIDE_RENEW_MINUTES is left, so each room
# is sent about once an hour rather than every five minutes. PROVEN LIVE 28-09-2026:
# RAMSES ESP 1.12.0's mode 04 was honoured by the controller and, when it ran out,
# the zone went back to its timetable (Bedroom 3: 16 degC at 19:21).
#
# The summer 8 degC hold stays PERMANENT: a stopped Indigo in summer must not hand
# the house back to a timetable that heats. The module default is 0 (permanent),
# the old behaviour; the plugin sets the length from its settings at startup.
RAMSES_PLUGIN_ID       = "uk.co.clives.ramses.esp"
OVERRIDE_RENEW_MINUTES = 60
_OVERRIDE = {"minutes": 0, "broken": False}
_OVERRIDE_WARNED = {}


def set_override_minutes(minutes):
    """Set how long each setpoint holds; 0 means permanent. Also clears a fallback
    left by an earlier failed send, so a fixed RAMSES ESP is tried again."""
    try:
        minutes = int(minutes)
    except (ValueError, TypeError):
        minutes = 0
    _OVERRIDE["minutes"] = max(0, minutes)
    _OVERRIDE["broken"]  = False


def override_renew_minutes():
    """How close to its end a timed setting is renewed: OVERRIDE_RENEW_MINUTES, or
    half the chosen length when that is shorter. With the 1-hour setting a fixed
    60 minutes was always "nearly over", so every room was resent every cycle."""
    return min(OVERRIDE_RENEW_MINUTES, _OVERRIDE["minutes"] / 2.0)


def _timed_overrides_on(permanent=False):
    return (not permanent) and _OVERRIDE["minutes"] > 0 and not _OVERRIDE["broken"]


# RAMSES ESP versions that accept an explicit end time ("until") on its timed action.
RAMSES_UNTIL_VERSION = (1, 15, 0)


def _ramses_takes_until():
    """True when the installed RAMSES ESP accepts an end time. An older one would ignore
    it and send its two-hour default, which the next cycle would see as wrong and send
    again - every five minutes, for every room."""
    try:
        ramses = indigo.server.getPlugin(RAMSES_PLUGIN_ID)
        version = tuple(int(p) for p in str(ramses.pluginVersion).split(".")[:3])
        return version >= RAMSES_UNTIL_VERSION
    except Exception:
        return False


def needs_override_refresh(dev, permanent=False, now=None, until=None):
    """True when the zone is not in the kind of override wanted, or a timed one ends
    within override_renew_minutes(). An end time that cannot be read counts as ending.
    With `until` ("YYYY-MM-DD HH:MM") the zone should hold exactly that end time."""
    mode = dev.states.get("zoneMode", "")
    if until is not None and _timed_overrides_on() and _ramses_takes_until():
        return not (mode == "temporary override"
                    and str(dev.states.get("zoneOverrideUntil", ""))[:16] == until)
    if until is not None:
        permanent = True
    if not _timed_overrides_on(permanent):
        return mode != "permanent override"
    if mode != "temporary override":
        return True
    try:
        end = dt.strptime(str(dev.states.get("zoneOverrideUntil", ""))[:16], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return True
    return (end - (now or dt.now())).total_seconds() < override_renew_minutes() * 60


def send_setpoint(dev, value, permanent=False, until=None):
    """Send a setpoint: timed through RAMSES ESP's Set Temperature for a While action,
    or permanent through Indigo's own thermostat command. If the timed kind cannot be
    sent, fall back to permanent, say so once, and stay permanent until the settings
    are saved again - otherwise every cycle would resend every room.

    With `until` ("YYYY-MM-DD HH:MM") the setting ends at that time instead (1.16.0:
    the summer hold ends on the day heating is due back, so a stopped Indigo cannot
    keep the house cold into the winter). Needs RAMSES ESP 1.15.0; permanent before."""
    note_sent(dev, value)
    if until is not None:
        if _timed_overrides_on() and _ramses_takes_until():
            try:
                indigo.server.getPlugin(RAMSES_PLUGIN_ID).executeAction(
                    "setTemporarySetpoint", deviceId=dev.id,
                    props={"setpoint": f"{float(value):.2f}", "until": until})
                return
            except Exception as e:
                _log(f"Could not send a setting ending {until} to {dev.name}: {e}. "
                     f"Sending a permanent one instead.", level="WARNING")
        indigo.thermostat.setHeatSetpoint(dev, value=value)
        return
    if _timed_overrides_on(permanent):
        try:
            ramses = indigo.server.getPlugin(RAMSES_PLUGIN_ID)
            if ramses is not None and ramses.isEnabled():
                ramses.executeAction("setTemporarySetpoint", deviceId=dev.id, props={
                    "setpoint": f"{float(value):.2f}",
                    "minutes":  str(_OVERRIDE["minutes"]),
                })
                return
            reason = "the RAMSES ESP plugin is not enabled"
        except Exception as e:
            reason = f"RAMSES ESP refused it ({e})"
        _OVERRIDE["broken"] = True
        if not _OVERRIDE_WARNED.get(reason):
            _OVERRIDE_WARNED[reason] = True
            _log(f"Could not send a timed setpoint - {reason}. Sending permanent ones "
                 f"instead; timed ones need RAMSES ESP 1.12.0 or later. Save the settings "
                 f"to try again.", level="WARNING")
    indigo.thermostat.setHeatSetpoint(dev, value=value)


# ---------------------------------------------------------------------------
# CHANGES MADE BY HAND (1.16.0)
# ---------------------------------------------------------------------------
# RAMSES ESP 1.15.0 marks each zone with who last changed it: "indigo", "timetable" or
# "manual" (the Evohome controller's screen, a valve's wheel or the app). A room changed
# by hand is left alone until its plan next changes (at the latest midnight), or for as
# long as it stays on a permanent setting. So anyone can run the heating the ordinary
# Evohome way while Indigo is still running, without Indigo undoing it minutes later.
#
# CHANGES MADE THROUGH INDIGO (1.19.0). RAMSES ESP calls every setpoint sent through it
# "indigo", whether this plugin sent it or a person did from the Indigo client, the Home
# app or a dashboard. CliveS turned the En Suite up from the Home app on 09-10-2026 and
# this plugin put it back to 8 five minutes later. So it now remembers what it last sent
# each zone, and an "indigo" change made after that, to a different temperature, is a
# person's and held like one made by hand. It is held until the plan next changes even
# when it arrived as a permanent setting: RAMSES ESP sends Indigo's own thermostat command
# as permanent, so the person never chose "for good".
_MANUAL_ANNOUNCED = {}

# {device id: (temperature, when)} - the last setpoint this plugin sent each zone.
# Saved with the setpoint cache, so a plugin restart does not forget a person's change.
_SENT = {}


def note_sent(dev, value, when=None):
    """Remember that this plugin sent `value` to `dev` (now, unless `when` is given)."""
    try:
        _SENT[int(dev.id)] = (float(value), when or dt.now())
    except (TypeError, ValueError, AttributeError):
        pass


def sent_snapshot():
    """The record above as JSON-friendly data, for the setpoint cache."""
    return {str(k): [v, when.isoformat()] for k, (v, when) in _SENT.items()}


def restore_sent(data):
    """Load what sent_snapshot() wrote. Anything unreadable is skipped, never raised."""
    if not isinstance(data, dict):
        return
    for k, item in data.items():
        try:
            _SENT[int(k)] = (float(item[0]), dt.fromisoformat(str(item[1])))
        except (TypeError, ValueError, IndexError, KeyError):
            continue


def _changed_through_indigo(dev, changed):
    """True when an "indigo" change was not this plugin's: it came after the last thing
    this plugin sent the zone, and to a different temperature. With nothing on record
    (no send since the record began) the change is taken to be ours."""
    sent = _SENT.get(int(dev.id)) if hasattr(dev, "id") else None
    if sent is None:
        return False
    value, when = sent
    try:
        now_value = float(dev.states.get("setpointHeat"))
    except (TypeError, ValueError):
        return False
    return changed > when and abs(now_value - value) > TEMP_CHANGE_TOLERANCE


def manual_hold_until(dev, hours, now=None):
    """None when the room is not held; otherwise when the hold ends (a datetime), or
    the string "permanent" while it stays on a permanent setting made by hand."""
    states = dev.states
    source = states.get("setpointSource")
    if source not in ("manual", "indigo"):
        return None
    mode = states.get("zoneMode", "")
    if mode == "schedule":
        return None
    try:
        changed = dt.strptime(str(states.get("setpointChangedAt", ""))[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if source == "indigo":
        if not _changed_through_indigo(dev, changed):
            return None
    elif mode == "permanent override":
        return "permanent"
    hour_start = changed.replace(minute=0, second=0, microsecond=0)
    end = None
    for step in range(1, 25):
        candidate = hour_start + timedelta(hours=step)
        if candidate.hour == 0 or hours[candidate.hour] != hours[(candidate.hour - 1) % 24]:
            end = candidate
            break
    if end is None or (now or dt.now()) >= end:
        return None
    return end


def check_manual_hold(room, dev, hours, now=None, log_buffer=None):
    """True when the room should be left alone because it was changed by hand. Says so
    once when a hold starts and once when the room comes back under the plugin."""
    held = manual_hold_until(dev, hours, now)
    key = str(dev.states.get("setpointChangedAt", ""))
    if held is None:
        if room in _MANUAL_ANNOUNCED:
            del _MANUAL_ANNOUNCED[room]
            _log(f"{room} is back under the heating plugin's control.", log_buffer=log_buffer)
        return False
    if _MANUAL_ANNOUNCED.get(room) != key:
        _MANUAL_ANNOUNCED[room] = key
        try:
            value = f"{float(dev.states.get('setpointHeat')):g} degrees"
        except (TypeError, ValueError):
            value = "a new temperature"
        if held == "permanent":
            how = "while it stays on that permanent setting"
        else:
            how = f"until {_clock_words(held)}"
        where = " through Indigo" if dev.states.get("setpointSource") == "indigo" else ""
        _log(f"{room} was set to {value} by hand{where}, so the heating plugin leaves it "
             f"alone {how}.", log_buffer=log_buffer)
    return True


def _clock_words(when):
    h, m = when.hour, when.minute
    if (h, m) == (0, 0):
        return "midnight"
    if (h, m) == (12, 0):
        return "noon"
    suffix = "am" if h < 12 else "pm"
    return f"{h % 12 or 12}{suffix}" if m == 0 else f"{h % 12 or 12}:{m:02d}{suffix}"


# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def _log(message, level="INFO", log_buffer=None, file_only=False):
    """Log to Indigo event log and optionally to a buffer list.
    file_only=True suppresses the Indigo event log; data still goes to log_buffer."""
    # The daily file always carries the time; the Event Log copy follows the
    # plugin's Toggle Timestamps switch (log_stamp.py).
    if not file_only:
        indigo.server.log(_stamp(message), level=_to_level(level))
    if log_buffer is not None:
        log_buffer.append(f"{_now_stamp()} {message}")


def validate_configuration():
    """Validate that all required Indigo variables and RAMSES TRV devices exist.

    Logs an ERROR for each missing item. Returns True if no errors.
    """
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

    # Check all 12 RAMSES TRV devices
    required_devices = [
        (DEV_BATHROOM_ID,           "Bathroom TRV"),
        (DEV_BEDROOM_1_ID,          "Bedroom 1 TRV"),
        (DEV_BEDROOM_2_ID,          "Bedroom 2 TRV"),
        (DEV_BEDROOM_3_ID,          "Bedroom 3 TRV"),
        (DEV_CONSERVATORY_ID,       "Conservatory TRV"),
        (DEV_DINING_ROOM_ID,        "Dining Room TRV"),
        (DEV_EN_SUITE_ID,           "En Suite TRV"),
        (DEV_HALL_BEDROOM_ID,       "Hall Bedroom TRV"),
        (DEV_HALL_KITCHEN_ID,       "Hall Kitchen TRV"),
        (DEV_LIVING_ROOM_DOOR_ID,   "Living Room Door TRV"),
        (DEV_LIVING_ROOM_FRONT_ID,  "Living Room Front TRV"),
        (DEV_UTILITY_ROOM_ID,       "Utility Room TRV"),
    ]
    for dev_id, dev_label in required_devices:
        try:
            indigo.devices[dev_id]
        except Exception:
            errors.append(f"Missing required device: {dev_label} (ID: {dev_id})")

    for error in errors:
        indigo.server.log(_stamp(error), level=_to_level("ERROR"))
    return len(errors) == 0


def update_variable(var_id_or_name, value):
    """Update Indigo variable by ID or name. All values stored as strings."""
    try:
        indigo.variable.updateValue(var_id_or_name, str(value))
    except Exception as e:
        indigo.server.log(_stamp(f"[heating_logic] Error updating variable {var_id_or_name}: {e}"), level=_to_level("ERROR"))


def get_variable_value(var_id_or_name, default=None):
    """Get Indigo variable value by ID or name, with default fallback."""
    try:
        return indigo.variables[var_id_or_name].value
    except Exception:
        return default


def is_within_summer_off(today, start_month, start_day, end_month, end_day):
    """Return True if `today` (a date) falls inside the summer shut-off window.

    The window runs from (start_month, start_day) INCLUSIVE up to
    (end_month, end_day) EXCLUSIVE — i.e. heating returns ON on the end date.
    With the defaults (1 Jun -> 30 Sep) the house is off 1 Jun..29 Sep and
    heating is restored on 30 Sep.

    A window whose start falls later in the year than its end (e.g. 1 Nov ->
    1 Mar) is treated as wrapping across the year boundary.
    """
    start = (start_month, start_day)
    end   = (end_month,   end_day)
    cur   = (today.month,  today.day)
    if start <= end:
        return start <= cur < end
    # Wrapped window (start later than end): off if at/after start OR before end
    return cur >= start or cur < end


# Rooms whose reading is currently too old, so the warning is logged once when a
# zone goes quiet and once when it comes back, not every five minutes. A mutable
# dict, never rebound, so the plugin host's copy of this module keeps it.
_ZONE_STALE_LATCH = {}


# The house's clock. A zone's temperatureSeen / lastSeen text is local wall-clock time
# with no offset, so it is read through this zone, never through UTC (1.18.1).
HOUSE_TZ = ZoneInfo("Europe/London")


def _now_epoch(now=None):
    """Seconds since the epoch for now, or for a given datetime: an aware one as it
    stands, a naive one as house time."""
    if now is None:
        return time.time()
    if now.tzinfo is None:
        return now.replace(tzinfo=HOUSE_TZ).timestamp()
    return now.timestamp()


def _local_text_age_minutes(seen, now_epoch):
    """Age in minutes of a naive house-time reading.

    On 25 October 01:00-01:59 happens twice, so the text means two moments an hour
    apart; both are tried (fold 0 is the BST one, fold 1 the GMT one). A reading
    cannot come from the future, so a negative age is ruled out, and of what is left
    the newer moment is taken - zones report every few minutes, so that is the likely
    one. In spring a text in the missing hour cannot occur, and the two folds simply
    agree on every real one."""
    ages = sorted((now_epoch - seen.replace(tzinfo=HOUSE_TZ, fold=f).timestamp()) / 60.0
                  for f in (0, 1))
    usable = [a for a in ages if a >= 0]
    return usable[0] if usable else ages[-1]


def zone_reading_age_minutes(dev, now=None):
    """Minutes since this zone's temperature was last reported.

    RAMSES ESP 1.17.0 and later keep that moment in temperatureSeenEpoch, seconds
    since the epoch, which the clocks changing cannot confuse (1.18.1); this is used
    whenever it holds a time. Otherwise the local text: temperatureSeen (RAMSES ESP
    1.16.0 on), read as house time through Europe/London. A blank temperatureSeen
    means no temperature has arrived since the device was made, so the reading (RAMSES
    starts a new zone at 0) is not one: infinity, which every caller treats as too old.
    Older versions have no temperatureSeen, and then lastSeen - any report from the
    zone - is the best there is. None when neither can be read: "cannot tell", and
    the caller carries on rather than stopping the heating on a missing state.

    `now` (for tests) is a datetime: aware as it stands, naive as house time."""
    try:
        states = dev.states
        epoch = states.get("temperatureSeenEpoch")
        try:
            epoch = int(float(epoch)) if epoch not in (None, "") else 0
        except (TypeError, ValueError):
            epoch = 0
        if epoch > 0:
            return (_now_epoch(now) - epoch) / 60.0
        if "temperatureSeen" in states:
            raw = states.get("temperatureSeen")
            if not raw:
                return float("inf")
        else:
            raw = states.get("lastSeen")
    except Exception:
        return None
    if not raw:
        return None
    try:
        seen = dt.strptime(str(raw)[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    return _local_text_age_minutes(seen, _now_epoch(now))


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
# EN SUITE UNDERFLOOR HEATING (1.21.0)
# ---------------------------------------------------------------------------
# The Heatit TF021 thermostat is powered through a Z-Wave switch. Until 1.21.0 the
# plugin turned the floor on and off with that switch, which also cut the thermostat's
# power, so it answered nothing while the floor was off ("no ack" for a week) and the
# 6am "heat to 14" was sent before it had started up. CliveS, 09-10-2026: the switch
# was "a belt and braces fix originally" - control it through the thermostat. Proven
# live that morning: Off, Heat and a setpoint each confirmed with no error.
# So: ON = power on, mode Heat, setpoint FLOOR_HEAT_ON_TEMP. OFF = mode Off. The switch
# is never turned off; with it off the thermostat has no power, so the floor is off.
FLOOR_HEAT_ON_TEMP     = 14.0
FLOOR_OFF_RESEND_SECS  = 600    # an Off the thermostat has not confirmed is resent this often
_FLOOR = {"off_sent_at": 0.0}


def _floor_devices():
    """(power switch, thermostat), or None for either one Indigo does not have."""
    out = []
    for dev_id in (DEV_EN_SUITE_FLOOR_HEAT_ID, DEV_EN_SUITE_FLOOR_THERMOSTAT_ID):
        try:
            out.append(indigo.devices[dev_id])
        except Exception:
            out.append(None)
    return tuple(out)


def floor_heat_is_heating(thermostat):
    """True only when the thermostat REPORTS heat mode at the morning temperature.
    A missing state is never a match, so an unconfirmed command is sent again."""
    if thermostat is None:
        return False
    states = thermostat.states
    if states.get("hvacOperationModeIsHeat") is not True:
        return False
    try:
        return abs(float(states.get("setpointHeat")) - FLOOR_HEAT_ON_TEMP) <= TEMP_CHANGE_TOLERANCE
    except (TypeError, ValueError):
        return False


def floor_heat_on(log_buffer=None):
    """Turn the En Suite floor on: power the thermostat if it is not, then Heat at
    FLOOR_HEAT_ON_TEMP. A thermostat that has just been powered is not sent anything
    yet - it takes about 25 seconds to start (measured 09-10-2026) and would lose the
    command; the next heating check, within five minutes, finds it not heating and
    sends it. Returns True when the commands were sent."""
    switch, thermostat = _floor_devices()
    if thermostat is None:
        _log("En Suite: the floor heating thermostat is missing from Indigo, so the floor "
             "cannot be turned on", level="WARNING", log_buffer=log_buffer)
        return False
    if switch is not None and switch.states.get("onOffState") is not True:
        indigo.device.turnOn(switch)
        _log("En Suite: the floor heating thermostat had no power, so it has been switched "
             "on. It will be set to heat at the next check.", log_buffer=log_buffer)
        return False
    if floor_heat_is_heating(thermostat):
        return True
    indigo.thermostat.setHvacMode(thermostat, value=indigo.kHvacMode.Heat)
    indigo.thermostat.setHeatSetpoint(thermostat, value=FLOOR_HEAT_ON_TEMP)
    _FLOOR["off_sent_at"] = 0.0
    _log(f"En Suite: floor heating on (thermostat set to heat to {FLOOR_HEAT_ON_TEMP:.0f} "
         f"degrees)", log_buffer=log_buffer)
    return True


def floor_heat_off(reason="", log_buffer=None, now=None):
    """Turn the En Suite floor off through its thermostat (mode Off). Leaves the power
    switch alone. Nothing is sent while the thermostat reports Off already, or has no
    power; an Off it has not confirmed is resent at most every FLOOR_OFF_RESEND_SECS,
    so a 30-second caller cannot flood the Z-Wave network. Returns True when sent."""
    switch, thermostat = _floor_devices()
    if thermostat is None:
        return False
    if switch is not None and switch.states.get("onOffState") is False:
        return False   # no power, so the floor is already off
    if thermostat.states.get("hvacOperationModeIsOff") is True:
        return False
    now = time.time() if now is None else now
    if now - _FLOOR["off_sent_at"] < FLOOR_OFF_RESEND_SECS:
        return False
    indigo.thermostat.setHvacMode(thermostat, value=indigo.kHvacMode.Off)
    _FLOOR["off_sent_at"] = now
    why = f" ({reason})" if reason else ""
    _log(f"En Suite: floor heating off{why}", log_buffer=log_buffer)
    return True


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
    min_off_cycles    = max(1, OVERHEAT_MIN_OFF_MINUTES // run_interval_mins)

    # TIER 0: Coast closure
    if temp_rise_rate > 0 and overheat_amount > -coast_margin:
        room_data["is_coasting"]    = True
        room_data["off_since_cycle"] = room_data.get("off_since_cycle", 0) + 1
        adjusted = max(OVERHEAT_MIN_SETPOINT, target_temp - OVERHEAT_BACKOFF)
        return True, adjusted, overheat_amount

    # Coast complete: room stopped rising
    # Only release if room has also dropped back near target — if it is still
    # significantly above the trigger threshold, fall through to Tier 2 rather
    # than blindly opening the valve just because the rate of rise has stopped.
    if room_data.get("is_coasting", False) and temp_rise_rate <= 0:
        room_data["is_coasting"]    = False
        room_data["off_since_cycle"] = 0
        if overheat_amount <= OVERHEAT_TRIGGER_THRESHOLD:
            return False, target_temp, 0.0
        # Still above threshold — fall through to Tier 2

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
        5:  "Door closed        (reduced 12degC)",
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
        22: f"En Suite morning   ({EN_SUITE_MORNING_TEMP:.0f}degC)",
        25: "En Suite drying    (radiator only)",
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
        25: f"Set to {t} - En Suite drying run",
    }
    return "  " + reason_map.get(message_code, f"Set to {t}")


# ---------------------------------------------------------------------------
# SETPOINT UPDATE
# ---------------------------------------------------------------------------

def update_radiator_setpoint(dev_radiator, new_temp, message, room_name,
                              last_setpoints, last_messages,
                              log_buffer, changes_buffer,
                              dev_temp=None, scheduled_temp=None,
                              overheat_amount=None, force_log=False,
                              event_log_dump=True):
    """
    Send new setpoint to RAMSES ESP thermostat and log if changed.

    force_log=True  -> always write the room log line (hourly full dump)
    force_log=False -> only write if setpoint calculation changed

    event_log_dump=False -> the hourly full dump still reaches log_buffer, and so
    the plugin's own daily log file, but is NOT echoed into the shared Indigo
    event log. Twelve room lines an hour is 288 lines a day of routine narration
    in a log the whole estate reads. Defaults True so any caller that does not
    pass it keeps the previous behaviour. Error lines are unaffected - they never
    set file_only and always reach the event log.

    Uses last_setpoints cache (not RAMSES device state) for change detection,
    because RAMSES does not always update setpointHeat promptly after a W 2349.
    """
    try:
        if dev_radiator is None:
            _log(f"Error: device is None for {room_name}", level="ERROR", log_buffer=log_buffer)
            return

        # Read current device setpoint for W 2349 decision
        # When the RAMSES state is unavailable we use the local cache instead of
        # 0.0 — otherwise abs(0 - 12) > tolerance always fires a redundant W 2349.
        setpoint_str       = dev_radiator.states.get("setpointHeat", "0")
        setpoint_available = setpoint_str not in (None, "null", "None", "", "unavailable", "unknown")
        if setpoint_available:
            setpoint_before = float(setpoint_str)
        else:
            cached = last_setpoints.get(room_name)
            setpoint_before = float(cached) if cached is not None else 0.0

        new_temp = float(new_temp)

        # Send when the setpoint changed, the zone is not in the override kind we
        # want, or a timed override is close to running out. If the RAMSES setpoint
        # state is unavailable we still send, so the TRV reflects our target.
        # (RAMSES_ESP v1.2.8 renamed zone_mode -> zoneMode.)
        refresh = needs_override_refresh(dev_radiator)
        changed = abs(setpoint_before - new_temp) > TEMP_CHANGE_TOLERANCE
        if changed or refresh or not setpoint_available:
            send_setpoint(dev_radiator, new_temp)

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
                f"[{dt.now().strftime('%H:%M:%S.%f')[:-3]}] {room_name:<20s}  "
                f"{before_s} -> {new_temp:.1f}  {reason}"
            )

        # Event log / log_buffer: hourly full dump or ALERT_LOG_MESSAGES events
        # file_only=True for per-change events (not hourly) — keeps file logs intact
        # but suppresses routine solar gain / overheat status lines from event log
        if force_log or (script_changed and message in ALERT_LOG_MESSAGES):
            log_line = get_log_message(
                message, room_name, setpoint_before, new_temp,
                dev_temp, scheduled_temp, overheat_amount
            )
            # The hourly dump reaches the event log only when the caller still
            # wants it there; the daily file gets the line either way, because
            # file_only gates indigo.server.log alone and never log_buffer.
            _log(log_line, log_buffer=log_buffer,
                 file_only=(not (force_log and event_log_dump)))
            if not force_log:
                _log(get_reason_line(message, new_temp, overheat_amount),
                     log_buffer=log_buffer, file_only=True)

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
        indigo.server.log(_stamp(f"[conservatory_rules] Error checking slide door: {e}"), level=_to_level("ERROR"))
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
    En Suite morning schedule: hold EN_SUITE_MORNING_TEMP from 06:00 to 09:59 if:
      - en_suite_morning_active flag is set in store
      - window is closed (contact state True)

    Cancellation reasons (set in store["en_suite_morning_cancelled_reason"]):
      - "window_open"   — window opened during the morning slot
      - "warm_outdoor"  — retired in 1.20.0; may still be in a saved state file from
                          before, and means nothing now
      - "10am_expired"  — normal end-of-window auto-cancel

    Returns (temp, msg). If window is open during active morning, returns
    unchanged so the standard windows_open branch in process_room_temperature
    closes the valve and turns off floor heating via floor_heat_device.
    """
    if store is None:
        return temp, msg

    # Drying run wins over everything else this room's rules decide. plugin.py's
    # _check_en_suite_drying owns start and stop - it ticks every 30 s, so it ends
    # the run on an opened window far sooner than this 5-minute cycle could, and it
    # is the only path that runs at all during the summer shut-off. This branch only
    # reports the target while the run is live. The window is re-checked here so a
    # window opened between ticks closes the valve on THIS cycle instead of holding
    # the room at the drying temperature for up to five more minutes.
    if store.get("en_suite_drying_active"):
        if _contact_is_open(DEV_EN_SUITE_WINDOW_ID):
            return temp, msg   # fall through to the windows_open branch
        return store.get("en_suite_drying_temp", EN_SUITE_DRYING_TEMP), 25

    morning_active   = store.get("en_suite_morning_active", False)

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
        # Override the temperature baseline used for overheat detection.
        # When En Suite morning schedule is active, pass EN_SUITE_MORNING_TEMP
        # so the room is only flagged as overheating above that, not its plan value.
        overheat_target_override=None,
        # Force this room's line into the hourly full event-log dump. When None
        # (caller did not specify) fall back to the legacy minute == 0 gate.
        # The plugin passes the clock-hour-change flag here so the dump is not
        # lost to heating-cycle drift past the :00 boundary.
        force_log_override=None,
        # Whether the hourly full dump is also echoed into the shared Indigo
        # event log. The plugin passes its logHourlyDumpToEventLog pref, which is
        # quiet by default; the per-room lines always reach log_buffer and so the
        # plugin's own daily log file regardless.
        event_log_dump=True,
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

        # No temperature state at all is the same as an unreadable one - never 0degC.
        temp_str = dev_radiator.states.get("temperatureInput1")
        if temp_str in (None, "null", "None", "", "unavailable", "unknown"):
            # A missing reading must NOT be treated as 0degC — that makes the room
            # look freezing (defeating overheat detection and driving a bogus
            # heat-up). Skip this zone for this cycle; the TRV keeps its last RAMSES
            # setpoint until a real temperature returns.
            _log(f"{room_name}: temperature unavailable — skipping this cycle (TRV holds last setpoint)",
                 level="WARNING", log_buffer=log_buffer)
            return
        dev_temp = float(temp_str)

        setpoint_str = dev_radiator.states.get("setpointHeat", "0")
        dev_setpoint = 0.0 if setpoint_str in (None, "null", "None", "", "unavailable", "unknown") else float(setpoint_str)

        # Changed by hand on the controller, a valve or the app: leave it alone.
        plan_hours = guest_schedule if (is_guest and guest_schedule) else room_schedule
        if check_manual_hold(room_name, dev_radiator, plan_hours, log_buffer=log_buffer):
            return

        # An old reading is as bad as a missing one: skip the zone and leave the
        # valve where it is. Warn once when the zone goes quiet, once when it returns.
        age = zone_reading_age_minutes(dev_radiator)
        if age is not None and age > ZONE_STALE_MINUTES:
            if not _ZONE_STALE_LATCH.get(room_name):
                _ZONE_STALE_LATCH[room_name] = True
                if age == float("inf"):
                    heard = "no temperature has been reported for this zone yet"
                else:
                    heard = f"no temperature has been reported for this zone for {age:.0f} minutes"
                _log(f"{room_name}: {heard}, so its reading of {dev_temp:.1f} degC may be out "
                     f"of date. The radiator stays at its last setting until the zone reports "
                     f"again.", level="WARNING", log_buffer=log_buffer)
            return
        if _ZONE_STALE_LATCH.pop(room_name, None):
            _log(f"{room_name}: the zone is reporting again, so the heating is back in control of it.",
                 log_buffer=log_buffer)

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
    # Use the same _contact_is_open() reader as windows so a Zigbee2MQTT door
    # contact (states["contact"]: False = open) is read correctly rather than via
    # the raw onOffState.ui, which a Zigbee contact device does not drive reliably.
    if door_devices:
        for dev_id in door_devices:
            try:
                if _contact_is_open(dev_id):
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

    # Whether a boost will actually be added below. Worked out here so overheat
    # detection can judge the room against its boosted target. Until 1.14.0 only a
    # TIMED boost raised that baseline, so a room on the global Boost variable that
    # was still warming within a degree of its normal target was "coasting" and had
    # its valve shut - the Conservatory's +3 could never happen.
    effective_boost = (
        is_boost
        or (timed_boost_active and room_name in (timed_boost_rooms or set()))
    )
    boost_applies = (effective_boost and room_name in schedules.BOOST_AMOUNTS
                     and not (windows_open or doors_open) and not is_away)

    # --- Overheat detection ---
    if dev_temp is not None and dev_temp > RADIATORS_OFF_TEMP:
        # Use override target if provided (e.g. the En Suite morning schedule —
        # use that as the baseline so 21.9°C is not falsely flagged as overheating)
        overheat_target = overheat_target_override if overheat_target_override is not None else new_temp
        # A boosted room is judged against its boosted target, so a room at 20.9 degC
        # with a 20 degC schedule and a +2 degC boost is not falsely suppressed.
        if boost_applies:
            overheat_target = overheat_target + schedules.BOOST_AMOUNTS[room_name]
        is_overheating, adjusted_temp, overheat_amt = check_overheating(
            dev_temp, overheat_target, room_name, overheat_monitor, run_interval_mins
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
    if special_rules and message not in (17, 23):
        new_temp, special_msg = special_rules(
            new_temp, message, windows_open, doors_open,
            window_count, door_count, current_outdoor_temp, current_hour
        )
        if special_msg is not None and special_msg != message:
            message = special_msg

    # An open window switches the floor heating off whatever mode the house is in.
    # This used to sit in the windows branch below, which is an elif of Away, so
    # with Away on an open En Suite window left the floor heating running.
    if windows_open and floor_heat_device:
        try:
            floor_heat_off("window open", log_buffer=log_buffer)
        except Exception as e:
            _log(f"Error turning off floor heating in {room_name}: {e}",
                 level="ERROR", log_buffer=log_buffer)

    # --- Standard priority overrides ---

    # Away mode
    if is_away and message not in (17, 23):
        outdoor = current_outdoor_temp if current_outdoor_temp is not None else 10.0
        if outdoor < 3.0:
            new_temp = AWAY_TEMP + 2.0
            message  = 15  # freeze protection
        else:
            new_temp = AWAY_TEMP
            message  = 8

    # Windows open. 20/21 are a special rule that has already decided what an open
    # window means for this room (the Dining Room holds 16 degC rather than closing
    # its valve), so the general rule must not overwrite that decision with 8 degC.
    # An `if`, not an `elif` of Away (1.14.0): with Away on, an open window used to
    # leave the radiator at 14 or 16 degC heating the garden. Away's own setting is a
    # message 8/15, which is not exempt here, so the window wins.
    if windows_open and message not in (5, 20, 21):
        new_temp = RADIATORS_OFF_TEMP
        message  = 2 if window_count >= 2 else 1

    # Doors open (20/21 exempt for the same reason as windows above)
    elif doors_open and message not in (5, 20, 21):
        new_temp = RADIATORS_OFF_TEMP
        message  = 4 if (windows_open and doors_open) else 3

    # Restore floor heating when window closes (En Suite only, morning schedule active)
    # Also the second chance for a 6am start that only powered the thermostat, or a
    # command the thermostat did not confirm (1.21.0): floor_heat_on sends nothing
    # while the thermostat already reports Heat at the morning temperature.
    elif floor_heat_device and not windows_open and floor_heat_restore_enabled and not is_away:
        try:
            floor_heat_on(log_buffer=log_buffer)
        except Exception as e:
            _log(f"Error restoring floor heating in {room_name}: {e}",
                 level="ERROR", log_buffer=log_buffer)

    # High outdoor temperature
    # 25 (drying run) is exempt: a warm damp morning still leaves wet towels, so a
    # mild day outside must not close the valve on a run that exists to dry the room.
    # 22 (En Suite morning) is exempt too (1.20.0): the shower is every day.
    if (current_outdoor_temp is not None and
            current_outdoor_temp > OUTDOOR_TEMP_TRIGGER and
            message not in (17, 23, 5, 22, 25)):
        new_temp = RADIATORS_OFF_TEMP
        message  = 7

    # Boost / timed boost. Not while a window or outside door is open (CliveS,
    # 27-09-2026): boosting a room with the garden door open only heats the garden,
    # and until 1.11.0 the Dining Room went to 18 degC that way.
    # Nor on top of Away (8/15) or the mild-weather cut-off (7) (1.14.0): Away plus a
    # boost gave 16 degC in an empty house.
    if boost_applies and message not in (17, 23, 5, 7, 8, 15):
        new_temp += schedules.BOOST_AMOUNTS[room_name]
        message   = 12

    # Both-out. 25 is exempt so the drying run holds one predictable temperature
    # whoever happens to be in the house at 5am. Away (8/15) is exempt because Away
    # already is the empty-house setting - taking four more off gave 10 degC, and
    # 12 instead of 16 in a frost. An open window's setting (1-4, 20, 21) and the
    # mild-weather cut-off (7) are decisions of their own, and relabelling them 13
    # also made the next cycle log "window closed" for a window still open.
    if is_both_out and message not in (17, 23, 5, 25, 7, 8, 15, 1, 2, 3, 4, 20, 21):
        new_temp += BOTH_OUT_OFFSET
        message   = 13

    # --- Clamp to valid range ---
    # Round to the nearest 0.5degC (RAMSES/Evohome native resolution) rather than to
    # a whole degree, so a fractional offset (e.g. a 1.5degC snow boost) isn't lost.
    new_temp = round(new_temp * 2) / 2
    new_temp = max(RADIATORS_OFF_TEMP, min(new_temp, MAX_ROOM_TEMP))

    # --- Final bedroom max limit ---
    if room_name in schedules.MAX_TEMP_LIMITS and message not in (1, 2, 3, 4, 7, 8, 15, 17, 23):
        if is_guest and room_name in schedules.MAX_TEMP_LIMITS_GUEST:
            max_limit = schedules.MAX_TEMP_LIMITS_GUEST[room_name]
        else:
            max_limit = schedules.MAX_TEMP_LIMITS[room_name]
        if new_temp > max_limit:
            new_temp = max_limit
            message  = 18

    # --- Message refinement ---
    # 23 = above target (passive warmth) is protected exactly like 17 (overheat)
    _OPEN_MESSAGES = {1, 2, 3, 4, 20, 21}

    if dev_temp is not None and abs(dev_temp - new_temp) <= TEMP_CHANGE_TOLERANCE:
        if message not in (1, 2, 3, 4, 5, 7, 8, 12, 13, 14, 15, 17, 18, 20, 21, 22, 23, 25):
            message = 11

    elif abs(dev_setpoint - new_temp) <= TEMP_CHANGE_TOLERANCE:
        if message not in (1, 2, 3, 4, 5, 7, 8, 12, 13, 14, 15, 17, 18, 20, 21, 22, 23, 25):
            message = 11

    # Window/door closed transition (open -> closed detection)
    if message not in _OPEN_MESSAGES and message not in (17, 23):
        if last_messages.get(room_name) in _OPEN_MESSAGES:
            message = 19

    # --- Send setpoint ---
    update_radiator_setpoint(
        dev_radiator, new_temp, message, room_name,
        last_setpoints, last_messages,
        log_buffer, changes_buffer,
        dev_temp, original_scheduled_temp, overheat_amount,
        force_log=(force_log_override if force_log_override is not None
                   else (current_minute == 0)),
        event_log_dump=event_log_dump,
    )
