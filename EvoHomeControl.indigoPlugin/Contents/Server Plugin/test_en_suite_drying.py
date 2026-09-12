#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_en_suite_drying.py
# Description: Unit tests for the En Suite drying run — the special rule, the
#              exemptions that let it survive this plugin's own cut-offs, the
#              humidity and window readers, and the prose it logs.
#              Run from this directory with:  python3 test_en_suite_drying.py
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5
# Date:        12-09-2026
# Version:     1.0
#
# Why these tests exist. The drying run is one setpoint on one radiator, and
# THREE separate rules in this plugin would each have cancelled it: the summer
# shut-off, the 06:00 warm-morning skip and the OUTDOOR_TEMP_TRIGGER cut-off.
# Each exemption is a single tuple membership that a later edit could quietly
# drop, and the failure would be silent - a radiator that simply does not warm
# up, on a morning nobody is watching. The end-to-end case below drives the real
# process_room_temperature with a mild day outside and asserts the written
# setpoint, which is the one test that fails if any exemption is lost.

import ast
import os
import sys
import types
import unittest
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ---------------------------------------------------------------------------
# Stub `indigo` so heating_logic / plugin import outside the Indigo runtime.
# Augment an existing stub rather than replacing it: whichever test module the
# runner imports first installs one, and the modules under test bind to it at
# THEIR import, so swapping the object would leave them reading a stale stub.
# ---------------------------------------------------------------------------
class _ServerStub:
    @staticmethod
    def log(msg, level=None, isError=False, **kwargs):
        pass

    @staticmethod
    def getInstallFolderPath():
        return "/tmp/evohome-test"

    @staticmethod
    def getPlugin(plugin_id):
        return types.SimpleNamespace(isInstalled=lambda: True,
                                     isRunning=lambda: True,
                                     isEnabled=lambda: True)


class _PluginBaseStub:
    def __init__(self, *args, **kwargs):
        pass


_existing = sys.modules.get("indigo")
_indigo = _existing if _existing is not None else types.ModuleType("indigo")
if not hasattr(_indigo, "server") or not hasattr(_indigo.server, "getInstallFolderPath"):
    _indigo.server = _ServerStub()
if not hasattr(_indigo.server, "getPlugin"):
    _indigo.server.getPlugin = _ServerStub.getPlugin
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
import plugin as plugin_mod       # noqa: E402


class FakeDevice:
    """Only the surface heating_logic and the readers actually touch."""

    def __init__(self, name="fake", states=None, enabled=True,
                 plugin_id="com.clives.indigoplugin.z2mbridge", last_comm=None):
        self.name      = name
        self.states    = states or {}
        self.enabled   = enabled
        self.pluginId  = plugin_id
        self.lastSuccessfulComm = last_comm if last_comm is not None else datetime.now()


def _radiator(temp=19.6, setpoint=15.0):
    """Starts at 15 degC ON PURPOSE. update_radiator_setpoint is idempotent, so a
    fake sitting at RADIATORS_OFF_TEMP makes "wrote 8" and "wrote nothing"
    indistinguishable - two tests here passed vacuously until this was changed."""
    return FakeDevice("En Suite Radiator", {
        "temperatureInput1": temp,
        "setpointHeat":      setpoint,
        "zoneMode":          "permanent override",
    })


def _window(shut=True):
    return FakeDevice("En Suite Window Contact Sensor",
                      {"contact": shut, "availability": "online"})


def _bare_plugin(prefs=None, store=None):
    """A Plugin with no __init__ run — enough for the pure readers and helpers."""
    p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
    p.pluginPrefs = prefs if prefs is not None else {}
    p.store       = store if store is not None else {}
    return p


