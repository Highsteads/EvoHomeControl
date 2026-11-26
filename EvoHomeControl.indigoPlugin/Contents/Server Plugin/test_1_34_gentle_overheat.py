#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_34_gentle_overheat.py
# Description: 1.34.0 - two rooms on trial get their target and are left alone; the setting
#              is lowered by 1 only after 30 minutes more than 1.5 above target, and goes
#              back with no fixed wait. CliveS, 26-11-2026. The standard rule cut 6 degrees
#              for 45 minutes about 36 times a day across the house.
# Author:      CliveS & Claude Fable 5.2
# Date:        26-11-2026 13:05
# Version:     1.0

import os
import tempfile
import unittest

from test_en_suite_drying import hl
import overheat_monitor as om

ROOM   = "Dining Room"
TARGET = 20.0


class TestTheGentleRule(unittest.TestCase):

    def setUp(self):
        self.mon = om.OverheatMonitor(os.path.join(tempfile.mkdtemp(), "h.json"))

    def _check(self, temp, room=ROOM):
        return hl.check_overheating(temp, TARGET, room, self.mon, run_interval_mins=5)

    def test_the_trial_rooms(self):
        self.assertEqual(hl.GENTLE_OVERHEAT_ROOMS, {"Dining Room", "Living Room Door"})

    def test_a_room_rising_towards_its_target_is_left_alone(self):
        # The standard rule's coast and predictive tiers close the valve here.
        for temp in (19.2, 19.6, 19.9, 20.2):
            self.assertEqual(self._check(temp), (False, TARGET, 0.0))

    def test_the_same_rise_is_cut_in_a_room_not_on_trial(self):
        results = [self._check(t, room="Living Room Front") for t in (19.2, 19.6, 19.9, 20.2)]
        self.assertTrue(any(r[0] and r[1] == TARGET - hl.OVERHEAT_BACKOFF for r in results))

    def test_a_little_over_target_is_left_alone_however_long(self):
        for _ in range(40):
            self.assertEqual(self._check(21.4), (False, TARGET, 0.0))

    def test_well_over_target_is_lowered_by_one_only_after_half_an_hour(self):
        for _ in range(5):                          # 25 minutes
            self.assertEqual(self._check(21.8), (False, TARGET, 0.0))
        hot, setting, amount = self._check(21.8)    # the sixth check, 30 minutes
        self.assertTrue(hot)
        self.assertEqual(setting, TARGET - hl.GENTLE_BACKOFF)
        self.assertAlmostEqual(amount, 1.8)

    def test_a_dip_back_under_the_line_starts_the_half_hour_again(self):
        for _ in range(5):
            self._check(21.8)
        self._check(21.2)
        self.assertEqual(self._check(21.8), (False, TARGET, 0.0))

    def test_it_goes_back_with_no_wait_once_near_target(self):
        for _ in range(6):
            self._check(21.8)
        self.assertTrue(self._check(20.9)[0])       # still lowered while over the release line
        self.assertEqual(self._check(20.5), (False, TARGET, 0.0))
        self.assertEqual(self._check(21.0), (False, TARGET, 0.0))

    def test_the_setting_is_never_under_the_floor(self):
        for _ in range(6):
            result = hl.check_overheating(15.0, 12.5, ROOM, self.mon, run_interval_mins=5)
        self.assertEqual(result[1], hl.OVERHEAT_MIN_SETPOINT)


if __name__ == "__main__":
    unittest.main()
