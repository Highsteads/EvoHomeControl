#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    overheat_monitor.py
# Description: OverheatMonitor — tracks per-room overheat history, sends Pushover + email alerts
# Author:      CliveS & Claude Sonnet 4.6
# Date:        15-04-2026
# Version:     1.0

import os
import json
from datetime import datetime as dt

import indigo  # noqa — available in plugin context

# ---------------------------------------------------------------------------
# Alert thresholds (defaults — may be overridden per room via room_specific_thresholds)
# ---------------------------------------------------------------------------
ALERT_CRITICAL_TEMP    = 6.0   # Alert if overheat exceeds this many °C above target
ALERT_PERSISTENT_TEMP  = 4.0   # Alert if persistent overheat exceeds this


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
        self.run_interval_mins        = run_interval_mins

        self.critical_overheat_temp   = ALERT_CRITICAL_TEMP
        self.critical_duration_cycles = (6 * 60) // run_interval_mins   # 6 hours
        self.persistent_overheat_temp = ALERT_PERSISTENT_TEMP
        self.all_clear_cycles         = max(2, 30 // run_interval_mins)  # 30 min stable
        self.outdoor_suppress_temp    = 12.0  # Suppress alerts if outdoor > 12°C

        # Credentials set by plugin.py after construction (from PluginConfig)
        self.pushover_user_key = ""
        self.email_address     = ""

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

    def load_history(self):
        """Load overheat history from JSON file or return empty dict."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                indigo.server.log(
                    f"[OverheatMonitor] Error loading history: {e}",
                    level="WARNING"
                )
        return {}

    def save_history(self):
        """Persist overheat history to JSON file."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            indigo.server.log(
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
                    current_temp, target_temp, outdoor_temp):
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
                if outdoor_temp is not None and outdoor_temp > self.outdoor_suppress_temp:
                    indigo.server.log(
                        f"[OverheatMonitor] {room_name}: alert suppressed "
                        f"(outdoor {outdoor_temp:.1f}°C > {self.outdoor_suppress_temp}°C)"
                    )
                else:
                    self.send_critical_alert(room_name, alert_type, overheat_amount)
                    room_data["alert_sent"]      = True
                    room_data["alert_type"]      = alert_type
                    room_data["alert_timestamp"] = dt.now().strftime("%d-%m-%Y %H:%M:%S")
                    room_data["all_clear_sent"]  = False

        else:
            room_data["consecutive_cycles"] = 0
            room_data["stable_cycles"]     += 1

            if (room_data["alert_sent"] and
                    not room_data["all_clear_sent"] and
                    room_data["stable_cycles"] >= self.all_clear_cycles):
                self.send_all_clear(room_name)
                room_data["alert_sent"]     = False
                room_data["alert_type"]     = None
                room_data["max_overheat"]   = 0.0
                room_data["all_clear_sent"] = True

    # ------------------------------------------------------------------
    # Alert sending
    # ------------------------------------------------------------------

    def send_critical_alert(self, room_name, alert_type, overheat_amount):
        """Send critical overheat alert via Pushover and email."""
        room_data    = self.history[room_name]
        current_temp = room_data["current_temp"]
        target_temp  = room_data["target_temp"]
        outdoor_temp = room_data["outdoor_temp"]

        duration_hours = (room_data["consecutive_cycles"] * self.run_interval_mins) / 60.0

        reduced_temp = max(12.0, target_temp - 6.0)
        valve_status = f"REDUCED (backed off 6°C to {reduced_temp:.1f}°C)"

        if alert_type == "CRITICAL_IMMEDIATE":
            title  = f"CRITICAL OVERHEAT - {room_name}"
            reason = (
                f"SEVERE OVERHEAT: {overheat_amount:+.1f}degC ABOVE TARGET\n"
                f"Room is {overheat_amount:.1f}degC above target.\n"
                f"Possible TRV failure or stuck valve."
            )
        else:
            title  = f"CRITICAL OVERHEAT - {room_name}"
            reason = (
                f"PERSISTENT OVERHEAT FOR {duration_hours:.1f} HOURS\n"
                f"Room has been overheating for {duration_hours:.1f} hours.\n"
                f"Check TRV operation and valve position."
            )

        message = (
            f"{title}\n"
            f"{'=' * 35}\n"
            f"Current Temp:     {current_temp:.1f}degC\n"
            f"Target Temp:      {target_temp:.1f}degC\n"
            f"Overheat Amount:  {overheat_amount:+.1f}degC\n"
            f"Max Overheat:     {room_data['max_overheat']:+.1f}degC\n"
            f"Duration:         {duration_hours:.2f} hours\n"
            f"Valve Status:     {valve_status}\n"
            f"\n"
            f"Outdoor Temp:     {outdoor_temp:.1f}degC\n"
            f"\n"
            f"{reason}\n"
            f"\n"
            f"Action Required:\n"
            f"- Check TRV valve operation\n"
            f"- Verify TRV batteries (if wireless)\n"
            f"- Ensure valve is not mechanically stuck\n"
        )

        self._send_pushover(title, message, priority=1)
        self._send_email(title, message)
        indigo.server.log(
            f"[OverheatMonitor] CRITICAL OVERHEAT ALERT sent for {room_name}: "
            f"{overheat_amount:+.1f}degC over target",
            level="WARNING"
        )

    def send_all_clear(self, room_name):
        """Send all-clear notification when room returns to normal."""
        room_data    = self.history[room_name]
        current_temp = room_data["current_temp"]
        target_temp  = room_data["target_temp"]

        time_text = "Unknown"
        if room_data["alert_timestamp"]:
            try:
                alert_time = dt.strptime(room_data["alert_timestamp"], "%d-%m-%Y %H:%M:%S")
                hours_ago  = (dt.now() - alert_time).total_seconds() / 3600.0
                time_text  = f"{hours_ago:.2f} hours ago"
            except ValueError:
                pass

        title = f"ALL CLEAR - {room_name}"
        message = (
            f"{title}\n"
            f"{'=' * 35}\n"
            f"Room has returned to target temperature.\n"
            f"\n"
            f"Current Temp:     {current_temp:.1f}degC\n"
            f"Target Temp:      {target_temp:.1f}degC\n"
            f"Temperature Diff: {current_temp - target_temp:+.1f}degC\n"
            f"\n"
            f"Previous Alert:   {time_text}\n"
            f"Peak Overheat:    {room_data['max_overheat']:+.1f}degC\n"
            f"Alert Type:       {room_data['alert_type']}\n"
            f"\n"
            f"[OK] Room is now stable\n"
            f"[OK] No action needed\n"
        )

        self._send_pushover(title, message, priority=-1)
        self._send_email(title, message)
        indigo.server.log(
            f"[OverheatMonitor] ALL CLEAR sent for {room_name}: room returned to normal"
        )

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------

    def _send_pushover(self, title, message, priority=-1):
        """Send alert via Pushover plugin."""
        try:
            plugin = indigo.server.getPlugin("io.thechad.indigoplugin.pushover")
            if plugin is None or not plugin.isEnabled():
                indigo.server.log(
                    "[OverheatMonitor] Pushover plugin not available",
                    level="WARNING"
                )
                return False
            plugin.executeAction("send", props={
                "msgTitle":        title,
                "msgBody":         message,
                "msgSound":        "vibrate",
                "msgPriority":     priority,
                "msgDevice":       "",
                "msgSupLinkUrl":   "",
                "msgSupLinkTitle": "",
            })
            return True
        except Exception as e:
            indigo.server.log(
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
            indigo.server.log(
                f"[OverheatMonitor] Email error: {e}",
                level="ERROR"
            )
            return False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status_summary(self):
        """Return a multi-line string summarising current overheat status."""
        lines = ["Overheat Monitor Status", "=" * 50]
        found = False
        for room_name, data in sorted(self.history.items()):
            if data.get("consecutive_cycles", 0) > 0:
                found = True
                hours = (data["consecutive_cycles"] * self.run_interval_mins) / 60.0
                lines.append(
                    f"{room_name:<20s} - Overheating for {hours:.1f}h "
                    f"(max {data['max_overheat']:+.1f}degC)"
                )
                if data.get("alert_sent"):
                    lines.append(f"{'':20s}   Alert: {data['alert_type']}")
        if not found:
            lines.append("No rooms currently overheating")
        return "\n".join(lines)

    def get_overheating_rooms(self):
        """Return sorted list of room names currently overheating."""
        return sorted(
            r for r, d in self.history.items()
            if d.get("consecutive_cycles", 0) > 0
        )
