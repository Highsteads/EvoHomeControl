#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_event_log_volume.py
# Description: Unit tests for what this plugin puts in the SHARED Indigo event
#              log: the once-on-change summer shut-off latch, and the
#              quiet-by-default hourly weather + room-table dump.
#              Run from this directory with:  python3 test_event_log_volume.py
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5
# Date:        06-09-2026
# Version:     1.0
#
# Why these tests exist. The Indigo event log is the estate's dashboard and every
# plugin shares it. Measured from the dated event logs, this plugin put 23 lines
# a day in it during the summer shut-off (106 of 113 over the 5 days to
# 06-09-2026 were one repeated sentence) and 965-991 lines a day in season. The
# tests below pin the two behaviours that keep it quiet, and - more importantly -
# pin that faults are NOT quietened: Log_Error_Watch.py reads the event log and
# nothing else, so a warning that only reaches a plugin's own file is a warning
# nobody is watching.

import os
import sys
import threading
import types
import unittest
from datetime import datetime

# Resolve sibling source files from THIS file, never from the working directory.
# CI runs `unittest discover` from inside this folder, but pytest from the repo
# root leaves cwd there and only puts this folder on sys.path - so a relative
# open() passes under one runner and raises FileNotFoundError under the other.
_HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Stub `indigo` so plugin.py / heating_logic.py import outside Indigo.
#
# Augment an existing stub rather than replacing it: test_heating_logic.py
# installs its own, and whichever test module unittest imports first wins.
# Replacing it would leave modules bound to a stub the other file then mutates.
# ---------------------------------------------------------------------------
class _ServerStub:
    @staticmethod
    def log(msg, level=None, isError=False, **kwargs):
        pass  # silent by default; tests swap in a recorder

    @staticmethod
    def getInstallFolderPath():
        return "/tmp/evohome-test"


class _PluginBaseStub:
    def __init__(self, *args, **kwargs):
        pass


_existing = sys.modules.get("indigo")
_indigo = _existing if _existing is not None else types.ModuleType("indigo")
if not hasattr(_indigo, "server") or not hasattr(_indigo.server, "getInstallFolderPath"):
    _indigo.server = _ServerStub()
for _name, _value in (
    ("PluginBase", _PluginBaseStub),
    ("devices",    {}),
    ("variables",  {}),
    ("thermostat", types.SimpleNamespace(setHeatSetpoint=lambda *a, **k: None)),
    ("device",     types.SimpleNamespace(turnOn=lambda *a, **k: None,
                                         turnOff=lambda *a, **k: None)),
    ("trigger",    types.SimpleNamespace(execute=lambda *a, **k: None)),
):
    if not hasattr(_indigo, _name):
        setattr(_indigo, _name, _value)
sys.modules["indigo"] = _indigo

if "schedules" not in sys.modules:
    _schedules = types.ModuleType("schedules")
    _schedules.MAX_TEMP_LIMITS       = {}
    _schedules.MAX_TEMP_LIMITS_GUEST = {}
    _schedules.BOOST_AMOUNTS         = {}
    _schedules.TIMED_BOOST_ROOMS     = set()
    sys.modules["schedules"] = _schedules

import heating_logic as hl      # noqa: E402
import plugin as plugin_mod     # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class RecordingLog:
    """Stands in for indigo.server.log and records every line it is handed."""

    def __init__(self):
        self.lines = []

    def __call__(self, msg, level=None, isError=False, **kwargs):
        self.lines.append((msg, level))

    @property
    def messages(self):
        return [m for m, _ in self.lines]

    def containing(self, text):
        return [m for m in self.messages if text in m]


class RecordingLogger:
    """Stands in for self.logger (the plugin's OWN log file, no event-log echo)."""

    def __init__(self):
        self.debug_lines = []
        self.info_lines  = []

    def debug(self, msg, *a, **k):
        self.debug_lines.append(msg)

    def info(self, msg, *a, **k):
        self.info_lines.append(msg)


class FakeRadiator:
    def __init__(self, setpoint="18.0", zone_mode="permanent override"):
        self.name   = "Fake TRV"
        self.states = {"setpointHeat": setpoint, "zoneMode": zone_mode}


class _FrozenDate:
    """Swaps plugin.datetime so 'today' is fixed for the summer-window tests."""

    def __init__(self, module, when):
        self.module   = module
        self.when     = when
        self.original = module.datetime

    def __enter__(self):
        when = self.when

        class _DT:
            @staticmethod
            def now():
                return when

        self.module.datetime = _DT
        return self

    def __exit__(self, *exc):
        self.module.datetime = self.original
        return False


