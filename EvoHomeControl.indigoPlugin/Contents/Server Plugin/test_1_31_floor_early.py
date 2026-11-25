#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_31_floor_early.py
# Description: 1.31.0 - the En Suite floor's start hour and temperature are settings, and
#              the floor can start ahead of the 6am morning schedule. 1.31.1 - the
#              defaults are 6am and 14 again (CliveS, 25-11-2026: the floor is only to
#              take the chill off the tiles), so these tests set an early hour themselves.
# Author:      CliveS & Claude Fable 5.2
# Date:        25-11-2026 14:20
# Version:     1.1

import unittest

from test_en_suite_drying import _indigo, _window, hl
import test_fixes_1_12 as t12


class _Floor(unittest.TestCase):
    # Borrow the fixture, not the tests: subclassing would run them all twice.
    _F       = t12.TestEnSuiteFloorHeating
    _plugin  = _F._plugin
    _at      = _F._at
    _heating = _F._heating
    OFF      = _F.OFF

    def setUp(self):
        self._F.setUp(self)
        self._saved_floor = dict(hl._FLOOR)
        hl.set_floor_heat_temp(hl.FLOOR_HEAT_ON_TEMP)
        hl.set_floor_start_hour(4)      # the early start under test; the default is 6

    def tearDown(self):
        hl._FLOOR.clear()
        hl._FLOOR.update(self._saved_floor)
        self._F.tearDown(self)

    def _on(self, temp=None):
        return [("mode", _indigo.kHvacMode.Heat),
                ("setpoint", hl.FLOOR_HEAT_ON_TEMP if temp is None else temp)]


class TestTheDefaults(unittest.TestCase):

    def test_the_floor_heats_to_fourteen_from_six(self):
        self.assertEqual(hl.FLOOR_HEAT_ON_TEMP, 14.0)
        self.assertEqual(hl.EN_SUITE_FLOOR_START_HOUR, 6)

    def test_a_blank_or_wrong_temperature_gives_the_default(self):
        for bad in ("", None, "warm"):
            self.assertEqual(hl.coerce_floor_temp(bad), 14.0)

    def test_the_temperature_is_whole_and_kept_between_five_and_twenty_seven(self):
        self.assertEqual(hl.coerce_floor_temp("18.6"), 19.0)
        self.assertEqual(hl.coerce_floor_temp("40"), 27.0)
        self.assertEqual(hl.coerce_floor_temp("1"), 5.0)

    def test_the_start_hour_is_kept_between_midnight_and_six(self):
        self.assertEqual(hl.coerce_floor_start_hour(""), 6)
        self.assertEqual(hl.coerce_floor_start_hour("9"), 6)
        self.assertEqual(hl.coerce_floor_start_hour("-1"), 0)
        self.assertEqual(hl.coerce_floor_start_hour("3"), 3)


class TestTheEarlyStart(_Floor):

    def test_with_the_default_hour_nothing_happens_before_six(self):
        hl.set_floor_start_hour(hl.EN_SUITE_FLOOR_START_HOUR)
        p = self._plugin()
        self._at(4)
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, [])
        self.assertFalse(p.store.get("en_suite_floor_early"))

    def test_at_four_the_floor_goes_on_and_the_radiator_morning_does_not_start(self):
        p = self._plugin()
        self._at(4)
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, self._on())
        self.assertTrue(p.store["en_suite_floor_early"])
        self.assertFalse(p.store["en_suite_morning_active"])

    def test_it_is_sent_once_not_every_tick(self):
        p = self._plugin()
        self._at(4)
        p._check_en_suite_morning()
        self._heating()
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, self._on())

    def test_at_three_nothing_happens(self):
        p = self._plugin()
        self._at(3)
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, [])
        self.assertFalse(p.store.get("en_suite_floor_early"))

    def test_away_gets_no_early_floor(self):
        p = self._plugin(away=True)
        self._at(4)
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, [])
        self.assertFalse(p.store.get("en_suite_floor_early"))

    def test_an_open_window_gets_no_early_floor(self):
        _indigo.devices[hl.DEV_EN_SUITE_WINDOW_ID] = _window(shut=False)
        p = self._plugin()
        self._at(5)
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, [])
        self.assertFalse(p.store.get("en_suite_floor_early"))

    def test_a_start_hour_of_six_means_no_early_floor(self):
        hl.set_floor_start_hour(6)
        p = self._plugin()
        self._at(5)
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, [])

    def test_a_start_hour_of_two_starts_at_two(self):
        hl.set_floor_start_hour("2")
        p = self._plugin()
        self._at(2)
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, self._on())

    def test_the_setting_is_the_temperature_sent(self):
        hl.set_floor_heat_temp("23")
        p = self._plugin()
        self._at(4)
        p._check_en_suite_morning()
        self.assertEqual(self.sw.calls, self._on(23.0))


class TestWhatEndsIt(_Floor):

    def test_at_six_the_morning_takes_the_floor_over_and_leaves_it_on(self):
        p = self._plugin(store={"en_suite_floor_early": True})
        self._heating()
        self._at(6)
        p._check_en_suite_morning()
        self.assertTrue(p.store["en_suite_morning_active"])
        self.assertFalse(p.store["en_suite_floor_early"])
        self.assertEqual(self.sw.calls, [])

    def test_a_morning_that_does_not_start_gives_the_floor_up(self):
        p = self._plugin(store={"en_suite_floor_early": True,
                                "en_suite_morning_cancelled_date": "2026-10-05"})
        self._heating()
        self._at(6)
        p._check_en_suite_morning()
        self.assertFalse(p.store["en_suite_morning_active"])
        self.assertFalse(p.store["en_suite_floor_early"])
        self.assertEqual(self.sw.calls, self.OFF)

    def test_away_during_the_early_start_switches_it_off(self):
        p = self._plugin(store={"en_suite_floor_early": True}, away=True)
        self._heating()
        self._at(5)
        p._check_en_suite_morning()
        self.assertFalse(p.store["en_suite_floor_early"])
        self.assertEqual(self.sw.calls, self.OFF)

    def test_a_floor_left_on_early_is_switched_off_later_in_the_day(self):
        p = self._plugin(store={"en_suite_floor_early": True})
        self._heating()
        self._at(11)
        p._check_en_suite_morning()
        self.assertFalse(p.store["en_suite_floor_early"])
        self.assertEqual(self.sw.calls, self.OFF)


if __name__ == "__main__":
    unittest.main()
