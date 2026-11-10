#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    overheat_monitor.py
# Description: OverheatMonitor — tracks per-room overheat history, sends Pushover + email alerts
# Author:      CliveS & Claude Fable 5.2
# Date:        10-11-2026
# Version:     1.6

import os
import json
import tempfile
import time
import logging
from datetime import datetime as dt

import indigo  # noqa — available in plugin context

from log_stamp import stamp as _stamp

# _slog()'s level= wants a Python logging int; a STRING is silently
# ignored and the line logs as Info. Translate string levels at the choke point.
_LOG_LEVELS = {
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "ERROR":    logging.ERROR,
    "DEBUG":    logging.DEBUG,
    "CRITICAL": logging.CRITICAL,
}


def _slog(message, level="INFO"):
    """indigo.server.log with string-level translation (string levels are otherwise
    silently downgraded to Info by Indigo)."""
    lvl = _LOG_LEVELS.get(level.upper(), logging.INFO) if isinstance(level, str) else level
    indigo.server.log(_stamp(message), level=lvl)


# ---------------------------------------------------------------------------
# Alert thresholds (defaults — may be overridden per room via room_specific_thresholds)
# ---------------------------------------------------------------------------
ALERT_CRITICAL_TEMP    = 6.0   # Alert if overheat exceeds this many °C above target
ALERT_PERSISTENT_TEMP  = 4.0   # Alert if persistent overheat exceeds this

# The heating cycle saves the history every few minutes whenever it runs, so a file
# older than this belongs to an earlier spell of heating - most often last spring,
# reloaded by a restart after the summer shut-off. Tracking starts fresh instead.
HISTORY_MAX_AGE_SECS   = 3600

# A critical alert that no channel accepted is tried again after this long, until one
# does. Before 1.18.0 a failed send was recorded as sent and never tried again.
ALERT_RETRY_SECS       = 1800

# A room counts as overheating only after the heating has turned its radiator down, so
# every alert this monitor could send says "too warm, radiator already down". Nearly always
# that is the room cooling slowly (sun on the Conservatory, heat in the walls), and CliveS
# does not want telling (06-11-2026). False: log it, keep the status menu, send nothing and
# no all-clear. True restores the 1.25.0 behaviour: a Pushover and email alert, and an
# all-clear. Nothing can prove a valve stuck open, so with this False that fault is only
# visible in the log and in Plugins -> Evohome Control -> overheat status.
ALERT_WHEN_RADIATOR_DOWN = False


# A room's target that falls by this much or more in one step (the evening set-back, a
# boost ending, the En Suite morning finishing) starts the hold-off below.
TARGET_DROP_MIN        = 1.0

# No overheat judgement for this long after a room's target steps down. At 8pm the Dining
# Room's target falls from 21 to 15 while the room is still at the 21 it was heated to:
# six degrees "too warm" within one cycle, and an alert about a stuck valve that was only
# a room cooling (seven of sixteen alerts, 27-10 to 05-11-2026). The radiator is still
# turned down as before; this only delays the judgement. Set by the "overheatHoldOffMins"
# setting; 0 switches the hold-off off.
TARGET_DROP_HOLDOFF_MINS     = 90
TARGET_DROP_HOLDOFF_MAX_MINS = 720

# For this long after a step down, a room that is no warmer than the target it had before
# is a room that has not cooled yet, so the "too warm for six hours" rule does not speak.
# Without it a set-back at 8pm produced that alert at 3:30am (90 minutes of hold-off and
# six hours judged) for a room holding 19.5 against 15 that had been heated to 21.
TARGET_DROP_COOLING_SECS = 12 * 3600

# The alert names a step-down in the target while it is this recent. Longer than the
# cooling allowance above, so the first alert after that allowance still names it.
TARGET_DROP_MENTION_SECS = 18 * 3600


