#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_fixes_1_12.py
# Description: Regression tests for 1.12.0 - the fixes made before the heating
#              came back on 30-09-2026: last spring's overheat state, frozen
#              outdoor and zone readings, and the En Suite floor heating left on.
#              Run from this directory with:  python3 test_fixes_1_12.py
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5.5
# Date:        28-09-2026
# Version:     1.0

import json
import os
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta
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

import heating_logic as hl            # noqa: E402
import overheat_monitor as om         # noqa: E402
import weather as wx                  # noqa: E402
import plugin as plugin_mod           # noqa: E402

_PLUGIN = plugin_mod.__name__
_FMT    = "%Y-%m-%d %H:%M:%S"


class FakeDevice:
    def __init__(self, states=None, last_changed=None):
        self.states      = dict(states or {})
        self.lastChanged = last_changed if last_changed is not None else datetime.now()
        self.enabled     = True


def _ago(minutes):
    return (datetime.now() - timedelta(minutes=minutes)).strftime(_FMT)


class _SwitchRecorder:
    """Stands in for indigo.device and records what was switched."""

    def __init__(self):
        self.calls = []

    def turnOn(self, dev, *a, **k):
        self.calls.append(("on", getattr(dev, "id", dev)))

    def turnOff(self, dev, *a, **k):
        self.calls.append(("off", getattr(dev, "id", dev)))


# ===========================================================================
class TestOverheatStateAcrossTheSummer(unittest.TestCase):
    """On 28-09-2026 overheat_history.json was the 7 June copy: three rooms still
    CRITICAL, counters in the thousands. A restart after the shut-off reloaded it."""
# ===========================================================================

    def setUp(self):
        self.dir  = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "overheat_history.json")

    def _write(self, history, age_secs=0):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(history, f)
        t = time.time() - age_secs
        os.utime(self.path, (t, t))

    SPRING = {"Bedroom 1": {"consecutive_cycles": 11023, "alert_sent": True,
                            "alert_type": "CRITICAL_IMMEDIATE", "temp_history": [24.2]}}

    def test_a_file_left_from_the_spring_is_not_loaded(self):
        self._write(self.SPRING, age_secs=113 * 86400)
        self.assertEqual(om.OverheatMonitor(self.path).history, {})

    def test_an_old_empty_file_is_dropped_without_a_word(self):
        self._write({}, age_secs=40 * 86400)
        with mock.patch.object(om, "_slog") as slog:
            self.assertEqual(om.OverheatMonitor(self.path).history, {})
        slog.assert_not_called()

    def test_an_old_file_with_rooms_in_it_is_mentioned(self):
        self._write(self.SPRING, age_secs=40 * 86400)
        with mock.patch.object(om, "_slog") as slog:
            om.OverheatMonitor(self.path)
        slog.assert_called_once()

    def test_a_file_saved_by_the_last_cycle_is_loaded(self):
        self._write(self.SPRING, age_secs=600)
        self.assertIn("Bedroom 1", om.OverheatMonitor(self.path).history)

    def test_the_reset_drops_the_temperature_history_as_well(self):
        self._write(self.SPRING, age_secs=60)
        m = om.OverheatMonitor(self.path)
        m.reset_all_tracking()
        m.initialize_room("Bedroom 1")
        self.assertEqual(m.history["Bedroom 1"]["temp_history"], [])

    def test_the_reset_is_saved_to_disk(self):
        self._write(self.SPRING, age_secs=60)
        m = om.OverheatMonitor(self.path)
        m.reset_all_tracking()
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {})


# ===========================================================================
class TestOutdoorReadingAge(unittest.TestCase):
    """The Ecowitt plugin never sets deviceOnline to False, so a stopped station
    kept its last temperature for ever - above 14 degC that holds every radiator
    at 8."""
# ===========================================================================

    DEV_ID = 889210700

    def setUp(self):
        self._saved = dict(_indigo.devices)
        self.w = wx.WeatherData(api_key="", cache_path=os.path.join(tempfile.mkdtemp(), "c.json"),
                                bypass_temp=6.0, ecowitt_dev_id=self.DEV_ID)
        self.w.current     = {"temp": 9.5}
        self.w.last_update = datetime.now()

    def tearDown(self):
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _ecowitt(self, temp, **states):
        _indigo.devices[self.DEV_ID] = FakeDevice(dict({"temperature": temp,
                                                        "deviceOnline": True}, **states))

    def test_a_fresh_ecowitt_reading_is_used(self):
        self._ecowitt(15.8, lastUpdate=_ago(1))
        self.assertEqual(self.w.get_outdoor_temp(), 15.8)

    def test_a_frozen_ecowitt_reading_falls_back_to_owm(self):
        self._ecowitt(15.8, lastUpdate=_ago(40))
        self.assertEqual(self.w.get_outdoor_temp(), 9.5)

    def test_without_lastupdate_the_device_change_time_is_used(self):
        _indigo.devices[self.DEV_ID] = FakeDevice({"temperature": 15.8, "deviceOnline": True},
                                                  last_changed=datetime.now() - timedelta(hours=2))
        self.assertEqual(self.w.get_outdoor_temp(), 9.5)

    def test_the_drying_gate_does_not_trust_a_frozen_reading_either(self):
        self._ecowitt(3.0, lastUpdate=_ago(40))
        self.w.last_update = datetime.now() - timedelta(hours=2)
        self.assertIsNone(self.w.get_measured_outdoor_temp())

    def test_owm_data_over_three_hours_old_is_not_used(self):
        self._ecowitt(15.8, lastUpdate=_ago(40))
        self.w.last_update = datetime.now() - timedelta(hours=4)
        self.assertEqual(self.w.get_outdoor_temp(), 6.0)

    def test_owm_data_just_under_three_hours_old_is_still_used(self):
        self._ecowitt(15.8, lastUpdate=_ago(40))
        self.w.last_update = datetime.now() - timedelta(hours=2, minutes=50)
        self.assertEqual(self.w.get_outdoor_temp(), 9.5)