def make_plugin(prefs=None, store=None):
    """A Plugin instance without running __init__.

    __init__ wants a live Indigo (data dir, state files, library check). The
    methods under test only touch pluginPrefs, store and logger, so build the
    object directly and give it just those.
    """
    p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
    p.pluginPrefs = dict(prefs or {})
    p.store       = dict(store or {})
    p.store.setdefault("summer_lockout_logged", None)
    p.store.setdefault("log_buffer", [])
    p.logger = RecordingLogger()
    return p


class EventLogTestCase(unittest.TestCase):
    """Base: swap the event-log sink for a recorder, restore afterwards."""

    def setUp(self):
        self.events = RecordingLog()
        self._targets = []
        seen = []
        for module in (plugin_mod, hl):
            server = module.indigo.server
            # Both modules normally bind the SAME stub. Patching it twice would
            # save the recorder as the "original" on the second pass and leave it
            # installed after tearDown, leaking recorded lines into later tests.
            if any(server is s for s in seen):
                continue
            seen.append(server)
            self._targets.append((server, server.log))
            server.log = self.events

    def tearDown(self):
        for server, original in self._targets:
            server.log = original


# ===========================================================================
class TestSummerLockoutAnnouncement(EventLogTestCase):
    """The shut-off is a STATE: announce it on change, never on a repeat."""
# ===========================================================================

    # Default prefs = shut-off enabled, 1 Jun to 30 Sep (matches PluginConfig).
    IN_SUMMER  = datetime(2026, 7, 15, 14, 30)
    IN_SEASON  = datetime(2026, 12, 15, 14, 30)

    def test_first_cycle_announces_once(self):
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SUMMER):
            p._announce_summer_lockout()
        self.assertEqual(len(self.events.containing("Whole-house heating OFF")), 1)

    def test_repeat_cycles_are_silent_in_the_event_log(self):
        """The bug this file exists for: ~21 identical lines a day."""
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SUMMER):
            for _ in range(200):          # ~17 hours of 5-minute cycles
                p._announce_summer_lockout()
        self.assertEqual(len(self.events.containing("Whole-house heating OFF")), 1)

    def test_every_cycle_still_reaches_the_plugins_own_log(self):
        """Quietening the event log must not lose the record."""
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SUMMER):
            for _ in range(12):
                p._announce_summer_lockout()
        self.assertEqual(len(p.logger.debug_lines), 12)
        self.assertIn("Whole-house heating OFF", p.logger.debug_lines[-1])

    def test_changed_resume_date_re_announces_once(self):
        """A pref edit changes the sentence, so the event log should hear it."""
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SUMMER):
            p._announce_summer_lockout()
            p.pluginPrefs["summerOnMonth"] = 10
            p.pluginPrefs["summerOnDay"]   = 15
            for _ in range(20):
                p._announce_summer_lockout()
        said = self.events.containing("Whole-house heating OFF")
        self.assertEqual(len(said), 2)
        self.assertIn("30 Sep", said[0])
        self.assertIn("15 Oct", said[1])

    def test_season_end_announces_once_then_stays_quiet(self):
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SUMMER):
            p._announce_summer_lockout()
        self.events.lines.clear()
        with _FrozenDate(plugin_mod, self.IN_SEASON):
            for _ in range(50):
                p._announce_summer_lockout_end()
        self.assertEqual(len(self.events.containing("shut-off ENDED")), 1)
        self.assertIsNone(p.store["summer_lockout_logged"])

    def test_no_end_line_when_nothing_was_announced(self):
        """Booting in December must not claim a shut-off just ended."""
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SEASON):
            p._announce_summer_lockout_end()
        self.assertEqual(self.events.containing("shut-off ENDED"), [])

    def test_force_on_does_not_fake_a_season_end(self):
        """A 24h force-on stops the lockout being enforced but does not end the
        season; it logs its own START/END lines, so the latch must stay armed."""
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SUMMER):
            p._announce_summer_lockout()
            self.events.lines.clear()

            p.store["summer_force_active"] = True
            self.assertFalse(p._summer_lockout_active())
            self.assertTrue(p._summer_window_active())
            p._announce_summer_lockout_end()
            self.assertEqual(self.events.containing("shut-off ENDED"), [])

            # Force-on expires: back under the shut-off, and still no repeat.
            p.store["summer_force_active"] = False
            for _ in range(20):
                p._announce_summer_lockout()
        self.assertEqual(self.events.containing("Whole-house heating OFF"), [])

    def test_disabling_the_feature_ends_the_announcement(self):
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SUMMER):
            p._announce_summer_lockout()
            self.events.lines.clear()
            p.pluginPrefs["summerLockoutEnabled"] = "false"
            p._announce_summer_lockout_end()
        self.assertEqual(len(self.events.containing("shut-off ENDED")), 1)

    def test_startup_seed_stops_a_restart_saying_it_twice(self):
        """startup() logs the status line and seeds the latch; the first cycle
        after it must not repeat the same news."""
        p = make_plugin()
        with _FrozenDate(plugin_mod, self.IN_SUMMER):
            p.store["summer_lockout_logged"] = p._summer_lockout_summary()
            for _ in range(20):
                p._announce_summer_lockout()
        self.assertEqual(self.events.containing("Whole-house heating OFF"), [])

    def test_summary_is_single_sourced(self):
        """The latch compares strings, so a second copy of the sentence would
        re-announce every cycle. Only _summer_lockout_summary may build it."""
        with open(os.path.join(_HERE, "plugin.py"), "r", encoding="utf-8") as f:
            source = f.read()
        self.assertEqual(source.count("Whole-house heating OFF for summer"), 1)