def coerce_holdoff_mins(value, default=TARGET_DROP_HOLDOFF_MINS):
    """The hold-off setting as whole minutes, 0 to TARGET_DROP_HOLDOFF_MAX_MINS.

    A Configure textfield comes back as a string and can be blank or not a number;
    anything unreadable gives the default, never an exception. bool is refused because
    int(True) is 1."""
    if isinstance(value, bool):
        return default
    try:
        minutes = int(float(str(value).strip()))
    except (ValueError, TypeError, OverflowError):
        return default
    return max(0, min(TARGET_DROP_HOLDOFF_MAX_MINS, minutes))


def _duration_text(hours):
    """'about 40 minutes', 'about an hour', 'about 3 hours', 'about 4 days' - as a
    person says it."""
    minutes = int(round(hours * 60))
    if minutes < 55:
        return f"about {max(5, 5 * round(minutes / 5))} minutes"
    whole = int(round(hours))
    if whole <= 1:
        return "about an hour"
    if whole < 36:
        return f"about {whole} hours"
    return f"about {int(round(hours / 24.0))} days"


def _clock_text(epoch):
    """'8pm', '8:02pm', '11:41am' - the time as a person says it."""
    when   = dt.fromtimestamp(epoch)
    hour   = when.hour % 12 or 12
    suffix = "am" if when.hour < 12 else "pm"
    if when.minute == 0:
        return f"{hour}{suffix}"
    return f"{hour}:{when.minute:02d}{suffix}"


def _clock_day_text(epoch, now):
    """'8:10pm', or '8:10pm yesterday' when that was the day before `now`."""
    days = (dt.fromtimestamp(now).date() - dt.fromtimestamp(epoch).date()).days
    return f"{_clock_text(epoch)} yesterday" if days == 1 else _clock_text(epoch)