# ===========================================================================
class TestZoneReadingAge(unittest.TestCase):
    """All 12 zones froze from 26 to 31 May 2026 while the RAMSES gateway was
    wedged, and the plugin went on acting on five-day-old temperatures."""
# ===========================================================================

    def setUp(self):
        hl._ZONE_STALE_LATCH.clear()
        self._saved = dict(_indigo.devices)
        self._saved_thermostat = _indigo.thermostat
        self.written = []
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda dev, value=None: self.written.append(value))
        self.rad = FakeDevice({"temperatureInput1": "18.0", "setpointHeat": "15.0",
                               "zoneMode": "permanent override", "lastSeen": _ago(3)})
        _indigo.devices[hl.DEV_BEDROOM_2_ID] = self.rad

    def tearDown(self):
        hl._ZONE_STALE_LATCH.clear()
        _indigo.thermostat = self._saved_thermostat
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _run(self):
        hl.process_room_temperature(
            room_name="Bedroom 2", room_schedule=[20] * 24, ha_device_id=hl.DEV_BEDROOM_2_ID,
            current_hour=12, current_minute=5, current_outdoor_temp=5.0,
            last_setpoints={}, last_messages={}, log_buffer=[], changes_buffer=[],
            overheat_monitor=None,
        )

    def test_a_fresh_zone_is_controlled(self):
        self._run()
        self.assertEqual(self.written, [20.0])

    def test_a_zone_not_heard_from_for_an_hour_is_left_alone(self):
        self.rad.states["lastSeen"] = _ago(60)
        self._run()
        self.assertEqual(self.written, [])

    def test_a_zone_with_no_lastseen_state_is_still_controlled(self):
        del self.rad.states["lastSeen"]
        self._run()
        self.assertEqual(self.written, [20.0])

    def test_it_warns_once_when_the_zone_goes_quiet_and_once_when_it_returns(self):
        self.rad.states["lastSeen"] = _ago(60)
        with mock.patch.object(hl, "_log") as log:
            self._run()
            self._run()
            self._run()
            warnings = [c for c in log.call_args_list if c.kwargs.get("level") == "WARNING"]
            self.assertEqual(len(warnings), 1)
            self.rad.states["lastSeen"] = _ago(1)
            self._run()
            self.assertTrue(any("reporting again" in c.args[0] for c in log.call_args_list))
        self.assertEqual(self.written, [20.0])


# ===========================================================================
class TestEnSuiteFloorHeating(unittest.TestCase):
    """Three ways the floor heating the plugin switched on could stay on until
    10:00 the next day."""