# ===========================================================================
class TestHourlyDumpGate(EventLogTestCase):
    """The hourly weather header + 12-room table: ~40 lines an hour."""
# ===========================================================================

    def test_quiet_by_default(self):
        self.assertFalse(make_plugin()._event_log_dump_enabled())

    def test_pref_coercion(self):
        """A saved dialog can hand the pref back as a string; bool("false") is True."""
        for raw, expected in ((True, True), ("true", True), (1, True),
                              (False, False), ("false", False), ("", False),
                              (None, False)):
            with self.subTest(raw=raw):
                p = make_plugin({"logHourlyDumpToEventLog": raw})
                self.assertIs(p._event_log_dump_enabled(), expected)

    def _header(self, plugin, **kwargs):
        """Drive _log_hourly_header far enough to exercise _b, with the section
        helpers stubbed out so no weather/records plumbing is needed."""
        plugin.store["log_buffer"] = []
        plugin._log_weather_section = lambda _b, *a, **k: _b("Weather line")
        plugin._log_records_section = lambda _b: _b("Records line")
        plugin._log_modes_section   = lambda _b: _b("Modes line")
        plugin._log_hourly_header(5.0, 0.0, menu_mode=True, **kwargs)

    def test_dump_off_writes_nothing_to_the_event_log(self):
        p = make_plugin()
        self._header(p)
        self.assertEqual(self.events.messages, [])

    def test_dump_off_still_fills_the_daily_log_buffer(self):
        """_flush_log_buffers writes this buffer to radiator_<date>.log, so the
        narration is kept in full - only the shared-log copy is dropped."""
        p = make_plugin()
        self._header(p)
        buffered = "\n".join(p.store["log_buffer"])
        for expected in ("Todays Weather", "Weather line", "Records line", "Modes line"):
            self.assertIn(expected, buffered)

    def test_dump_off_still_records_in_the_plugins_own_log(self):
        p = make_plugin()
        self._header(p)
        self.assertTrue(p.logger.debug_lines)

    def test_dump_on_echoes_to_the_event_log(self):
        p = make_plugin({"logHourlyDumpToEventLog": "true"})
        self._header(p)
        self.assertTrue(self.events.containing("Todays Weather"))
        self.assertTrue(self.events.containing("Weather line"))

    def test_menu_item_is_loud_whatever_the_pref_says(self):
        """'Show Full Weather Log' was clicked by a human asking to see it.

        Drives menuForceFullLog itself rather than passing to_event_log by hand:
        a mutation sweep showed that testing the parameter alone left the CALL
        SITE uncovered, so dropping to_event_log=True from the menu would have
        made the menu item silently print nothing and no test would have failed.
        """
        p = make_plugin({"logHourlyDumpToEventLog": False})
        p.weather      = None          # _get_snow_forecast returns [] without it
        p._cycle_lock  = threading.Lock()
        p._log_weather_section = lambda _b, *a, **k: _b("Weather line")
        p._log_records_section = lambda _b: _b("Records line")
        p._log_modes_section   = lambda _b: _b("Modes line")

        p.menuForceFullLog()

        self.assertTrue(self.events.containing("Todays Weather"))
        self.assertTrue(self.events.containing("Weather line"))

    def test_menu_item_does_not_pollute_the_daily_log(self):
        """The throwaway-buffer swap must survive the gate change."""
        p = make_plugin({"logHourlyDumpToEventLog": False})
        p.weather     = None
        p._cycle_lock = threading.Lock()
        p.store["log_buffer"] = ["a cycle line"]
        p._log_weather_section = lambda _b, *a, **k: _b("Weather line")
        p._log_records_section = lambda _b: None
        p._log_modes_section   = lambda _b: None

        p.menuForceFullLog()

        self.assertEqual(p.store["log_buffer"], ["a cycle line"])

    def test_buffer_is_identical_whether_the_echo_is_on_or_off(self):
        """The daily log file must not change - only the event-log copy."""
        quiet = make_plugin()
        loud  = make_plugin({"logHourlyDumpToEventLog": "true"})
        self._header(quiet)
        self._header(loud)
        strip = lambda lines: [ln.split("] ", 1)[-1] for ln in lines]   # noqa: E731
        self.assertEqual(strip(quiet.store["log_buffer"]),
                         strip(loud.store["log_buffer"]))