# ---------------------------------------------------------------------------
class TestDryingSpecialRule(unittest.TestCase):
    """en_suite_special_rules must report the drying target while a run is live."""

    def setUp(self):
        self._saved = dict(_indigo.devices) if isinstance(_indigo.devices, dict) else {}
        _indigo.devices.clear()
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=True)

    def tearDown(self):
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def test_active_run_returns_the_drying_temperature_and_message_25(self):
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 22.0}
        temp, msg = hl.en_suite_special_rules(18, 11, False, False, 0, 0, 5.0, 5, store=store)
        self.assertEqual((temp, msg), (22.0, 25))

    def test_it_uses_the_stored_target_not_the_module_default(self):
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 21.0}
        temp, _ = hl.en_suite_special_rules(18, 11, False, False, 0, 0, 5.0, 5, store=store)
        self.assertEqual(temp, 21.0)

    def test_an_open_window_falls_through_so_the_valve_closes(self):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=False)
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 22.0}
        temp, msg = hl.en_suite_special_rules(18, 11, True, False, 1, 0, 5.0, 5, store=store)
        self.assertEqual((temp, msg), (18, 11),
                         "an open window must return unchanged so windows_open closes the valve")

    def test_drying_beats_the_morning_schedule(self):
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 22.0,
                 "en_suite_morning_active": True}
        _, msg = hl.en_suite_special_rules(18, 11, False, False, 0, 0, 5.0, 7, store=store)
        self.assertEqual(msg, 25, "drying is the higher-priority rule")

    def test_drying_beats_the_warm_morning_skip(self):
        # The warm-morning skip forces the radiator OFF between 06:00 and 09:59.
        # A drying run must override it: a warm damp morning still has wet towels.
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 22.0,
                 "en_suite_morning_active": False,
                 "en_suite_morning_cancelled_reason": "warm_outdoor"}
        temp, msg = hl.en_suite_special_rules(19, 11, False, False, 0, 0, 15.0, 7, store=store)
        self.assertEqual((temp, msg), (22.0, 25))

    def test_warm_morning_skip_still_works_when_no_run_is_going(self):
        store = {"en_suite_drying_active": False,
                 "en_suite_morning_active": False,
                 "en_suite_morning_cancelled_reason": "warm_outdoor"}
        temp, msg = hl.en_suite_special_rules(19, 11, False, False, 0, 0, 15.0, 7, store=store)
        self.assertEqual((temp, msg), (hl.RADIATORS_OFF_TEMP, 24))


# ---------------------------------------------------------------------------
class TestDryingSurvivesTheCutOffs(unittest.TestCase):
    """The end-to-end case: what setpoint actually reaches the radiator."""

    def setUp(self):
        self._saved = dict(_indigo.devices)
        _indigo.devices.clear()
        self.radiator = _radiator()
        _indigo.devices[hl.DEV_EN_SUITE_ID]        = self.radiator
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=True)
        self.written = []
        self._saved_thermostat = _indigo.thermostat
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda dev, value=None: self.written.append(value))

    def tearDown(self):
        _indigo.thermostat = self._saved_thermostat
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _run(self, store, outdoor, hour=5, **kw):
        hl.process_room_temperature(
            room_name      = "En Suite",
            room_schedule  = [18] * 24,
            window_devices = [hl.DEV_EN_SUITE_WINDOW_ID],
            special_rules  = lambda *a, **k: hl.en_suite_special_rules(*a, store=store, **k),
            ha_device_id   = hl.DEV_EN_SUITE_ID,
            current_hour   = hour,
            current_minute = 0,
            current_outdoor_temp = outdoor,
            overheat_target_override = 22.0,
            last_setpoints = {}, last_messages = {},
            log_buffer = [], changes_buffer = [],
            overheat_monitor = None,
            **kw,
        )

    def test_a_mild_morning_does_not_close_the_valve_on_a_drying_run(self):
        # 20 degC outside is well past OUTDOOR_TEMP_TRIGGER (14), which normally
        # forces every radiator to the off temperature.
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 22.0}
        self._run(store, outdoor=20.0)
        self.assertEqual(self.written, [22.0],
                         "the mild-weather cut-off must not override the drying run")

    def test_without_a_run_a_mild_morning_still_closes_the_valve(self):
        store = {"en_suite_drying_active": False}
        self._run(store, outdoor=20.0)
        self.assertEqual(self.written, [hl.RADIATORS_OFF_TEMP],
                         "the cut-off must still work for every other case")

    def test_both_out_does_not_knock_four_degrees_off_the_drying_target(self):
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 22.0}
        self._run(store, outdoor=5.0, is_both_out=True)
        self.assertEqual(self.written, [22.0])

    def test_away_mode_still_beats_the_drying_run(self):
        # An empty house has no wet towels, so away is deliberately the winner.
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 22.0}
        self._run(store, outdoor=5.0, is_away=True)
        self.assertEqual(self.written, [hl.AWAY_TEMP])

    def test_an_open_window_still_closes_the_valve_during_a_run(self):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=False)
        store = {"en_suite_drying_active": True, "en_suite_drying_temp": 22.0}
        self._run(store, outdoor=5.0)
        self.assertEqual(self.written, [hl.RADIATORS_OFF_TEMP])


