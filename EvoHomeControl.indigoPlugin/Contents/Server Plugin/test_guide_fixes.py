#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_guide_fixes.py
# Description: Regression tests for the plugin-level faults found while writing
#              the plain-English guide (1.10.0): the location placeholder in
#              IndigoSecrets, empty outdoor record variables, the Toggle
#              Timestamps menu item, and the En Suite Morning Cancelled event.
#              Run from this directory with:  python3 test_guide_fixes.py
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0

import os
import sys
import types
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ---------------------------------------------------------------------------
# Stub `indigo`. Augment an existing stub rather than replacing it: whichever
# test module the runner imports first installs one, and the modules under test
# bind to it at THEIR import.
# ---------------------------------------------------------------------------
class _ServerStub:
    @staticmethod
    def log(msg, level=None, isError=False, **kwargs):
        pass

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

import heating_logic as hl        # noqa: E402
import log_stamp                  # noqa: E402
import plugin as plugin_mod       # noqa: E402

_PLUGIN = plugin_mod.__name__


def _bare_plugin(prefs=None, store=None):
    p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
    p.pluginPrefs = prefs if prefs is not None else {}
    p.store       = store if store is not None else {}
    p.weather     = None
    p.overheat    = None
    return p


class _Recorder:
    def __init__(self):
        self.lines = []

    def __call__(self, msg, level=None, isError=False, **kwargs):
        self.lines.append(msg)


# ===========================================================================
class TestLocationPlaceholder(unittest.TestCase):
    """IndigoSecrets_example.py ships LATITUDE = 0.0 and LONGITUDE = 0.0. Those used
    to win over the Configure boxes because 0.0 is a value, so a copied template
    sent every weather request to open sea off Africa."""
# ===========================================================================

    PREFS = {"owmLatitude": "54.5", "owmLongitude": "-1.5"}

    def _resolve(self, lat, lon, prefs=None, **kw):
        with mock.patch(_PLUGIN + "._SECRETS_LATITUDE", lat), \
             mock.patch(_PLUGIN + "._SECRETS_LONGITUDE", lon):
            return plugin_mod._resolve_location(self.PREFS if prefs is None else prefs, **kw)

    def test_the_template_zeros_count_as_not_set(self):
        self.assertEqual(self._resolve(0.0, 0.0), (54.5, -1.5))

    def test_real_secrets_still_win(self):
        self.assertEqual(self._resolve(51.5, -0.1), (51.5, -0.1))

    def test_no_secrets_uses_the_dialog(self):
        self.assertEqual(self._resolve(None, None), (54.5, -1.5))

    def test_one_coordinate_on_the_equator_is_still_a_real_place(self):
        self.assertEqual(self._resolve(0.0, 32.5), (0.0, 32.5))

    def test_blank_dialog_falls_back_to_the_given_default(self):
        self.assertEqual(self._resolve(0.0, 0.0, prefs={}, fallback_lat=1.0, fallback_lon=2.0),
                         (1.0, 2.0))

    def test_startup_and_the_dialog_save_both_use_it(self):
        import inspect
        for method in (plugin_mod.Plugin.startup, plugin_mod.Plugin.closedPrefsConfigUi):
            src = inspect.getsource(method)
            self.assertIn("_resolve_location(", src, method.__name__)
            self.assertNotIn("_SECRETS_LATITUDE", src, method.__name__)


# ===========================================================================
class TestEmptyRecordVariables(unittest.TestCase):
    """An empty Highest or Lowest variable made float("") raise, and the method
    returned without writing - so an empty record never filled in."""
# ===========================================================================

    def _run(self, hi, lo, reading):
        values = {plugin_mod.VAR_AV_OUT_TEMP_HI_ID: hi, plugin_mod.VAR_AV_OUT_TEMP_LO_ID: lo}
        written = {}
        with mock.patch(_PLUGIN + ".get_variable_value",
                        lambda var_id, default=None: values.get(var_id, default)), \
             mock.patch(_PLUGIN + ".update_variable",
                        lambda var_id, value: written.__setitem__(var_id, value)):
            _bare_plugin()._update_temp_records(reading)
        return written

    def test_both_empty_are_filled_by_the_first_reading(self):
        w = self._run("", "", 11.3)
        self.assertEqual(w[plugin_mod.VAR_AV_OUT_TEMP_HI_ID], 11.3)
        self.assertEqual(w[plugin_mod.VAR_AV_OUT_TEMP_LO_ID], 11.3)

    def test_an_empty_high_does_not_block_the_low(self):
        w = self._run("", "12.0", 4.0)
        self.assertEqual(w[plugin_mod.VAR_AV_OUT_TEMP_LO_ID], 4.0)
        self.assertEqual(w[plugin_mod.VAR_AV_OUT_TEMP_HI_ID], 4.0)

    def test_junk_counts_as_empty(self):
        w = self._run("n/a", "unknown", 9.0)
        self.assertIn(plugin_mod.VAR_AV_OUT_TEMP_HI_ID, w)
        self.assertIn(plugin_mod.VAR_AV_OUT_TEMP_LO_ID, w)

    def test_real_records_are_only_beaten_not_replaced(self):
        w = self._run("30.1", "-8.4", 12.0)
        self.assertEqual(w, {})


