#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_21_floor_by_thermostat.py
# Description: 1.21.0 - the En Suite underfloor heating is turned on and off through its
#              Heatit TF021 thermostat. The Z-Wave switch only powers the thermostat, so
#              it is turned on when the floor is wanted and never off. Its use as the
#              on/off control cut the thermostat's power, which is why it answered nothing
#              for a week and why the 6am "heat to 14" went to a thermostat still starting.
# Author:      CliveS & Claude Opus 5.5
# Date:        09-10-2026
# Version:     1.0

import unittest

import test_fixes_1_12 as t12
from test_fixes_1_12 import FakeDevice, _ago, _indigo, hl


class TestTheHeatingCheckCatchesUp(unittest.TestCase):
    """The heating cycle is the second chance: a 6am start that only powered the
    thermostat, or a command it never confirmed, is sent again within five minutes."""

    _F       = t12.TestEnSuiteFloorHeating
    setUp    = _F.setUp
    tearDown = _F.tearDown
    _heating = _F._heating
    ON       = _F.ON

    def _cycle(self, morning=True):
        _indigo.devices[hl.DEV_EN_SUITE_ID] = FakeDevice({
            "temperatureInput1": "17.0", "setpointHeat": "15.0",
            "zoneMode": "temporary override", "lastSeen": _ago(1)})
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = FakeDevice({"contact": True})
        hl.process_room_temperature(
            room_name="En Suite", room_schedule=[18] * 24,
            window_devices=[hl.DEV_EN_SUITE_WINDOW_ID],
            floor_heat_device=hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID,
            floor_heat_restore_enabled=morning,
            ha_device_id=hl.DEV_EN_SUITE_ID, current_hour=7, current_minute=5,
            current_outdoor_temp=5.0,
            last_setpoints={}, last_messages={}, log_buffer=[], changes_buffer=[],
            overheat_monitor=None,
        )
        return [c for c in self.sw.calls if c[0] in ("mode", "on", "off")
                or (c[0] == "setpoint" and c[1] == hl.FLOOR_HEAT_ON_TEMP)]

    def test_a_thermostat_not_yet_heating_is_set_during_the_morning(self):
        self.assertEqual(self._cycle(), self.ON)

    def test_a_thermostat_already_heating_is_left_alone(self):
        self._heating()
        self.assertEqual(self._cycle(), [])

    def test_a_thermostat_that_reports_nothing_is_set(self):
        self.therm.states.clear()
        self.assertEqual(self._cycle(), self.ON)

    def test_outside_the_morning_the_cycle_does_not_turn_it_on(self):
        self.assertEqual(self._cycle(morning=False), [])


class TestTheSummerShutOff(unittest.TestCase):

    _F       = t12.TestEnSuiteFloorHeating
    setUp    = _F.setUp
    tearDown = _F.tearDown
    _heating = _F._heating
    _plugin  = _F._plugin
    OFF      = _F.OFF

    def test_the_shut_off_turns_a_heating_floor_off_through_its_thermostat(self):
        self._heating()
        p = self._plugin()
        p._summer_window = lambda: (6, 1, 10, 14)
        p._apply_summer_off()
        self.assertEqual([c for c in self.sw.calls if c[0] in ("mode", "off")], self.OFF)


class TestTheHelpers(unittest.TestCase):

    _F       = t12.TestEnSuiteFloorHeating
    setUp    = _F.setUp
    tearDown = _F.tearDown

    def test_heating_means_heat_mode_at_the_morning_temperature(self):
        self.assertFalse(hl.floor_heat_is_heating(None))
        self.assertFalse(hl.floor_heat_is_heating(FakeDevice({"hvacOperationModeIsHeat": True,
                                                              "setpointHeat": 8.0})))
        self.assertFalse(hl.floor_heat_is_heating(FakeDevice({"hvacOperationModeIsHeat": "True",
                                                              "setpointHeat": 14.0})))
        self.assertTrue(hl.floor_heat_is_heating(FakeDevice({"hvacOperationModeIsHeat": True,
                                                             "setpointHeat": 14.0})))

    def test_a_missing_thermostat_sends_nothing(self):
        del _indigo.devices[hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID]
        self.assertFalse(hl.floor_heat_on())
        self.assertFalse(hl.floor_heat_off())
        self.assertEqual(self.sw.calls, [])

    def test_the_power_switch_is_never_turned_off(self):
        self.therm.states.update({"hvacOperationModeIsOff": False})
        hl.floor_heat_off("test")
        self.assertNotIn(("off", hl.DEV_EN_SUITE_FLOOR_HEAT_ID), self.sw.calls)


if __name__ == "__main__":
    unittest.main()