# ---------------------------------------------------------------------------
class TestHourWindow(unittest.TestCase):
    """A window that crosses midnight needs different arithmetic."""

    def setUp(self):
        self.f = plugin_mod.Plugin._hour_in_window

    def test_ordinary_window(self):
        for hour in (5, 6, 9):
            self.assertTrue(self.f(hour, 5, 10), hour)
        for hour in (4, 10, 11, 23, 0):
            self.assertFalse(self.f(hour, 5, 10), hour)

    def test_start_is_inclusive_and_end_is_exclusive(self):
        self.assertTrue(self.f(5, 5, 10))
        self.assertFalse(self.f(10, 5, 10))

    def test_a_window_crossing_midnight_is_open_not_closed(self):
        # `start <= hour < end` is False for EVERY hour when start > end, so the
        # obvious form silently closes a 22->6 window instead of widening it.
        for hour in (22, 23, 0, 3, 5):
            self.assertTrue(self.f(hour, 22, 6), hour)
        for hour in (6, 12, 21):
            self.assertFalse(self.f(hour, 22, 6), hour)

    def test_a_zero_length_window_never_opens(self):
        for hour in range(24):
            self.assertFalse(self.f(hour, 7, 7), hour)


# ---------------------------------------------------------------------------
class TestHumidityReader(unittest.TestCase):
    """A reading is used only in prose, so anything doubtful must read as unknown."""

    DEV_ID = 286568782

    def setUp(self):
        self._saved = dict(_indigo.devices)
        _indigo.devices.clear()
        self.plugin = _bare_plugin(prefs={"enSuiteHumidityDeviceId": str(self.DEV_ID)})

    def tearDown(self):
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _install(self, **kw):
        states = {"humidity": kw.pop("humidity", 70.9),
                  "availability": kw.pop("availability", "online")}
        _indigo.devices[self.DEV_ID] = FakeDevice("En Suite T+H", states, **kw)

    def test_a_good_reading_comes_back(self):
        self._install(humidity=70.9)
        self.assertAlmostEqual(self.plugin._en_suite_humidity(), 70.9)

    def test_zero_is_not_a_reading(self):
        # Measured 12-09-2026: this device logged 0.0% four seconds before its
        # first real report. A transmitting sensor cannot be in 0% air.
        self._install(humidity=0.0)
        self.assertIsNone(self.plugin._en_suite_humidity())

    def test_an_offline_sensor_reads_unknown_not_dry(self):
        self._install(humidity=70.9, availability="offline")
        self.assertIsNone(self.plugin._en_suite_humidity())

    def test_a_stale_reading_reads_unknown(self):
        stale = datetime.now() - timedelta(minutes=plugin_mod.EN_SUITE_HUMIDITY_MAX_AGE_MINS + 5)
        self._install(humidity=70.9, last_comm=stale)
        self.assertIsNone(self.plugin._en_suite_humidity())

    def test_a_fresh_reading_just_inside_the_age_bound_is_kept(self):
        fresh = datetime.now() - timedelta(minutes=plugin_mod.EN_SUITE_HUMIDITY_MAX_AGE_MINS - 5)
        self._install(humidity=70.9, last_comm=fresh)
        self.assertAlmostEqual(self.plugin._en_suite_humidity(), 70.9)

    def test_a_disabled_device_reads_unknown(self):
        self._install(humidity=70.9, enabled=False)
        self.assertIsNone(self.plugin._en_suite_humidity())

    def test_a_missing_device_reads_unknown(self):
        self.assertIsNone(self.plugin._en_suite_humidity())

    def test_no_configured_sensor_reads_unknown(self):
        self.plugin.pluginPrefs = {"enSuiteHumidityDeviceId": ""}
        self.assertIsNone(self.plugin._en_suite_humidity())

    def test_a_junk_device_id_reads_unknown_rather_than_raising(self):
        self.plugin.pluginPrefs = {"enSuiteHumidityDeviceId": "not a number"}
        self.assertIsNone(self.plugin._en_suite_humidity())


