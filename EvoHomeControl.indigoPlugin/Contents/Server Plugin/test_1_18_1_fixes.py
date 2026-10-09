#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_18_1_fixes.py
# Description: 1.18.1 - two findings from the 05-10-2026 external audit. HI-09: a zone's
#              reading age is worked out from RAMSES ESP 1.17.0's temperatureSeenEpoch, or
#              from the local text read through Europe/London, so the October clock change
#              cannot make a 55-minute-old reading look 5 minutes in the future. HI-03: the
#              En Suite open-window floor-heating shutdown runs on every 30-second tick,
#              whatever the radiator path decided (manual hold, missing or stale reading).
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5.5
# Date:        05-10-2026
# Version:     1.0

import os
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


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
    # Live values (IndigoConformance): Off 0, Heat 1. The floor runs on these from 1.21.0.
    ("kHvacMode",  types.SimpleNamespace(Off=0, Heat=1)),
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

_PLUGIN = plugin_mod.__name__
BST = timezone(timedelta(hours=1))
GMT = timezone.utc


def _dev(**states):
    return types.SimpleNamespace(states=states)


# ===========================================================================
class TestReadingAgeAcrossTheClockChange(unittest.TestCase):
    """HI-09. temperatureSeen is local wall-clock text, which repeats 01:00-01:59 on
    25-10-2026 and skips 01:00-01:59 on 28-03-2027."""
# ===========================================================================

    def test_the_epoch_state_wins_over_the_text(self):
        dev = _dev(temperatureSeenEpoch=int(time.time()) - 600,
                   temperatureSeen="2000-01-01 00:00:00")
        self.assertAlmostEqual(hl.zone_reading_age_minutes(dev), 10, delta=0.2)

    def test_an_epoch_reading_55_real_minutes_old_reads_55(self):
        seen = datetime(2026, 10, 25, 1, 30, tzinfo=BST)       # 00:30 UTC
        now  = datetime(2026, 10, 25, 1, 25, tzinfo=GMT)       # 01:25 UTC
        dev = _dev(temperatureSeenEpoch=int(seen.timestamp()),
                   temperatureSeen="2026-10-25 01:30:00")
        self.assertAlmostEqual(hl.zone_reading_age_minutes(dev, now=now), 55, delta=0.01)

    def test_a_blank_epoch_falls_back_to_the_text(self):
        dev = _dev(temperatureSeenEpoch=0,
                   temperatureSeen=(datetime.now() - timedelta(minutes=7)).strftime(
                       "%Y-%m-%d %H:%M:%S"))
        self.assertAlmostEqual(hl.zone_reading_age_minutes(dev), 7, delta=0.2)

    def test_the_text_fallback_is_not_minus_five_in_the_repeated_hour(self):
        """The audit's own example: 01:30 BST, read at 01:25 GMT, is 55 minutes old."""
        dev = _dev(temperatureSeen="2026-10-25 01:30:00")
        now = datetime(2026, 10, 25, 1, 25, tzinfo=GMT)
        self.assertAlmostEqual(hl.zone_reading_age_minutes(dev, now=now), 55, delta=0.01)

    def test_a_dead_zone_is_old_in_the_repeated_hour(self):
        """Last heard 00:50 BST; at 01:40 GMT that is 110 minutes, not 50."""
        dev = _dev(temperatureSeen="2026-10-25 00:50:00")
        now = datetime(2026, 10, 25, 1, 40, tzinfo=GMT)
        self.assertAlmostEqual(hl.zone_reading_age_minutes(dev, now=now), 110, delta=0.01)
        self.assertGreater(hl.zone_reading_age_minutes(dev, now=now), hl.ZONE_STALE_MINUTES)

    def test_an_ambiguous_time_takes_the_reading_that_is_not_in_the_future(self):
        dev = _dev(temperatureSeen="2026-10-25 01:08:00")
        now = datetime(2026, 10, 25, 1, 10, tzinfo=GMT)
        self.assertAlmostEqual(hl.zone_reading_age_minutes(dev, now=now), 2, delta=0.01)

    def test_the_spring_change_does_not_add_an_hour(self):
        """00:50 GMT to 02:10 BST on 28-03-2027 is 20 minutes, not 80."""
        dev = _dev(temperatureSeen="2027-03-28 00:50:00")
        now = datetime(2027, 3, 28, 2, 10, tzinfo=BST)
        self.assertAlmostEqual(hl.zone_reading_age_minutes(dev, now=now), 20, delta=0.01)

    def test_an_ordinary_day_is_unchanged(self):
        dev = _dev(temperatureSeen="2026-12-01 12:00:00")
        self.assertAlmostEqual(
            hl.zone_reading_age_minutes(dev, now=datetime(2026, 12, 1, 12, 30)), 30, delta=0.01)

    def test_last_seen_fallback_uses_the_same_conversion(self):
        dev = _dev(lastSeen="2026-10-25 01:30:00")
        now = datetime(2026, 10, 25, 1, 25, tzinfo=GMT)
        self.assertAlmostEqual(hl.zone_reading_age_minutes(dev, now=now), 55, delta=0.01)

    def test_blank_text_is_still_never_reported(self):
        self.assertEqual(hl.zone_reading_age_minutes(_dev(temperatureSeen="")), float("inf"))


