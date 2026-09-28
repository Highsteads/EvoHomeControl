#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_timed_overrides.py
# Description: 1.13.0 - setpoints sent as timed overrides through RAMSES ESP, so a
#              stopped Indigo hands the house back to the Evohome timetable; renewed
#              about once an hour; the summer 8 degC hold stays permanent.
#              Run from this directory with:  python3 test_timed_overrides.py
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5.5
# Date:        28-09-2026
# Version:     1.0

import os
import sys
import types
import unittest
from datetime import datetime, timedelta

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

_FMT = "%Y-%m-%d %H:%M"


class FakeZone:
    def __init__(self, dev_id=hl.DEV_BEDROOM_2_ID, setpoint="20.0",
                 mode="temporary override", ends_in=90):
        self.id = dev_id
        self.name = f"Zone {dev_id}"
        until = (datetime.now() + timedelta(minutes=ends_in)).strftime(_FMT) if ends_in is not None else ""
        self.states = {"temperatureInput1": "19.0", "setpointHeat": setpoint,
                       "zoneMode": mode, "zoneOverrideUntil": until,
                       "lastSeen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


class FakeRamses:
    def __init__(self, enabled=True, raises=None):
        self.enabled, self.raises, self.calls = enabled, raises, []

    def isEnabled(self):
        return self.enabled

    def executeAction(self, action_id, deviceId=0, props=None, **kw):
        if self.raises:
            raise self.raises
        self.calls.append((action_id, deviceId, dict(props or {})))


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved_server   = _indigo.server
        self._saved_thermo   = _indigo.thermostat
        self._saved_devices  = dict(_indigo.devices)
        self.permanent = []
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda dev, value=None: self.permanent.append((dev.id, value)))
        self.ramses = FakeRamses()
        server = types.SimpleNamespace(log=lambda *a, **k: None,
                                       getInstallFolderPath=lambda: "/tmp/evohome-test",
                                       getPlugin=lambda pid: self.ramses)
        _indigo.server = server
        hl._OVERRIDE_WARNED.clear()
        hl.set_override_minutes(120)

    def tearDown(self):
        hl.set_override_minutes(0)
        _indigo.server     = self._saved_server
        _indigo.thermostat = self._saved_thermo
        _indigo.devices.clear()
        _indigo.devices.update(self._saved_devices)


# ===========================================================================
class TestWhenToRenew(_Base):
# ===========================================================================

    def test_a_timed_override_with_time_to_spare_is_left_alone(self):
        self.assertFalse(hl.needs_override_refresh(FakeZone(ends_in=90)))

    def test_one_ending_within_the_hour_is_renewed(self):
        self.assertTrue(hl.needs_override_refresh(FakeZone(ends_in=50)))

    def test_a_zone_on_its_timetable_or_held_permanently_is_taken_over(self):
        self.assertTrue(hl.needs_override_refresh(FakeZone(mode="schedule", ends_in=None)))
        self.assertTrue(hl.needs_override_refresh(FakeZone(mode="permanent override", ends_in=None)))

    def test_an_unreadable_end_time_counts_as_ending(self):
        z = FakeZone()
        z.states["zoneOverrideUntil"] = ""
        self.assertTrue(hl.needs_override_refresh(z))

    def test_the_summer_hold_wants_a_permanent_override(self):
        self.assertFalse(hl.needs_override_refresh(
            FakeZone(mode="permanent override", ends_in=None), permanent=True))
        self.assertTrue(hl.needs_override_refresh(FakeZone(), permanent=True))

    def test_set_to_never_it_behaves_as_before(self):
        hl.set_override_minutes(0)
        self.assertFalse(hl.needs_override_refresh(FakeZone(mode="permanent override", ends_in=None)))


# ===========================================================================
class TestSending(_Base):
# ===========================================================================

    def test_a_timed_setpoint_goes_through_ramses_with_its_device(self):
        z = FakeZone()
        hl.send_setpoint(z, 20.5)
        self.assertEqual(self.ramses.calls,
                         [("setTemporarySetpoint", z.id, {"setpoint": "20.50", "minutes": "120"})])
        self.assertEqual(self.permanent, [])

    def test_the_summer_hold_is_sent_permanent(self):
        z = FakeZone()
        hl.send_setpoint(z, 8.0, permanent=True)
        self.assertEqual(self.permanent, [(z.id, 8.0)])
        self.assertEqual(self.ramses.calls, [])

    def test_a_refusal_falls_back_to_permanent_and_stays_there(self):
        self.ramses.raises = RuntimeError("no such action")
        z = FakeZone(mode="permanent override", ends_in=None)
        hl.send_setpoint(z, 20.5)
        self.assertEqual(self.permanent, [(z.id, 20.5)])
        # Otherwise every cycle would resend every room, forever.
        self.assertFalse(hl.needs_override_refresh(z))

    def test_saving_the_settings_tries_timed_again(self):
        self.ramses.raises = RuntimeError("no such action")
        hl.send_setpoint(FakeZone(), 20.5)
        self.ramses.raises = None
        hl.set_override_minutes(120)
        hl.send_setpoint(FakeZone(), 20.5)
        self.assertEqual(len(self.ramses.calls), 1)


# ===========================================================================
class TestTheCycle(_Base):
# ===========================================================================

    def _run(self, zone):
        _indigo.devices[zone.id] = zone
        hl.process_room_temperature(
            room_name="Bedroom 2", room_schedule=[20] * 24, ha_device_id=zone.id,
            current_hour=12, current_minute=5, current_outdoor_temp=5.0,
            last_setpoints={}, last_messages={}, log_buffer=[], changes_buffer=[],
            overheat_monitor=None,
        )

    def test_a_room_already_set_with_time_to_spare_is_not_resent(self):
        self._run(FakeZone(ends_in=90))
        self.assertEqual(self.ramses.calls, [])

    def test_a_room_whose_override_ends_soon_is_renewed(self):
        self._run(FakeZone(ends_in=45))
        self.assertEqual(len(self.ramses.calls), 1)

    def test_a_changed_setpoint_is_sent_at_once(self):
        self._run(FakeZone(setpoint="18.0", ends_in=90))
        self.assertEqual(self.ramses.calls[0][2]["setpoint"], "20.00")


# ===========================================================================
class TestSummerHold(_Base):
# ===========================================================================

    def _plugin(self, drying=False):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs = {"enSuiteDryingTemp": "20"}
        p.store = {"en_suite_drying_active": drying}
        p._save_state = lambda: None
        return p

    def _all_zones(self, **kw):
        for dev_id in hl.ALL_RADIATOR_IDS:
            _indigo.devices[dev_id] = FakeZone(dev_id=dev_id, **kw)
        floor = types.SimpleNamespace(onState=False)
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_HEAT_ID] = floor

    def test_the_summer_hold_is_permanent_eight_degrees(self):
        self._all_zones(setpoint="20.0", mode="temporary override")
        self._plugin()._apply_summer_off()
        self.assertEqual(len(self.permanent), len(hl.ALL_RADIATOR_IDS))
        self.assertTrue(all(v == hl.RADIATORS_OFF_TEMP for _i, v in self.permanent))
        self.assertEqual(self.ramses.calls, [])

    def test_the_drying_run_is_timed_so_it_cannot_outlive_indigo(self):
        self._all_zones(setpoint="8.0", mode="permanent override", ends_in=None)
        self._plugin(drying=True)._apply_summer_off()
        self.assertEqual([c[1] for c in self.ramses.calls], [hl.DEV_EN_SUITE_ID])
        self.assertEqual(self.permanent, [])


if __name__ == "__main__":
    unittest.main()
