#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_20_en_suite_morning.py
# Description: 1.20.0 - the En Suite is held at 20 degC from 6am to 10am every day for
#              the morning shower, whatever the weather. CliveS, 09-10-2026. The old
#              warm-morning skip (10 degC outside) and the mild-weather cut-off (14 degC)
#              left the room at 16 degrees that morning.
# Author:      CliveS & Claude Opus 5.5
# Date:        09-10-2026
# Version:     1.0

import types
import unittest

from test_en_suite_drying import _indigo, _radiator, _window, hl
import test_fixes_1_12 as t12


class TestTheTemperature(unittest.TestCase):

    def test_the_morning_is_twenty_two_degrees(self):
        # 20 from 1.20.0; 22 again from 1.33.0 (CliveS, 26-11-2026).
        self.assertEqual(hl.EN_SUITE_MORNING_TEMP, 22.0)

    def test_a_saved_warm_morning_reason_from_before_means_nothing(self):
        store = {"en_suite_drying_active": False, "en_suite_morning_active": False,
                 "en_suite_morning_cancelled_reason": "warm_outdoor"}
        temp, msg = hl.en_suite_special_rules(19, 11, False, False, 0, 0, 15.0, 7, store=store)
        self.assertEqual((temp, msg), (19, 11))


class TestAMildMorningStillStarts(unittest.TestCase):
    # Borrow the fixture, not the tests: subclassing would run them all twice.
    _F       = t12.TestEnSuiteFloorHeating
    setUp    = _F.setUp
    tearDown = _F.tearDown
    _plugin  = _F._plugin
    _at      = _F._at
    FLOOR    = _F.FLOOR
    ON       = _F.ON

    def test_fifteen_degrees_outside_at_six_still_starts_the_morning(self):
        p = self._plugin()
        p.weather = types.SimpleNamespace(get_outdoor_temp=lambda: 15.0)
        self._at(6)
        p._check_en_suite_morning()
        self.assertTrue(p.store["en_suite_morning_active"])
        self.assertEqual(self.sw.calls, self.ON)
        self.assertNotEqual(p.store.get("en_suite_morning_cancelled_reason"), "warm_outdoor")


class TestTheRadiatorGetsTwenty(unittest.TestCase):

    def setUp(self):
        self._saved = dict(_indigo.devices)
        _indigo.devices.clear()
        _indigo.devices[hl.DEV_EN_SUITE_ID]        = _radiator(temp=16.0, setpoint=15.0)
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=True)
        self.written = []
        self._saved_thermostat = _indigo.thermostat
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda dev, value=None: self.written.append(value))

    def tearDown(self):
        _indigo.thermostat = self._saved_thermostat
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _run(self, outdoor, hour=7, morning=True):
        store = {"en_suite_morning_active": morning}
        hl.process_room_temperature(
            room_name      = "En Suite",
            room_schedule  = [18] * 24,
            window_devices = [hl.DEV_EN_SUITE_WINDOW_ID],
            special_rules  = lambda *a, **k: hl.en_suite_special_rules(*a, store=store, **k),
            ha_device_id   = hl.DEV_EN_SUITE_ID,
            current_hour   = hour,
            current_minute = 0,
            current_outdoor_temp = outdoor,
            overheat_target_override = hl.EN_SUITE_MORNING_TEMP if morning else None,
            last_setpoints = {}, last_messages = {},
            log_buffer = [], changes_buffer = [],
            overheat_monitor = None,
        )

    def test_a_cold_morning_gets_its_temperature(self):
        self._run(outdoor=5.0)
        self.assertEqual(self.written, [hl.EN_SUITE_MORNING_TEMP])

    def test_a_mild_morning_past_the_cut_off_still_gets_its_temperature(self):
        # 16 degC is past OUTDOOR_TEMP_TRIGGER (14), which turns every other radiator off.
        self._run(outdoor=16.0)
        self.assertEqual(self.written, [hl.EN_SUITE_MORNING_TEMP])

    def test_without_the_morning_a_mild_day_still_turns_it_off(self):
        self._run(outdoor=16.0, morning=False)
        self.assertEqual(self.written, [hl.RADIATORS_OFF_TEMP])


class TestTheMorningIsNotCutForOverheating(unittest.TestCase):
    """1.33.0. On 26-11-2026 the room reached 20.1 at 08:21 and the overheat rule set the
    radiator to 14 from 08:25 to 09:10, at shower time."""

    def setUp(self):
        import os
        import tempfile
        import overheat_monitor as om
        self._saved = dict(_indigo.devices)
        _indigo.devices.clear()
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=True)
        self.written = []
        self._saved_thermostat = _indigo.thermostat
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda dev, value=None: self.written.append(value))
        self.mon = om.OverheatMonitor(os.path.join(tempfile.mkdtemp(), "h.json"))

    def tearDown(self):
        _indigo.thermostat = self._saved_thermostat
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _run(self, room_temp, exempt):
        _indigo.devices[hl.DEV_EN_SUITE_ID] = _radiator(temp=room_temp, setpoint=15.0)
        store = {"en_suite_morning_active": True}
        hl.process_room_temperature(
            room_name      = "En Suite",
            room_schedule  = [18] * 24,
            window_devices = [hl.DEV_EN_SUITE_WINDOW_ID],
            special_rules  = lambda *a, **k: hl.en_suite_special_rules(*a, store=store, **k),
            ha_device_id   = hl.DEV_EN_SUITE_ID,
            current_hour   = 8,
            current_minute = 25,
            current_outdoor_temp = 3.0,
            overheat_target_override = hl.EN_SUITE_MORNING_TEMP,
            overheat_exempt = exempt,
            last_setpoints = {}, last_messages = {},
            log_buffer = [], changes_buffer = [],
            overheat_monitor = self.mon,
        )

    def test_a_room_above_its_morning_target_keeps_the_target(self):
        self._run(room_temp=hl.EN_SUITE_MORNING_TEMP + 0.5, exempt=True)
        self.assertEqual(self.written, [hl.EN_SUITE_MORNING_TEMP])

    def test_a_room_still_rising_towards_it_keeps_the_target(self):
        for temp in (21.2, 21.6, 21.9):
            self.written.clear()
            self._run(room_temp=temp, exempt=True)
            self.assertEqual(self.written, [hl.EN_SUITE_MORNING_TEMP])

    def test_without_the_exemption_the_same_room_is_cut(self):
        self._run(room_temp=hl.EN_SUITE_MORNING_TEMP + 0.5, exempt=False)
        self.assertEqual(self.written, [hl.EN_SUITE_MORNING_TEMP - hl.OVERHEAT_BACKOFF])

    def test_the_plugin_asks_for_the_exemption_only_while_the_morning_runs(self):
        import inspect
        import plugin as plugin_mod
        src = inspect.getsource(plugin_mod.Plugin)
        self.assertIn("overheat_exempt            = morning_active", src)


if __name__ == "__main__":
    unittest.main()