# ===========================================================================
class TestFaultsStillReachTheEventLog(EventLogTestCase):
    """Log_Error_Watch.py reads the event log and nothing else. Quietening
    routine narration must never quieten a fault."""
# ===========================================================================

    def test_header_warning_survives_the_quiet_gate(self):
        import logging
        p = make_plugin()          # dump OFF
        p.store["log_buffer"] = []
        p._log_weather_section = lambda _b, *a, **k: _b("Sensor unavailable",
                                                       level="WARNING")
        p._log_records_section = lambda _b: None
        p._log_modes_section   = lambda _b: None
        p._log_hourly_header(5.0, 0.0, menu_mode=True)

        warned = self.events.containing("Sensor unavailable")
        self.assertEqual(len(warned), 1)
        level = [lv for m, lv in self.events.lines if "Sensor unavailable" in m][0]
        self.assertEqual(level, logging.WARNING)
        # ...and the routine lines around it are still quiet.
        self.assertEqual(self.events.containing("Todays Weather"), [])

    def test_header_error_survives_the_quiet_gate(self):
        import logging
        p = make_plugin()
        p.store["log_buffer"] = []
        p._log_weather_section = lambda _b, *a, **k: _b("Weather fetch failed",
                                                       level="ERROR")
        p._log_records_section = lambda _b: None
        p._log_modes_section   = lambda _b: None
        p._log_hourly_header(5.0, 0.0, menu_mode=True)
        level = [lv for m, lv in self.events.lines if "Weather fetch failed" in m][0]
        self.assertEqual(level, logging.ERROR)

    def test_room_update_missing_device_survives_the_quiet_gate(self):
        """update_radiator_setpoint's guard branch must always be visible."""
        buf = []
        hl.update_radiator_setpoint(
            None, 18.0, 11, "Bathroom", {}, {}, buf, [],
            force_log=True, event_log_dump=False,
        )
        self.assertTrue(self.events.containing("device is None for Bathroom"))

    def test_room_update_exception_survives_the_quiet_gate(self):
        """The catch-all except branch is the one that reports a genuinely
        unexpected fault, so it must reach the event log with the dump off.
        A junk setpoint that is not one of the recognised 'unavailable' tokens
        makes float() raise inside the try."""
        hl.update_radiator_setpoint(
            FakeRadiator(setpoint="banana"), 18.0, 11, "Bathroom", {}, {}, [], [],
            force_log=True, event_log_dump=False,
        )
        self.assertTrue(self.events.containing("Error updating Bathroom"))

    def test_real_snow_forecast_line_survives_the_quiet_gate(self):
        """The header's ONE genuine above-INFO line, driven for real.

        The two tests above stub _log_weather_section and hand _b a synthetic
        WARNING, so they prove the gate and not the caller. This one runs the
        shipped _log_weather_section with a snow forecast in the store and the
        dump pref off - the state the plugin is actually in on a snowy morning.
        weather=None skips the OWM and sunrise blocks, leaving the outdoor
        temperature line (INFO, so quiet) beside the snow line (WARNING, loud).
        """
        import logging
        p = make_plugin()                       # dump OFF
        p.weather = None
        p.store["log_buffer"]   = []
        p.store["snow_forecast"] = [{"time_str": "06:00", "mm": 2.0},
                                    {"time_str": "07:00", "mm": 1.5}]
        p._log_records_section = lambda _b: None
        p._log_modes_section   = lambda _b: None

        p._log_hourly_header(5.0, 0.0, menu_mode=True)

        snow = [(m, lv) for m, lv in self.events.lines if "SNOW FORECAST" in m]
        self.assertEqual(len(snow), 1)
        self.assertEqual(snow[0][1], logging.WARNING)
        self.assertIn("3.5mm total", snow[0][0])
        # ...while the routine INFO lines beside it stayed out of the event log.
        self.assertEqual(self.events.containing("Temperature"), [])
        self.assertTrue([ln for ln in p.store["log_buffer"] if "Temperature" in ln])

    def test_the_snow_line_is_the_only_header_line_above_info(self):
        """Pins the factual claim made by the comment on _b's gate.

        The comment tells the next reader that the snow line is the only
        above-INFO line in this header, which is why the gate cannot be
        simplified away. Adding a second WARNING here is fine - but the comment
        must be corrected in the same edit, and this test is what forces that.
        """
        import ast
        import logging

        with open(os.path.join(_HERE, "plugin.py"), "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_b"]
        # A scan that matched nothing would pass every assertion below it.
        self.assertGreater(len(calls), 20)

        def _level_of(call):
            for kw in call.keywords:
                if kw.arg == "level" and isinstance(kw.value, ast.Constant):
                    return kw.value.value
            if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
                return call.args[1].value
            return "INFO"

        def _text_of(call):
            node = call.args[0] if call.args else None
            return "".join(c.value for c in ast.walk(node)
                           if isinstance(c, ast.Constant) and isinstance(c.value, str))

        loud = [c for c in calls
                if plugin_mod._to_level(_level_of(c)) >= logging.WARNING]
        self.assertEqual(len(loud), 1,
                         "the comment on _b names ONE above-INFO line; found "
                         f"{[ (c.lineno, _text_of(c)) for c in loud ]}")
        self.assertIn("SNOW FORECAST", _text_of(loud[0]))


