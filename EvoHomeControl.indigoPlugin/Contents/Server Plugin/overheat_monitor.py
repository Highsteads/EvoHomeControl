#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    overheat_monitor.py
# Description: OverheatMonitor — tracks per-room overheat history, sends Pushover + email alerts
# Author:      CliveS & Claude Sonnet 4.6
# Date:        30-04-2026
# Version:     1.4

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


def _duration_text(hours):
    """'about 40 minutes', 'about an hour', 'about 3 hours' - as a person says it."""
    minutes = int(round(hours * 60))
    if minutes < 55:
        return f"about {max(5, 5 * round(minutes / 5))} minutes"
    whole = int(round(hours))
    return "about an hour" if whole <= 1 else f"about {whole} hours"


def _deg(value):
    """12.0 -> '12', 12.5 -> '12.5'."""
    return f"{value:.1f}".rstrip("0").rstrip(".")


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
            }

    def update_room(self, room_name, is_overheating, overheat_amount,
                    current_temp, target_temp, outdoor_temp, is_passive=False):
        """
        Update overheat tracking for a room and send alerts if thresholds crossed.
        Called every heating cycle for every room regardless of overheat state.
        """
        self.initialize_room(room_name)
        room_data = self.history[room_name]

        # Store current conditions for alert messages
        room_data["current_temp"]  = current_temp
        room_data["target_temp"]   = target_temp
        room_data["outdoor_temp"]  = outdoor_temp
        room_data["last_update"]   = dt.now().strftime("%d-%m-%Y %H:%M:%S")

        # Room-specific threshold overrides
        if room_name in self.room_specific_thresholds:
            room_config = self.room_specific_thresholds[room_name]
            if not room_config.get("monitor_enabled", True):
                room_data["consecutive_cycles"] = 0
                room_data["stable_cycles"]      = 0
                return
            critical_temp   = room_config.get("critical_overheat_temp",   self.critical_overheat_temp)
            persistent_temp = room_config.get("persistent_overheat_temp", self.persistent_overheat_temp)
        else:
            critical_temp   = self.critical_overheat_temp
            persistent_temp = self.persistent_overheat_temp

        if is_overheating:
            room_data["consecutive_cycles"] += 1
            room_data["stable_cycles"]       = 0

            if overheat_amount > room_data["max_overheat"]:
                room_data["max_overheat"] = overheat_amount

            should_alert = False
            alert_type   = None

            if overheat_amount >= critical_temp:
                should_alert = True
                alert_type   = "CRITICAL_IMMEDIATE"
            elif (overheat_amount >= persistent_temp and
                  room_data["consecutive_cycles"] >= self.critical_duration_cycles):
                should_alert = True
                alert_type   = "CRITICAL_PERSISTENT"

            if should_alert and not room_data["alert_sent"]:
                if is_passive:
                    # Valve has been off 3+ cycles — passive warmth (solar/internal gain)
                    # Not a TRV fault; suppress alert and mark sent so it does not
                    # re-trigger every cycle.
                    _slog(
                        f"[OverheatMonitor] {room_name}: alert suppressed "
                        f"(passive warmth — solar/internal gain, no TRV action)"
                    )
                    room_data["alert_sent"]      = True
                    room_data["alert_type"]      = "PASSIVE_GAIN"
                    room_data["all_clear_sent"]  = False
                elif outdoor_temp is not None and outdoor_temp > self.outdoor_suppress_temp:
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

        # The backoff is clamped to a 12degC floor, so report the real setting.
        reduced_temp = max(12.0, target_temp - 6.0)
        hours        = (room_data["consecutive_cycles"] * self.run_interval_mins) / 60.0

        title = f"The {room_name} is {_deg(overheat_amount)} degrees too warm"
        if alert_type == "CRITICAL_IMMEDIATE":
            opening = (f"The {room_name} is at {_deg(current_temp)} degrees, "
                       f"{_deg(overheat_amount)} more than the {_deg(target_temp)} it should be.")
        else:
            opening = (f"The {room_name} has been too warm for {_duration_text(hours)}. It is "
                       f"at {_deg(current_temp)} degrees against the {_deg(target_temp)} it "
                       f"should be.")
        if isinstance(outdoor_temp, (int, float)):
            outside = f" It is {_deg(outdoor_temp)} degrees outside."
        else:
            outside = ""
        message = (
            f"{opening}{outside} The heating has turned its radiator down to "
            f"{_deg(reduced_temp)} degrees. A room this far over usually means the "
            f"radiator valve is stuck open or its batteries are flat, so please check it."
        )

        pushed  = self._send_pushover(title, message, priority=1)
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
            f"The {room_name} is at {_deg(current_temp)} degrees against the "
            f"{_deg(target_temp)} it should be, so it has settled.{when} At its worst it was "
            f"{_deg(room_data['max_overheat'])} degrees too warm. Nothing needs doing."
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
