#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    log_stamp.py
# Description: One on/off switch for the [HH:MM:SS.mmm] stamp on every line this
#              plugin writes to the Indigo Event Log, shared by all its modules so
#              the Toggle Timestamps menu item reaches every line, not a handful.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
#
# The plugin's lines reach the Event Log by four routes: plugin.py's _log(),
# heating_logic's _log(), the _slog() helpers in weather.py and overheat_monitor.py,
# and self.logger (stamped by plugin_utils' filter). Before this module each of the
# first three stamped its own lines unconditionally or not at all, so the menu item
# only moved the few lines that went through self.logger. The daily radiator log
# file keeps its stamps whatever the switch says: a file line is a record, and a
# record needs its time.

from datetime import datetime

_STATE = {"enabled": True}   # mutable container: no module global rebinding


def set_enabled(enabled):
    """Turn the Event Log stamp on or off for every module at once."""
    _STATE["enabled"] = bool(enabled)


def is_enabled():
    return _STATE["enabled"]


def now_stamp():
    """The stamp itself, always - for the daily log file."""
    return f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]"


def stamp(message):
    """message with the stamp in front when the switch is on, else unchanged."""
    if _STATE["enabled"]:
        return f"{now_stamp()} {message}"
    return message