# ---------------------------------------------------------------------------
class TestWindowReader(unittest.TestCase):
    """Only a positive SHUT lets the run go. A doubtful read stops it, loudly."""

    def setUp(self):
        self._saved = dict(_indigo.devices)
        _indigo.devices.clear()
        self.plugin = _bare_plugin()

    def tearDown(self):
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def test_a_shut_window_reads_shut(self):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=True)
        self.assertTrue(self.plugin._en_suite_window_is_shut())

    def test_an_open_window_reads_open(self):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=False)
        self.assertFalse(self.plugin._en_suite_window_is_shut())

    def test_a_missing_sensor_stops_the_run(self):
        self.assertFalse(self.plugin._en_suite_window_is_shut())

    def test_a_sensor_that_never_reported_stops_the_run(self):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = FakeDevice("w", {"availability": "online"})
        self.assertFalse(self.plugin._en_suite_window_is_shut())

    def test_an_offline_sensor_stops_the_run(self):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = FakeDevice(
            "w", {"contact": True, "availability": "offline"})
        self.assertFalse(self.plugin._en_suite_window_is_shut())

    def test_a_disabled_sensor_stops_the_run(self):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=True)
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID].enabled = False
        self.assertFalse(self.plugin._en_suite_window_is_shut())

    def test_the_warning_is_latched_so_it_cannot_repeat_every_thirty_seconds(self):
        # Count the LOG CALLS, not the stored value: an unlatched version rewrites
        # the store with the same string, so comparing it passes either way and a
        # mutation removing the latch survived the suite.
        lines = []
        saved = plugin_mod._log
        plugin_mod._log = lambda msg, level="INFO": lines.append(msg)
        try:
            for _ in range(5):
                self.plugin._en_suite_window_is_shut()   # missing sensor -> warns
        finally:
            plugin_mod._log = saved
        self.assertEqual(len(lines), 1,
                         f"five checks must warn once, got {len(lines)}: {lines}")
        self.assertIsNotNone(self.plugin.store.get("en_suite_window_warned"))

    def test_a_changed_problem_warns_again(self):
        lines = []
        saved = plugin_mod._log
        plugin_mod._log = lambda msg, level="INFO": lines.append(msg)
        try:
            self.plugin._en_suite_window_is_shut()       # missing
            _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=True)
            _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID].enabled = False
            self.plugin._en_suite_window_is_shut()       # disabled — a new problem
        finally:
            plugin_mod._log = saved
        self.assertEqual(len(lines), 2)

    def test_a_good_read_clears_the_latch(self):
        self.plugin._en_suite_window_is_shut()
        self.assertIsNotNone(self.plugin.store.get("en_suite_window_warned"))
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=True)
        self.plugin._en_suite_window_is_shut()
        self.assertIsNone(self.plugin.store.get("en_suite_window_warned"))


# ---------------------------------------------------------------------------
class TestDryingProse(unittest.TestCase):
    """The log sentence has to read like English, plurals included."""

    def setUp(self):
        self.say = plugin_mod.Plugin._drying_humidity_sentence

    def test_a_fall_is_reported_as_drying_out(self):
        s = self.say(80.0, 66.0)
        self.assertIn("fell from 80% to 66%", s)
        self.assertIn("14 points", s)

    def test_a_rise_is_reported_as_getting_damper(self):
        s = self.say(66.0, 72.0)
        self.assertIn("rose from 66% to 72%", s)
        self.assertIn("damper by 6 points", s)

    def test_one_point_is_singular(self):
        self.assertIn("1 point.", self.say(71.0, 70.0))
        self.assertNotIn("1 points", self.say(71.0, 70.0))

    def test_a_rounding_sized_change_says_no_difference(self):
        self.assertIn("no measurable difference", self.say(70.2, 70.0))

    def test_both_readings_missing(self):
        self.assertIn("nothing to compare", self.say(None, None))

    def test_only_the_start_missing(self):
        self.assertIn("no reading when the run began", self.say(None, 68.0))

    def test_only_the_end_missing(self):
        self.assertIn("no reading now", self.say(70.0, None))

    def test_every_sentence_is_plain_ascii_and_ends_in_a_full_stop(self):
        for before, after in ((80.0, 66.0), (66.0, 72.0), (71.0, 70.0),
                              (70.2, 70.0), (None, None), (None, 68.0), (70.0, None)):
            s = self.say(before, after)
            self.assertTrue(s.endswith("."), s)
            s.encode("ascii")           # raises if any Unicode crept in
            self.assertNotIn("|", s)
            self.assertNotIn("=", s)