# ===========================================================================
class TestRoomLineGate(EventLogTestCase):
    """The per-room table lines: 12 rooms x 24 hours = 288 lines a day."""
# ===========================================================================

    def _run(self, event_log_dump):
        buf = []
        hl.update_radiator_setpoint(
            FakeRadiator(), 18.0, 11, "Bathroom",
            last_setpoints={}, last_messages={},
            log_buffer=buf, changes_buffer=[],
            dev_temp=19.5, scheduled_temp=18.0,
            force_log=True, event_log_dump=event_log_dump,
        )
        return buf

    def test_hourly_room_line_is_quiet_by_default_but_still_filed(self):
        buf = self._run(event_log_dump=False)
        self.assertEqual(self.events.containing("Bathroom"), [])
        self.assertTrue([ln for ln in buf if "Bathroom" in ln])

    def test_hourly_room_line_echoes_when_asked(self):
        buf = self._run(event_log_dump=True)
        self.assertTrue(self.events.containing("Bathroom"))
        self.assertTrue([ln for ln in buf if "Bathroom" in ln])

    def test_daily_log_content_is_unchanged_by_the_gate(self):
        strip = lambda lines: [ln.split("] ", 1)[-1] for ln in lines]   # noqa: E731
        self.assertEqual(strip(self._run(False)), strip(self._run(True)))

    def test_default_keeps_the_old_behaviour_for_callers_that_omit_it(self):
        """event_log_dump defaults True, so an unaware caller is unaffected."""
        hl.update_radiator_setpoint(
            FakeRadiator(), 18.0, 11, "Bathroom", {}, {}, [], [],
            dev_temp=19.5, scheduled_temp=18.0, force_log=True,
        )
        self.assertTrue(self.events.containing("Bathroom"))

    def test_non_hourly_change_lines_were_already_file_only(self):
        """Guard against the gate accidentally making these louder."""
        self._run(event_log_dump=True)
        self.events.lines.clear()
        hl.update_radiator_setpoint(
            FakeRadiator(), 21.0, 11, "Bathroom", {"Bathroom": 18.0}, {}, [], [],
            dev_temp=19.5, scheduled_temp=18.0,
            force_log=False, event_log_dump=True,
        )
        self.assertEqual(self.events.containing("Bathroom"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