# ===========================================================================

    def setUp(self):
        self._saved_devices = dict(_indigo.devices)
        self._saved_device  = _indigo.device
        self._saved_thermo  = _indigo.thermostat
        self.sw = _SwitchRecorder()
        _indigo.device     = self.sw
        # 1.21.0: the floor goes on and off through its thermostat; the switch only
        # powers it. Both kinds of command land in the one list, in order.
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda d, value=None, **k: self.sw.calls.append(("setpoint", value)),
            setHvacMode=lambda d, value=None, **k: self.sw.calls.append(("mode", value)))
        self.switch = FakeDevice({"onOffState": True})
        self.switch.id = hl.DEV_EN_SUITE_FLOOR_HEAT_ID
        self.therm = FakeDevice({"hvacOperationModeIsHeat": False,
                                 "hvacOperationModeIsOff": True, "setpointHeat": 8.0})
        self.therm.id = hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_HEAT_ID]       = self.switch
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID] = self.therm
        hl._FLOOR["off_sent_at"] = 0.0

    def tearDown(self):
        _indigo.device     = self._saved_device
        _indigo.thermostat = self._saved_thermo
        _indigo.devices.clear()
        _indigo.devices.update(self._saved_devices)

    def _plugin(self, store=None, away=False):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs = {}
        p.store = {"en_suite_morning_active": False}
        p.store.update(store or {})
        p.weather  = None
        p.overheat = None
        p._summer_lockout_active = lambda: False
        p._away_mode_on          = lambda: away
        p._save_state            = lambda: None
        p._fire_event            = lambda *a, **k: None
        return p

    def _at(self, hour):
        dt = mock.patch(_PLUGIN + ".datetime")
        m = dt.start()
        self.addCleanup(dt.stop)
        m.now.return_value = datetime(2026, 10, 5, hour, 5)
        m.strptime = datetime.strptime
        return m

    FLOOR = hl.DEV_EN_SUITE_FLOOR_HEAT_ID
    ON    = [("mode", _indigo.kHvacMode.Heat), ("setpoint", hl.FLOOR_HEAT_ON_TEMP)]
    OFF   = [("mode", _indigo.kHvacMode.Off)]

    def _heating(self):
        self.therm.states.update({"hvacOperationModeIsHeat": True,
                                  "hvacOperationModeIsOff": False, "setpointHeat": 14.0})

    # -- Away mode --------------------------------------------------------------
    def test_a_cold_morning_at_home_still_starts_the_floor_heating(self):
        p = self._plugin()
        self._at(6)
        p._check_en_suite_morning()
        self.assertTrue(p.store["en_suite_morning_active"])
        self.assertEqual(self.sw.calls, self.ON)

    def test_an_unpowered_thermostat_is_powered_and_set_at_the_next_check(self):
        self.switch.states["onOffState"] = False
        p = self._plugin()
        self._at(6)
        p._check_en_suite_morning()
        self.assertTrue(p.store["en_suite_morning_active"])
        self.assertEqual(self.sw.calls, [("on", self.FLOOR)],
                         "nothing is sent to a thermostat that is still starting up")

    def test_away_mode_does_not_start_the_floor_heating(self):
        p = self._plugin(away=True)
        self._at(6)
        p._check_en_suite_morning()
        self.assertFalse(p.store["en_suite_morning_active"])
        self.assertEqual(self.sw.calls, [])

    def test_away_mode_stops_a_morning_already_running(self):
        self._heating()
        p = self._plugin(store={"en_suite_morning_active": True}, away=True)
        self._at(7)
        p._check_en_suite_morning()
        self.assertFalse(p.store["en_suite_morning_active"])
        self.assertEqual(self.sw.calls, self.OFF)

    def test_away_is_not_a_cancel_for_the_whole_day(self):
        p = self._plugin(store={"en_suite_morning_active": True}, away=True)
        self._at(7)
        p._check_en_suite_morning()
        p._away_mode_on = lambda: False
        p._check_en_suite_morning()
        self.assertTrue(p.store["en_suite_morning_active"])

    # -- Plugin stopped across 10:00 ---------------------------------------------
    def test_a_morning_saved_as_running_is_switched_off_after_ten(self):
        self._heating()
        p = self._plugin()
        self._at(11)
        p._restore_en_suite_morning(True)
        self.assertFalse(p.store["en_suite_morning_active"])
        self.assertEqual(self.sw.calls, self.OFF)

    def test_a_morning_saved_as_running_carries_on_before_ten(self):
        p = self._plugin()
        self._at(8)
        p._restore_en_suite_morning(True)
        self.assertTrue(p.store["en_suite_morning_active"])
        self.assertEqual(self.sw.calls, self.ON)

    def test_nothing_saved_touches_nothing(self):
        p = self._plugin()
        self._at(11)
        p._restore_en_suite_morning(False)
        self.assertEqual(self.sw.calls, [])

    # -- The heating cycle crossing 10:00 first ----------------------------------
    def test_the_cycle_ending_the_morning_at_ten_switches_the_floor_off(self):
        self._heating()
        p = self._plugin(store={"en_suite_morning_active": False,
                                "en_suite_morning_cancelled_reason": "10am_expired"})
        p._note_en_suite_morning_cancelled(True)
        self.assertEqual(self.sw.calls, self.OFF)

    def test_the_window_path_leaves_the_floor_to_the_room_rule(self):
        p = self._plugin(store={"en_suite_morning_active": False,
                                "en_suite_morning_cancelled_reason": "window_open"})
        p._note_en_suite_morning_cancelled(True)
        self.assertEqual(self.sw.calls, [])

    # -- An open window with Away on ---------------------------------------------
    def test_an_open_window_switches_the_floor_off_even_with_away_on(self):
        _indigo.devices[hl.DEV_EN_SUITE_ID] = FakeDevice({
            "temperatureInput1": "18.0", "setpointHeat": "15.0",
            "zoneMode": "permanent override", "lastSeen": _ago(1)})
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID]    = FakeDevice({"contact": False})
        self._heating()
        hl.process_room_temperature(
            room_name="En Suite", room_schedule=[18] * 24,
            window_devices=[hl.DEV_EN_SUITE_WINDOW_ID],
            floor_heat_device=hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID,
            ha_device_id=hl.DEV_EN_SUITE_ID, current_hour=12, current_minute=5,
            current_outdoor_temp=5.0, is_away=True,
            last_setpoints={}, last_messages={}, log_buffer=[], changes_buffer=[],
            overheat_monitor=None,
        )
        self.assertIn(self.OFF[0], self.sw.calls)
        self.assertNotIn(("off", hl.DEV_EN_SUITE_FLOOR_HEAT_ID), self.sw.calls)


if __name__ == "__main__":
    unittest.main()