# ---------------------------------------------------------------------------
class TestDryingSettings(unittest.TestCase):
    """Blank and junk prefs must fall back, never raise."""

    def test_defaults_when_nothing_is_saved(self):
        p = _bare_plugin()
        self.assertEqual(p._en_suite_drying_window(),
                         (hl.EN_SUITE_DRYING_START_HOUR, hl.EN_SUITE_DRYING_END_HOUR))
        self.assertEqual(p._en_suite_drying_temp(), hl.EN_SUITE_DRYING_TEMP)
        self.assertTrue(p._en_suite_drying_enabled())

    def test_saved_values_are_honoured(self):
        p = _bare_plugin(prefs={"enSuiteDryingStartHour": "6",
                                "enSuiteDryingEndHour": "9",
                                "enSuiteDryingTemp": "21.0"})
        self.assertEqual(p._en_suite_drying_window(), (6, 9))
        self.assertEqual(p._en_suite_drying_temp(), 21.0)

    def test_junk_hours_fall_back_to_the_defaults(self):
        p = _bare_plugin(prefs={"enSuiteDryingStartHour": "",
                                "enSuiteDryingEndHour": "banana"})
        self.assertEqual(p._en_suite_drying_window(),
                         (hl.EN_SUITE_DRYING_START_HOUR, hl.EN_SUITE_DRYING_END_HOUR))

    def test_an_out_of_range_hour_falls_back(self):
        p = _bare_plugin(prefs={"enSuiteDryingStartHour": "99"})
        self.assertEqual(p._en_suite_drying_window()[0], hl.EN_SUITE_DRYING_START_HOUR)

    def test_the_target_is_clamped_to_something_sane(self):
        self.assertEqual(_bare_plugin(prefs={"enSuiteDryingTemp": "99"})._en_suite_drying_temp(), 26.0)
        self.assertEqual(_bare_plugin(prefs={"enSuiteDryingTemp": "-5"})._en_suite_drying_temp(),
                         hl.RADIATORS_OFF_TEMP)

    def test_the_string_false_switches_it_off(self):
        # bool("false") is True, which is exactly the wrong answer.
        self.assertFalse(_bare_plugin(prefs={"enSuiteDryingEnabled": "false"})._en_suite_drying_enabled())


# ---------------------------------------------------------------------------
class TestSummerShutOffExemption(unittest.TestCase):
    """The shut-off is the ONLY path that runs before 30 September.

    _apply_summer_off pushes the off temperature back over any radiator that
    differs, every five minutes. Without the exemption below the drying run would
    be undone before anyone was awake to see it, and no other test in this file
    touches that code path - a mutation removing it survived the whole suite.
    """

    def setUp(self):
        self._saved = dict(_indigo.devices)
        _indigo.devices.clear()
        # Distinct names per zone. They all shared one name at first, so keying the
        # captured writes by name collapsed twelve radiators into one entry and the
        # test could not tell which zone had been written what.
        for dev_id in hl.ALL_RADIATOR_IDS:
            rad = _radiator(setpoint=15.0)
            rad.name = ("En Suite Radiator" if dev_id == hl.DEV_EN_SUITE_ID
                        else f"Radiator {dev_id}")
            _indigo.devices[dev_id] = rad
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_HEAT_ID] = FakeDevice(
            "En Suite Floor Heating Switch", {"onOffState": False})
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_HEAT_ID].onState = False
        self.written = []
        self._saved_thermostat = _indigo.thermostat
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda dev, value=None: self.written.append((dev.name, value)))
        self._saved_device = _indigo.device
        self.turned_off = []
        _indigo.device = types.SimpleNamespace(
            turnOn=lambda *a, **k: self.turned_off.append(("on", a)),
            turnOff=lambda *a, **k: self.turned_off.append(("off", a)))

    def tearDown(self):
        _indigo.thermostat = self._saved_thermostat
        _indigo.device     = self._saved_device
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _apply(self, store):
        p = _bare_plugin(prefs={}, store=store)
        p._apply_summer_off()
        return dict(self.written)

    def test_the_en_suite_is_held_at_the_drying_target_while_a_run_is_going(self):
        written = self._apply({"en_suite_drying_active": True})
        self.assertEqual(written["En Suite Radiator"], 22.0,
                         "the shut-off must not push 8 degC back over a drying run")

    def test_every_other_radiator_still_goes_to_the_off_temperature(self):
        self._apply({"en_suite_drying_active": True})
        others = [v for name, v in self.written]
        self.assertEqual(others.count(hl.RADIATORS_OFF_TEMP), len(hl.ALL_RADIATOR_IDS) - 1)
        self.assertEqual(others.count(22.0), 1)

    def test_with_no_run_going_the_en_suite_goes_off_like_the_rest(self):
        self._apply({"en_suite_drying_active": False})
        values = {v for _, v in self.written}
        self.assertEqual(values, {hl.RADIATORS_OFF_TEMP})

    def test_the_shut_off_never_switches_the_floor_heating_on(self):
        self._apply({"en_suite_drying_active": True})
        self.assertEqual([d for d, _ in self.turned_off], [],
                         "the floor switch is already off and must be left alone")