# ===========================================================================
class TestToggleTimestamps(unittest.TestCase):
    """The menu item only moved the few lines that go through self.logger; most
    lines stamped themselves whatever it said. One switch now covers them all."""
# ===========================================================================

    def setUp(self):
        self.rec = _Recorder()
        self._saved_log = _indigo.server.log
        _indigo.server.log = self.rec
        self._saved_enabled = log_stamp.is_enabled()

    def tearDown(self):
        _indigo.server.log = self._saved_log
        log_stamp.set_enabled(self._saved_enabled)

    @staticmethod
    def _stamped(line):
        return line.startswith("[") and line[3] == ":" and line[13] == "]"

    def _emit_everywhere(self):
        import overheat_monitor
        import weather
        buf = []
        plugin_mod._log("from plugin")
        hl._log("from heating_logic", log_buffer=buf)
        weather._slog("from weather")
        overheat_monitor._slog("from overheat_monitor")
        return buf

    def test_off_means_no_stamp_on_any_route(self):
        log_stamp.set_enabled(False)
        self._emit_everywhere()
        self.assertEqual(len(self.rec.lines), 4)
        for line in self.rec.lines:
            self.assertFalse(self._stamped(line), line)

    def test_on_means_a_stamp_on_every_route(self):
        log_stamp.set_enabled(True)
        self._emit_everywhere()
        for line in self.rec.lines:
            self.assertTrue(self._stamped(line), line)

    def test_the_daily_file_keeps_its_time_either_way(self):
        log_stamp.set_enabled(False)
        buf = self._emit_everywhere()
        self.assertTrue(self._stamped(buf[0]), buf[0])

    def test_the_menu_item_flips_the_shared_switch(self):
        log_stamp.set_enabled(True)
        p = _bare_plugin()
        p.timestamp_enabled  = True
        p._ts_filter         = None
        p.pluginDisplayName  = "EvoHome"
        p.menuToggleTimestamps()
        self.assertFalse(log_stamp.is_enabled())
        self.assertEqual(p.pluginPrefs["timestampEnabled"], False)
        p.menuToggleTimestamps()
        self.assertTrue(log_stamp.is_enabled())

    def test_the_menu_item_saves_the_choice_at_once(self):
        p = _bare_plugin()
        p.timestamp_enabled  = True
        p._ts_filter         = None
        p.pluginDisplayName  = "EvoHome"
        saved = []
        p.savePluginPrefs = lambda: saved.append(True)
        p.menuToggleTimestamps()
        self.assertEqual(saved, [True])


# ===========================================================================
class TestMorningCancelledByTheWindowFiresTheEvent(unittest.TestCase):
    """Opening the window ends the En Suite morning schedule inside the room's own
    rule, which cannot reach Indigo's triggers, so En Suite Morning Cancelled never
    fired for it although the event promised it. Drives the real _process_all_rooms
    and the real en_suite_special_rules."""
# ===========================================================================

    def setUp(self):
        self._saved = dict(_indigo.devices)
        _indigo.devices.clear()

    def tearDown(self):
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _plugin(self, morning_active, window_open):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = types.SimpleNamespace(
            name="En Suite Window", states={"contact": not window_open})
        store = {
            "is_guest_2": False, "is_guest_3": False, "is_away": False,
            "is_boost": False, "is_both_out": False, "timed_boost_active": False,
            "last_setpoints": {}, "last_messages": {},
            "log_buffer": [], "changes_buffer": [],
            "en_suite_morning_active": morning_active,
            "en_suite_morning_cancelled_reason": None,
        }
        p = _bare_plugin(store=store)
        self.fired, self.saved = [], []
        p._fire_event = lambda event_id: self.fired.append(event_id)
        p._save_state = lambda: self.saved.append(True)

        def _room(**kw):
            if kw["room_name"] == "En Suite":
                kw["special_rules"](18, 11, window_open, False, int(window_open), 0, 5.0, 7)
        p._safe_process_room = _room
        return p

    class _AnySchedule:
        """Every room plan is a flat 18; the stubbed schedules module has none."""
        TIMED_BOOST_ROOMS = set()

        def __getattr__(self, name):
            return [18] * 24

    def _cycle(self, p):
        with mock.patch(_PLUGIN + "._log"), \
             mock.patch(_PLUGIN + ".schedules", self._AnySchedule()):
            p._process_all_rooms(7, 0, 0.0, 5.0, 5)

    def test_opening_the_window_fires_morning_cancelled(self):
        p = self._plugin(morning_active=True, window_open=True)
        self._cycle(p)
        self.assertFalse(p.store["en_suite_morning_active"])
        self.assertEqual(self.fired, ["enSuiteMorningCancelled"])
        self.assertTrue(self.saved, "the cancellation must survive a restart")

    def test_a_shut_window_fires_nothing(self):
        p = self._plugin(morning_active=True, window_open=False)
        self._cycle(p)
        self.assertEqual(self.fired, [])

    def test_no_morning_schedule_running_fires_nothing(self):
        p = self._plugin(morning_active=False, window_open=True)
        self._cycle(p)
        self.assertEqual(self.fired, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