# ===========================================================================
class TestEnSuiteWindowInterlock(unittest.TestCase):
    """HI-03. The radiator path returns early on a manual hold, a missing reading or a
    stale one, and the floor-heating shutdown sat after those returns."""
# ===========================================================================

    def setUp(self):
        self._saved_devices = dict(_indigo.devices)
        self._saved_device = _indigo.device
        self.turned_off, self.turned_on, self.events, self.saves = [], [], [], []
        _indigo.device = types.SimpleNamespace(
            turnOff=lambda d, **k: self.turned_off.append(d),
            turnOn=lambda d, **k: self.turned_on.append(d))
        self.floor = types.SimpleNamespace(id=hl.DEV_EN_SUITE_FLOOR_HEAT_ID, onState=True,
                                           states={"onOffState": True})
        self.window = types.SimpleNamespace(id=hl.DEV_EN_SUITE_WINDOW_ID,
                                            states={"contact": False})   # False = open
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_HEAT_ID] = self.floor
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = self.window
        # 1.21.0: the floor is turned off through its thermostat; the switch only powers it.
        self.therm = types.SimpleNamespace(id=hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID, states={
            "hvacOperationModeIsHeat": True, "hvacOperationModeIsOff": False,
            "setpointHeat": 14.0})
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID] = self.therm
        self.modes = []
        self._saved_thermo = _indigo.thermostat
        _indigo.thermostat = types.SimpleNamespace(
            setHvacMode=lambda d, value=None: self.modes.append(value),
            setHeatSetpoint=lambda d, value=None: self.modes.append(("setpoint", value)))
        hl._FLOOR["off_sent_at"] = 0.0

    def tearDown(self):
        _indigo.thermostat = self._saved_thermo
        _indigo.device = self._saved_device
        _indigo.devices.clear()
        _indigo.devices.update(self._saved_devices)

    def _plugin(self, morning=True):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs = {}
        p.store = {"en_suite_morning_active": morning,
                   "en_suite_morning_cancelled_date": None,
                   "en_suite_morning_cancelled_reason": None}
        p.weather = None
        p._summer_lockout_active = lambda: False
        p._away_mode_on = lambda: False
        p._save_state = lambda: self.saves.append(True)
        p._fire_event = lambda name, *a, **k: self.events.append(name)
        return p

    def test_an_open_window_switches_the_floor_off_and_ends_the_morning(self):
        p = self._plugin()
        p._check_en_suite_window_interlock()
        self.assertEqual(self.modes, [_indigo.kHvacMode.Off])
        self.assertEqual(self.turned_off, [], "the power switch is never turned off")
        self.assertFalse(p.store["en_suite_morning_active"])
        self.assertEqual(p.store["en_suite_morning_cancelled_reason"], "window_open")
        self.assertEqual(p.store["en_suite_morning_cancelled_date"],
                         datetime.now().strftime("%Y-%m-%d"))
        self.assertEqual(self.events, ["enSuiteMorningCancelled"])
        self.assertTrue(self.saves)

    def test_a_shut_window_changes_nothing(self):
        self.window.states["contact"] = True
        p = self._plugin()
        p._check_en_suite_window_interlock()
        self.assertEqual(self.modes, [])
        self.assertTrue(p.store["en_suite_morning_active"])
        self.assertEqual(self.events, [])

    def test_a_floor_already_off_is_not_switched_again(self):
        self.therm.states.update({"hvacOperationModeIsHeat": False, "hvacOperationModeIsOff": True})
        p = self._plugin(morning=False)
        p._check_en_suite_window_interlock()
        self.assertEqual(self.modes, [])
        self.assertEqual(self.events, [])

    def test_an_unpowered_thermostat_is_not_sent_anything(self):
        self.floor.states["onOffState"] = False
        p = self._plugin(morning=False)
        p._check_en_suite_window_interlock()
        self.assertEqual(self.modes, [])

    def test_an_unconfirmed_off_is_not_resent_every_tick(self):
        p = self._plugin(morning=False)
        for _ in range(5):
            p._check_en_suite_window_interlock()
        self.assertEqual(self.modes, [_indigo.kHvacMode.Off])
        hl._FLOOR["off_sent_at"] -= hl.FLOOR_OFF_RESEND_SECS
        p._check_en_suite_window_interlock()
        self.assertEqual(self.modes, [_indigo.kHvacMode.Off] * 2)

    def test_the_floor_goes_off_outside_the_morning_too(self):
        p = self._plugin(morning=False)
        p._check_en_suite_window_interlock()
        self.assertEqual(self.modes, [_indigo.kHvacMode.Off])
        self.assertEqual(self.events, [])

    def test_the_radiator_is_never_touched(self):
        """A manual radiator hold is respected: the interlock owns the floor only."""
        written = []
        saved = _indigo.thermostat
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda d, **k: written.append(d.id),
            setHvacMode=lambda d, **k: written.append(d.id))
        try:
            self._plugin()._check_en_suite_window_interlock()
        finally:
            _indigo.thermostat = saved
        self.assertNotIn(hl.DEV_EN_SUITE_ID, written)
        self.assertEqual(written, [hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID])

    def test_every_tick_runs_it(self):
        p = self._plugin()
        p.store.update({"last_heating_cycle": 10000.0, "cycle_requests": 0,
                        "cycle_requests_served": 0})
        for name in ("_check_summer_force_expiry", "_check_en_suite_morning",
                     "_check_en_suite_drying", "_check_timed_boost_expiry"):
            setattr(p, name, lambda: None)
        p._maybe_check_timetable = lambda now: None
        p._run_heating_cycle = lambda: None
        ran = []
        p._check_en_suite_window_interlock = lambda: ran.append(True)
        p._tick(10030.0)
        self.assertEqual(ran, [True])

    def test_a_morning_does_not_start_into_an_open_window(self):
        self.floor.states["onOffState"] = False
        p = self._plugin(morning=False)
        with mock.patch(_PLUGIN + ".datetime") as dt:
            dt.now.return_value = datetime(2026, 12, 1, 6, 0, 30)
            p._check_en_suite_morning()
        self.assertFalse(p.store["en_suite_morning_active"])
        self.assertEqual(self.turned_on, [])
        self.assertNotIn(_indigo.kHvacMode.Heat, self.modes)
        self.assertIsNone(p.store["en_suite_morning_cancelled_date"],
                          "not cancelled for the day: it starts once the window shuts")


if __name__ == "__main__":
    unittest.main()