def _number(value):
    """True for an int or float that is not a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _deg(value):
    """12.0 -> '12', 12.5 -> '12.5'."""
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _degrees(value):
    """'12 degrees', '12.5 degrees', but '1 degree' and '-1 degree'."""
    text = _deg(value)
    return f"{text} degree" if text in ("1", "-1") else f"{text} degrees"


class OverheatMonitor:
    """
    Monitors radiator overheating across heating cycles and sends alerts.

    Tracks overheat history for each room and sends:
    - Critical alerts when overheat is severe or prolonged
    - All-clear notifications when rooms return to normal

    history_path: absolute path to JSON persistence file (in plugin data dir)
    run_interval_mins: heating cycle interval (derived timer constants scale with it)
    """

    def __init__(self, history_path, run_interval_mins=5):
        self.history_file             = history_path
        # Defensive coercion: a blank/zero/non-numeric interval must never reach the
        # integer divisions below (ZeroDivisionError / TypeError on the startup path).
        try:
            run_interval_mins = int(run_interval_mins)
        except (ValueError, TypeError):
            run_interval_mins = 5
        if run_interval_mins <= 0:
            run_interval_mins = 5
        self.run_interval_mins        = run_interval_mins

        self.critical_overheat_temp   = ALERT_CRITICAL_TEMP
        self.critical_duration_cycles = (6 * 60) // run_interval_mins   # 6 hours
        self.persistent_overheat_temp = ALERT_PERSISTENT_TEMP
        self.all_clear_cycles         = max(2, 30 // run_interval_mins)  # 30 min stable
        self.outdoor_suppress_temp    = 12.0  # Suppress alerts if outdoor > 12°C
        # Minutes with no overheat judgement after a room's target steps down. plugin.py
        # sets it from the "overheatHoldOffMins" setting through coerce_holdoff_mins().
        self.target_drop_holdoff_mins = TARGET_DROP_HOLDOFF_MINS

        # Credentials set by plugin.py after construction (from PluginConfig)
        self.pushover_user_key = ""
        self.email_address     = ""

        # Optional callback fired when an overheat alert or all-clear is sent.
        # Signature: callback(event_id: str)  — e.g. "overheatAlert" / "overheatAllClear"
        # Set by plugin.py after construction. Used to fire Indigo plugin events.
        self.event_callback    = None

        # Per-room threshold overrides
        self.room_specific_thresholds = {
            "Bedroom 3": {
                "critical_overheat_temp":   10.0,
                "persistent_overheat_temp":  5.0,
                "monitor_enabled":          False,  # background heat from servers
            },
        }

        self.history = self.load_history()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_history(self, max_age_secs=HISTORY_MAX_AGE_SECS):
        """Load overheat history from JSON file or return empty dict.

        A file older than max_age_secs is ignored. On 28-09-2026 the file on disk
        was from 7 June, with three rooms still flagged CRITICAL and counters in the
        thousands, so a restart after the summer shut-off would have started every
        room in an overheat hold and sent all-clear alerts for rooms that were fine."""
        if os.path.exists(self.history_file):
            try:
                age = time.time() - os.path.getmtime(self.history_file)
            except OSError:
                age = 0
            if age > max_age_secs:
                # Said only when there was something to throw away: during the summer
                # shut-off the file is an empty record saved at the start of it, and a
                # line on every restart about discarding nothing would be noise.
                try:
                    with open(self.history_file, 'r', encoding='utf-8') as f:
                        had_rooms = bool(json.load(f))
                except Exception:
                    had_rooms = True
                if had_rooms:
                    saved = dt.fromtimestamp(time.time() - age)
                    _slog(f"[OverheatMonitor] The saved overheat history is from "
                          f"{saved.strftime('%d %b %H:%M').lstrip('0')}, too old to use, "
                          f"so every room starts fresh.")
                return {}
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                _slog(
                    f"[OverheatMonitor] Error loading history: {e}",
                    level="WARNING"
                )
        return {}

    def save_history(self):
        """Persist overheat history to JSON file (atomically: a crash mid-write
        must not corrupt the file and silently discard all overheat history)."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            # A temporary file of its own, so two writers can never share one.
            fd, tmp = tempfile.mkstemp(prefix=os.path.basename(self.history_file) + ".",
                                       suffix=".tmp", dir=os.path.dirname(self.history_file) or ".")
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            # mkstemp makes the file private (0600); keep the mode the old file had.
            try:
                os.chmod(tmp, os.stat(self.history_file).st_mode & 0o777)
            except OSError:
                os.chmod(tmp, 0o644)
            os.replace(tmp, self.history_file)
        except Exception as e:
            _slog(
                f"[OverheatMonitor] Error saving history: {e}",
                level="ERROR"
            )

    # ------------------------------------------------------------------
    # Room tracking
    # ------------------------------------------------------------------

    def initialize_room(self, room_name):
        """Ensure room entry exists in history with all required keys."""
        if room_name not in self.history:
            self.history[room_name] = {
                "consecutive_cycles":  0,
                "max_overheat":        0.0,
                "alert_sent":          False,
                "alert_type":          None,
                "alert_timestamp":     None,
                "last_update":         None,
                "stable_cycles":       0,
                "all_clear_sent":      True,
                "off_since_cycle":     0,
                "temp_history":        [],
                "is_coasting":         False,
                "judged_cycles":       0,
                "target_dropped_at":   None,
                "target_dropped_from": None,
                "target_dropped_to":   None,
            }

    def _note_target_change(self, room_data, previous_target, target_temp, now):
        """Record a step down in the room's target, or forget one when it rises again."""
        if not (isinstance(previous_target, (int, float))
                and isinstance(target_temp, (int, float))):
            return
        if previous_target - target_temp >= TARGET_DROP_MIN:
            # A further step down while the wait from an earlier one is still running
            # (21 to 19 to 17 an hour apart) does not start the wait again, and the room
            # goes on being compared with the highest of those targets. Otherwise a
            # stepped set-back could keep a room unjudged all evening.
            dropped_at = room_data.get("target_dropped_at")
            holdoff    = coerce_holdoff_mins(self.target_drop_holdoff_mins) * 60
            running    = (_number(dropped_at) and _number(room_data.get("target_dropped_from"))
                          and 0 <= now - dropped_at < holdoff)
            if running:
                room_data["target_dropped_from"] = max(room_data["target_dropped_from"],
                                                       previous_target)
            else:
                room_data["target_dropped_at"]   = now
                room_data["target_dropped_from"] = previous_target
            room_data["target_dropped_to"]   = target_temp
        elif target_temp - previous_target >= TARGET_DROP_MIN:
            # Raised again (a boost, the morning plan): the room is judged against the
            # higher target straight away.
            room_data["target_dropped_at"]   = None
            room_data["target_dropped_from"] = None
            room_data["target_dropped_to"]   = None

    def in_target_drop_holdoff(self, room_name, now=None):
        """True while the room's target stepped down less than the hold-off ago.

        A drop time in the future (the clock was put back) holds nothing off: a wrong
        clock must not silence the judgement for longer than the hold-off."""
        room_data  = self.history.get(room_name) or {}
        dropped_at = room_data.get("target_dropped_at")
        if not isinstance(dropped_at, (int, float)) or isinstance(dropped_at, bool):
            return False
        holdoff = coerce_holdoff_mins(self.target_drop_holdoff_mins) * 60
        age     = (time.time() if now is None else now) - dropped_at
        return 0 <= age < holdoff

    def update_room(self, room_name, is_overheating, overheat_amount,
                    current_temp, target_temp, outdoor_temp, is_passive=False,
                    reduced_temp=None):
        """
        Update overheat tracking for a room and send alerts if thresholds crossed.
        Called every heating cycle for every room regardless of overheat state.

        target_temp is the target the decision was judged against, and reduced_temp the
        setting it chose (1.25.0), so the alert quotes the real arithmetic.
        """
        self.initialize_room(room_name)
        room_data = self.history[room_name]

        # A step down in the target starts the hold-off (1.27.0). Read before the new
        # target is stored below.
        now = time.time()
        self._note_target_change(room_data, room_data.get("target_temp"), target_temp, now)

        # Store current conditions for alert messages
        room_data["current_temp"]  = current_temp
        room_data["target_temp"]   = target_temp
        room_data["outdoor_temp"]  = outdoor_temp
        room_data["reduced_temp"]  = reduced_temp
        room_data["passive"]       = bool(is_passive)
        room_data["last_update"]   = dt.now().strftime("%d-%m-%Y %H:%M:%S")

        # Room-specific threshold overrides
        if room_name in self.room_specific_thresholds:
            room_config = self.room_specific_thresholds[room_name]
            if not room_config.get("monitor_enabled", True):
                room_data["consecutive_cycles"] = 0
                room_data["judged_cycles"]      = 0
                room_data["stable_cycles"]      = 0
                return
            critical_temp   = room_config.get("critical_overheat_temp",   self.critical_overheat_temp)
            persistent_temp = room_config.get("persistent_overheat_temp", self.persistent_overheat_temp)
        else:
            critical_temp   = self.critical_overheat_temp
            persistent_temp = self.persistent_overheat_temp

        if is_overheating:
            # A history file saved before 1.27.0 has no judged_cycles: carry on from
            # the count it does have.
            judged_before = room_data.get("judged_cycles")
            if not isinstance(judged_before, int) or isinstance(judged_before, bool):
                judged_before = room_data["consecutive_cycles"]
            room_data["consecutive_cycles"] += 1
            room_data["stable_cycles"]       = 0

            # The target has only just stepped down, so the room is "too warm" because
            # it is still at the temperature it was heated to. The radiator is turned
            # down as usual and the status menu lists the room. For the hold-off the room
            # is judged against the target it had BEFORE the step down, not left unjudged:
            # a room climbing through the set-back (27 against an earlier 21) is a fault
            # whatever the timetable did, and must not wait 90 minutes to be said. A room
            # under the thresholds against that earlier target is only cooling: no alert,
            # no log line, and the time does not count towards "too warm for six hours" or
            # the worst figure an all-clear quotes. The count is paused, not cleared:
            # hours of real overheating before the step down still stand.
            judge_amount = overheat_amount
            dropped_from = room_data.get("target_dropped_from")
            if self.in_target_drop_holdoff(room_name, now):
                over_earlier = (current_temp - dropped_from
                                if _number(current_temp) and _number(dropped_from) else None)
                if over_earlier is None or over_earlier < min(persistent_temp, critical_temp):
                    room_data["judged_cycles"] = judged_before
                    return
                judge_amount = over_earlier
            room_data["judged_cycles"] = judged_before + 1

            if overheat_amount > room_data["max_overheat"]:
                room_data["max_overheat"] = overheat_amount

            should_alert = False
            alert_type   = None

            # For half a day after a step down, a room no warmer than its earlier target
            # has simply not cooled: the six-hour rule waits. A room above that earlier
            # target, or any room once the half day is up, is judged as usual.
            dropped_at   = room_data.get("target_dropped_at")
            still_cooling = (_number(dropped_at) and _number(dropped_from)
                             and _number(current_temp)
                             and 0 <= now - dropped_at < TARGET_DROP_COOLING_SECS
                             and current_temp <= dropped_from)

            if judge_amount >= critical_temp:
                should_alert = True
                alert_type   = "CRITICAL_IMMEDIATE"
            elif (judge_amount >= persistent_temp and not still_cooling and
                  room_data["judged_cycles"] >= self.critical_duration_cycles):
                should_alert = True
                alert_type   = "CRITICAL_PERSISTENT"

            if should_alert and not room_data["alert_sent"]:
                if not ALERT_WHEN_RADIATOR_DOWN:
                    _slog(
                        f"[OverheatMonitor] {room_name} is {overheat_amount:.1f} degrees over "
                        f"its target with its radiator already turned down - no alert sent, "
                        f"the room is cooling."
                    )
                    room_data["alert_sent"]     = True
                    room_data["alert_type"]     = "PASSIVE_GAIN"
                    room_data["all_clear_sent"] = False
                    return
                # A room that stays too warm after its radiator has been turned down used to
                # be called passive warmth and get no alert at all. Nothing proves the valve
                # closed - no zone reports its valve position - so a valve stuck open looked
                # exactly the same (1.25.0, review finding 5). It now alerts, at normal
                # priority, and the message names both explanations.
                if outdoor_temp is not None and outdoor_temp > self.outdoor_suppress_temp:
                    _slog(
                        f"[OverheatMonitor] {room_name}: alert suppressed "
                        f"(outdoor {outdoor_temp:.1f}degC > {self.outdoor_suppress_temp}degC)"
                    )
                    room_data["alert_sent"]      = True
                    room_data["alert_type"]      = "OUTDOOR_SUPPRESSED"
                    room_data["all_clear_sent"]  = False
                else:
                    retry_at = room_data.get("alert_retry_at")
                    if retry_at is None or time.time() >= retry_at:
                        # The trigger fires once per overheat, on the first try; a
                        # retry is about the notification, not a new event.
                        delivered = self.send_critical_alert(
                            room_name, alert_type, overheat_amount,
                            fire_event=retry_at is None)
                        if delivered:
                            room_data["alert_sent"]      = True
                            room_data["alert_type"]      = alert_type
                            room_data["alert_timestamp"] = dt.now().strftime("%d-%m-%Y %H:%M:%S")
                            room_data["all_clear_sent"]  = False
                            room_data["alert_retry_at"]  = None
                        else:
                            room_data["alert_retry_at"]  = time.time() + ALERT_RETRY_SECS

        else:
            room_data["consecutive_cycles"] = 0
            room_data["judged_cycles"]      = 0
            room_data["stable_cycles"]     += 1
            # An alert still waiting to be delivered is dropped once the room is fine.
            room_data["alert_retry_at"]     = None

            if (room_data["alert_sent"] and
                    not room_data["all_clear_sent"] and
                    room_data["stable_cycles"] >= self.all_clear_cycles):
                suppressed_types = {"PASSIVE_GAIN", "OUTDOOR_SUPPRESSED"}
                if room_data.get("alert_type") in suppressed_types:
                    # Was suppressed — reset silently, no Pushover all-clear
                    _slog(
                        f"[OverheatMonitor] {room_name}: returned to normal "
                        f"(was {room_data['alert_type']}, no alert was sent)"
                    )
                else:
                    self.send_all_clear(room_name)
                room_data["alert_sent"]     = False
                room_data["alert_type"]     = None
                room_data["max_overheat"]   = 0.0
                room_data["all_clear_sent"] = True

    # ------------------------------------------------------------------
    # Alert sending
    # ------------------------------------------------------------------

    def send_critical_alert(self, room_name, alert_type, overheat_amount, fire_event=True):
        """Send a critical overheat alert by Pushover and email.

        Returns True when at least one channel took it, or when neither is set up
        (then there is nothing to try again). False means every channel that is set
        up refused it, and the caller tries again after ALERT_RETRY_SECS.
        """
        room_data    = self.history[room_name]
        current_temp = room_data["current_temp"]
        target_temp  = room_data["target_temp"]
        outdoor_temp = room_data["outdoor_temp"]

        # The setting the heating actually chose; before 1.25.0 it was worked out again
        # here from the plain schedule, and could differ from what was sent.
        reduced_temp = room_data.get("reduced_temp")
        if not isinstance(reduced_temp, (int, float)):
            reduced_temp = max(12.0, target_temp - 6.0)
        # How long the room has been JUDGED too warm: the hold-off after a step down in
        # its target is left out, so "too warm for about 6 hours" is six hours of it.
        judged = room_data.get("judged_cycles")
        if not isinstance(judged, int) or isinstance(judged, bool):
            judged = room_data["consecutive_cycles"]
        hours        = (judged * self.run_interval_mins) / 60.0
        passive      = bool(room_data.get("passive"))
        # How long the heating has had this radiator turned down, by its own count.
        off_cycles = room_data.get("off_since_cycle", 0)
        if not isinstance(off_cycles, int) or isinstance(off_cycles, bool):
            off_cycles = 0
        down_hours   = (off_cycles * self.run_interval_mins) / 60.0

        title = f"The {room_name} is {_degrees(overheat_amount)} too warm"
        if alert_type == "CRITICAL_IMMEDIATE":
            opening = (f"The {room_name} is at {_degrees(current_temp)}, "
                       f"{_deg(overheat_amount)} more than the {_deg(target_temp)} it should be.")
        else:
            opening = (f"The {room_name} has been too warm for {_duration_text(hours)}. It is "
                       f"at {_degrees(current_temp)} against the {_deg(target_temp)} it "
                       f"should be.")
        if isinstance(outdoor_temp, (int, float)) and not isinstance(outdoor_temp, bool):
            outside = f" It is {_degrees(outdoor_temp)} outside."
        else:
            outside = ""
        # A recent step down in the target is said. "Cooling from its earlier setting"
        # is only claimed for a room that is no warmer than that setting; a room above
        # it is told so, because the step down does not explain it.
        stepped    = ""
        now        = time.time()
        dropped_at = room_data.get("target_dropped_at")
        dropped_from = room_data.get("target_dropped_from")
        dropped_to   = room_data.get("target_dropped_to")
        if (_number(dropped_at) and _number(dropped_from) and _number(dropped_to)
                and 0 <= now - dropped_at < TARGET_DROP_MENTION_SECS):
            stepped = (f" Its target came down from {_deg(dropped_from)} to "
                       f"{_degrees(dropped_to)} at {_clock_day_text(dropped_at, now)}")
            if _number(current_temp) and current_temp <= dropped_from + 0.5:
                stepped += ", so some of this is the room cooling from its earlier setting."
            else:
                stepped += ", but the room is warmer than that earlier setting too."
        # Said as it stands when the message goes: how long the radiator has really been
        # turned down. Before 1.27.0 this read "for a while" three minutes after the
        # target had dropped. The heating's own count starts again when a coast ends with
        # the radiator still down, so "just" is only said when the room has not already
        # been judged too warm for ten minutes or more.
        if off_cycles * self.run_interval_mins >= 10:
            turned_down = (f" The heating has had its radiator turned down for "
                           f"{_duration_text(down_hours)}, now to {_degrees(reduced_temp)}")
        elif judged * self.run_interval_mins >= 10:
            turned_down = (f" The heating has turned its radiator down to "
                           f"{_degrees(reduced_temp)}")
        else:
            turned_down = (f" The heating has just turned its radiator down to "
                           f"{_degrees(reduced_temp)}")
        if passive:
            advice = (f"{turned_down}, and the room is still too warm. Sun or other heat "
                      f"can do that, but a valve stuck open or with flat batteries looks "
                      f"the same, so please check it.")
        else:
            advice = (f"{turned_down}. A room this far over usually means the radiator "
                      f"valve is stuck open or its batteries are flat, so please check it.")
        message = f"{opening}{outside}{stepped}{advice}"

        pushed  = self._send_pushover(title, message, priority=0 if passive else 1)
        emailed = self._send_email(title, message)
        if fire_event and self.event_callback:
            try:
                self.event_callback("overheatAlert")
            except Exception:
                pass

        if pushed or emailed:
            how = " and ".join(n for n, ok in (("Pushover", pushed), ("email", emailed)) if ok)
            _slog(f"[OverheatMonitor] {room_name} is {overheat_amount:.1f} degrees over its "
                  f"target - alert sent by {how}.", level="WARNING")
            return True
        if not self._any_channel():
            _slog(f"[OverheatMonitor] {room_name} is {overheat_amount:.1f} degrees over its "
                  f"target, but neither Pushover nor email is set up to send the alert.",
                  level="WARNING")
            return True
        _slog(f"[OverheatMonitor] {room_name} is {overheat_amount:.1f} degrees over its "
              f"target, and the alert could not be sent. Trying again in "
              f"{ALERT_RETRY_SECS // 60} minutes.", level="ERROR")
        return False

    def send_all_clear(self, room_name):
        """Send all-clear notification when room returns to normal."""
        room_data    = self.history[room_name]
        current_temp = room_data["current_temp"]
        target_temp  = room_data["target_temp"]

        when = ""
        if room_data["alert_timestamp"]:
            try:
                alert_time = dt.strptime(room_data["alert_timestamp"], "%d-%m-%Y %H:%M:%S")
                hours_ago  = (dt.now() - alert_time).total_seconds() / 3600.0
                when       = f" The alert went out {_duration_text(hours_ago)} ago."
            except (ValueError, TypeError):
                pass

        title = f"The {room_name} is back to normal"
        message = (
            f"The {room_name} is at {_degrees(current_temp)} against the "
            f"{_deg(target_temp)} it should be, so it has settled.{when} At its worst it was "
            f"{_degrees(room_data['max_overheat'])} too warm. Nothing needs doing."
        )

        self._send_pushover(title, message, priority=-1)
        self._send_email(title, message)
        _slog(
            f"[OverheatMonitor] ALL CLEAR sent for {room_name}: room returned to normal"
        )
        if self.event_callback:
            try:
                self.event_callback("overheatAllClear")
            except Exception:
                pass

    def _any_channel(self):
        """True when Pushover is enabled or an email address is set."""
        if self.email_address:
            return True
        try:
            plugin = indigo.server.getPlugin("io.thechad.indigoplugin.pushover")
            return bool(plugin is not None and plugin.isEnabled())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------

    def _send_pushover(self, title, message, priority=-1):
        """Send alert via Pushover plugin."""
        try:
            plugin = indigo.server.getPlugin("io.thechad.indigoplugin.pushover")
            if plugin is None or not plugin.isEnabled():
                _slog(
                    "[OverheatMonitor] Pushover plugin not available",
                    level="WARNING"
                )
                return False
            props = {
                "msgTitle":        title,
                "msgBody":         message,
                "msgSound":        "vibrate",
                "msgPriority":     str(priority),
                "msgDevice":       "",
                "msgSupLinkUrl":   "",
                "msgSupLinkTitle": "",
            }
            # The user key from IndigoSecrets.py or the Configure dialog. Sent only
            # when one is set: without it the Pushover plugin uses its own default
            # user, which is what a blank setting has always meant.
            user_key = str(self.pushover_user_key or "").strip()
            if user_key:
                props["msgUser"] = user_key
            plugin.executeAction("send", props=props)
            return True
        except Exception as e:
            _slog(
                f"[OverheatMonitor] Pushover error: {e}",
                level="ERROR"
            )
            return False

    def _send_email(self, title, message):
        """Send alert via Email+ plugin using sendEmailTo."""
        if not self.email_address:
            return False
        try:
            indigo.server.sendEmailTo(
                self.email_address,
                subject=title,
                body=message
            )
            return True
        except Exception as e:
            _slog(
                f"[OverheatMonitor] Email error: {e}",
                level="ERROR"
            )
            return False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status_summary(self):
        """Return a multi-line string summarising current overheat status."""
        lines = ["Above-Target / Overheat Monitor Status", "=" * 50]
        found = False
        # Snapshot the items: these status readers run on the menu/action thread
        # while the cycle thread's update_room may add a room key — iterating the
        # live dict would risk 'dictionary changed size during iteration'.
        for room_name, data in sorted(list(self.history.items())):
            if data.get("consecutive_cycles", 0) > 0:
                found = True
                hours      = (data["consecutive_cycles"] * self.run_interval_mins) / 60.0
                off_cycles = data.get("off_since_cycle", 0)
                if off_cycles >= 3:
                    label = "Above Target (solar/passive)"
                else:
                    label = "Overheating (radiator)"
                lines.append(
                    f"{room_name:<20s} - {label} for {hours:.1f}h "
                    f"(max {data['max_overheat']:+.1f}degC)"
                )
                if data.get("alert_sent"):
                    alert_labels = {
                        "PASSIVE_GAIN":       "Passive gain (no alert sent)",
                        "OUTDOOR_SUPPRESSED": "Outdoor temp (no alert sent)",
                        "CRITICAL_IMMEDIATE": "CRITICAL IMMEDIATE (alert sent)",
                        "CRITICAL_PERSISTENT":"CRITICAL PERSISTENT (alert sent)",
                    }
                    alert_str = alert_labels.get(
                        data["alert_type"], data["alert_type"]
                    )
                    lines.append(f"{'':20s}   Alert: {alert_str}")
        if not found:
            lines.append("No rooms above target")
        return "\n".join(lines)

    def get_overheating_rooms(self):
        """Return sorted list of room names currently overheating."""
        # Snapshot for the same cross-thread reason as get_status_summary.
        return sorted(
            r for r, d in list(self.history.items())
            if d.get("consecutive_cycles", 0) > 0
        )

    def reset_all_tracking(self):
        """Clear per-room overheat counters and alert flags for every room.

        Called once when the whole-house summer shut-off engages: during lockout the
        cycle stops calling update_room, so any room left mid-alert would keep a stale
        alert_sent=True for the whole season and could suppress a genuine alert when
        heating resumes. Resetting here means tracking starts clean at lockout end.

        Every room is dropped outright, temperature history and peak included, and
        the empty history is SAVED. Before 1.12.0 only the counters were reset and
        only in memory, so the file kept last spring's alerts and a restart brought
        them back; the rate of rise was also worked out against June readings.
        """
        self.history.clear()
        self.save_history()