# ---------------------------------------------------------------------------
class TestOverheatBaseline(unittest.TestCase):
    """An elevated run must raise the baseline it is judged against."""

    def test_no_run_uses_the_schedule(self):
        self.assertIsNone(_bare_plugin(store={})._en_suite_overheat_target())

    def test_a_drying_run_raises_the_baseline_to_its_own_target(self):
        p = _bare_plugin(prefs={"enSuiteDryingTemp": "22.0"},
                         store={"en_suite_drying_active": True})
        self.assertEqual(p._en_suite_overheat_target(), 22.0)

    def test_the_morning_schedule_raises_it_to_the_morning_temperature(self):
        p = _bare_plugin(store={"en_suite_morning_active": True})
        self.assertEqual(p._en_suite_overheat_target(), hl.EN_SUITE_MORNING_TEMP)

    def test_drying_wins_when_both_are_somehow_set(self):
        p = _bare_plugin(prefs={"enSuiteDryingTemp": "21.0"},
                         store={"en_suite_drying_active": True,
                                "en_suite_morning_active": True})
        self.assertEqual(p._en_suite_overheat_target(), 21.0,
                         "the baseline must agree with the higher-priority rule")


# ---------------------------------------------------------------------------
class TestStructure(unittest.TestCase):
    """Read from the parsed tree, not from the source text."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_HERE, "plugin.py"), encoding="utf-8") as f:
            cls.tree = ast.parse(f.read())
        cls.funcs = {n.name: n for n in ast.walk(cls.tree)
                     if isinstance(n, ast.FunctionDef)}

    def test_the_tick_calls_the_drying_check(self):
        tick = self.funcs["_tick"]
        called = {n.func.attr for n in ast.walk(tick)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("_check_en_suite_drying", called,
                      "_tick must run the drying check every poll, or an opened "
                      "window is not noticed for up to five minutes")

    def test_the_drying_code_never_touches_the_floor_heating(self):
        # CliveS's instruction, 12-09-2026: the floor thermostat is his to switch
        # by hand. This is the guard that keeps it that way.
        floor = {"DEV_EN_SUITE_FLOOR_HEAT_ID", "DEV_EN_SUITE_FLOOR_THERMOSTAT_ID"}
        names = [n for n in self.funcs
                 if "drying" in n or n in ("_en_suite_window_is_shut", "_en_suite_humidity")]
        self.assertGreaterEqual(len(names), 8,
                                f"expected the drying methods, found {sorted(names)}")
        offenders = []
        for name in names:
            used = {n.id for n in ast.walk(self.funcs[name]) if isinstance(n, ast.Name)}
            if used & floor:
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_the_en_suite_dispatch_asks_for_the_raised_overheat_baseline(self):
        """Testing the decision is not testing that anything calls it.

        _en_suite_overheat_target has its own tests, and a mutation pinning the
        dispatch's argument to None still passed all of them - the room dispatch is
        a 150-line method no unit test enters, so only the parsed tree can say
        whether the value is actually asked for.
        """
        calls = []
        for node in ast.walk(self.funcs["_process_all_rooms"]):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_safe_process_room"):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            room = kw.get("room_name")
            if isinstance(room, ast.Constant) and room.value == "En Suite":
                calls.append(kw)
        self.assertEqual(len(calls), 1,
                         f"expected exactly one En Suite dispatch, found {len(calls)}")
        override = calls[0].get("overheat_target_override")
        self.assertIsInstance(override, ast.Call,
                              "the En Suite must be given a computed overheat baseline")
        self.assertEqual(override.func.attr, "_en_suite_overheat_target")

    def test_message_25_is_wired_all_the_way_through(self):
        self.assertIn(25, hl.ALERT_LOG_MESSAGES)
        self.assertIn("drying", hl.get_log_message(25, "En Suite", 8.0, 22.0, 19.6, 18.0).lower())
        self.assertIn("drying", hl.get_reason_line(25, 22.0).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
