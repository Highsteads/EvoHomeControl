#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_16_hand_and_summer.py
# Description: 1.16.0 - a room changed by hand (controller screen, valve wheel, app) is left
#              alone until its plan next changes, and the summer 8 degC hold ends by itself
#              on the day heating is due back.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0

import unittest
from datetime import date, datetime, timedelta

from test_timed_overrides import FakeZone, _Base, _indigo, hl, plugin_mod

_STAMP = "%Y-%m-%d %H:%M:%S"
# A day that is 16 until 7am, 20 until 10pm, then 16 again.
PLAN = [16] * 7 + [20] * 15 + [16] * 2


def _hand(dev, changed, mode="temporary override", setpoint="22.0"):
    dev.states.update({"setpointSource": "manual", "zoneMode": mode,
                       "setpointHeat": setpoint, "setpointChangedAt": changed.strftime(_STAMP)})
    return dev


class TestHoldUntil(unittest.TestCase):

    def setUp(self):
        hl._MANUAL_ANNOUNCED.clear()
        hl._SENT.clear()

    def test_a_morning_change_holds_until_the_plan_next_moves(self):
        dev = _hand(FakeZone(), datetime(2026, 10, 20, 8, 15))
        end = hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 20, 12, 0))
        self.assertEqual(end, datetime(2026, 10, 20, 22, 0))

    def test_a_late_change_ends_at_midnight_at_the_latest(self):
        dev = _hand(FakeZone(), datetime(2026, 10, 20, 22, 30))
        end = hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 20, 23, 0))
        self.assertEqual(end, datetime(2026, 10, 21, 0, 0))

    def test_the_hold_ends(self):
        dev = _hand(FakeZone(), datetime(2026, 10, 20, 8, 15))
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 20, 22, 0)))

    def test_a_permanent_change_by_hand_holds_while_it_stays(self):
        dev = _hand(FakeZone(), datetime(2026, 10, 1, 8, 0), mode="permanent override")
        self.assertEqual(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 12, 1)), "permanent")

    def test_back_on_the_timetable_is_not_a_hold(self):
        dev = _hand(FakeZone(), datetime(2026, 10, 20, 8, 15), mode="schedule")
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 20, 9, 0)))

    def test_our_own_change_is_not_a_hold(self):
        dev = _hand(FakeZone(), datetime(2026, 10, 20, 8, 15))
        dev.states["setpointSource"] = "indigo"
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 20, 9, 0)))

    def test_an_older_ramses_with_no_source_is_not_a_hold(self):
        dev = FakeZone()
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 20, 9, 0)))

    def test_an_unreadable_time_is_not_a_hold(self):
        dev = _hand(FakeZone(), datetime(2026, 10, 20, 8, 15))
        dev.states["setpointChangedAt"] = ""
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 20, 9, 0)))


class TestHoldIsSaidOnce(unittest.TestCase):

    def setUp(self):
        hl._MANUAL_ANNOUNCED.clear()
        self.lines = []
        self._saved = hl._log
        hl._log = lambda msg, **k: self.lines.append(msg)

    def tearDown(self):
        hl._log = self._saved

    def test_one_line_when_it_starts_and_one_when_it_ends(self):
        dev = _hand(FakeZone(), datetime.now() - timedelta(minutes=5))
        flat = [20] * 24
        for _ in range(3):
            self.assertTrue(hl.check_manual_hold("Bedroom 2", dev, flat))
        self.assertEqual(len(self.lines), 1)
        self.assertIn("Bedroom 2 was set to 22 degrees by hand", self.lines[0])
        self.assertIn("until midnight", self.lines[0])
        dev.states["zoneMode"] = "schedule"
        self.assertFalse(hl.check_manual_hold("Bedroom 2", dev, flat))
        self.assertFalse(hl.check_manual_hold("Bedroom 2", dev, flat))
        self.assertEqual(self.lines[1:], ["Bedroom 2 is back under the heating plugin's control."])

    def test_the_clock_is_said_the_way_a_person_says_it(self):
        self.assertEqual(hl._clock_words(datetime(2026, 1, 1, 22, 0)), "10pm")
        self.assertEqual(hl._clock_words(datetime(2026, 1, 1, 12, 0)), "noon")
        self.assertEqual(hl._clock_words(datetime(2026, 1, 1, 0, 0)), "midnight")
        self.assertEqual(hl._clock_words(datetime(2026, 1, 1, 6, 30)), "6:30am")


class TestHeatingSeason(_Base):

    def _run(self, zone):
        _indigo.devices[zone.id] = zone
        hl.process_room_temperature(
            room_name="Bedroom 2", room_schedule=[20] * 24, ha_device_id=zone.id,
            current_hour=12, current_minute=5, current_outdoor_temp=5.0,
            last_setpoints={}, last_messages={}, log_buffer=[], changes_buffer=[],
            overheat_monitor=None,
        )

    def setUp(self):
        super().setUp()
        hl._MANUAL_ANNOUNCED.clear()

    def test_a_room_changed_by_hand_is_not_put_back(self):
        # Ending in 10 minutes would normally be renewed; set by hand it is left alone.
        zone = _hand(FakeZone(ends_in=10), datetime.now() - timedelta(minutes=3))
        self._run(zone)
        self.assertEqual(self.ramses.calls, [])
        self.assertEqual(self.permanent, [])

    def test_the_same_room_set_by_indigo_is_renewed(self):
        zone = _hand(FakeZone(ends_in=10), datetime.now() - timedelta(minutes=3))
        zone.states["setpointSource"] = "indigo"
        self._run(zone)
        self.assertEqual(len(self.ramses.calls), 1)


class TestSummerHoldEnds(_Base):

    def setUp(self):
        super().setUp()
        hl._MANUAL_ANNOUNCED.clear()
        self.ramses.pluginVersion = "1.15.0"

    def _plugin(self, drying=False, on="14 Oct"):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs = {"enSuiteDryingTemp": "20"}
        p.store = {"en_suite_drying_active": drying}
        p._save_state = lambda: None
        p._summer_window = lambda: (6, 1, 10, 14)
        return p

    def _zones(self, **kw):
        for dev_id in hl.ALL_RADIATOR_IDS:
            _indigo.devices[dev_id] = FakeZone(dev_id=dev_id, **kw)
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_HEAT_ID] = type("F", (), {"onState": False})()

    def test_the_end_is_midnight_on_the_day_heating_comes_back(self):
        p = self._plugin()
        self.assertEqual(p._summer_hold_until(date(2026, 9, 29)), "2026-10-14 00:00")
        self.assertEqual(p._summer_hold_until(date(2026, 10, 14)), "2027-10-14 00:00")
        self.assertEqual(p._summer_hold_until(date(2026, 7, 1)), "2026-10-14 00:00")

    def test_the_hold_is_sent_with_that_end(self):
        self._zones(setpoint="20.0", mode="temporary override")
        p = self._plugin()
        end = p._summer_hold_until()
        p._apply_summer_off()
        self.assertEqual(self.permanent, [])
        self.assertEqual(len(self.ramses.calls), len(hl.ALL_RADIATOR_IDS))
        for action, _dev, props in self.ramses.calls:
            self.assertEqual(action, "setTemporarySetpoint")
            self.assertEqual(props, {"setpoint": "8.00", "until": end})

    def test_a_zone_already_holding_that_end_is_left_alone(self):
        p = self._plugin()
        self._zones(setpoint="8.0", mode="temporary override")
        for dev_id in hl.ALL_RADIATOR_IDS:
            _indigo.devices[dev_id].states["zoneOverrideUntil"] = p._summer_hold_until()
        p._apply_summer_off()
        self.assertEqual(self.ramses.calls, [])
        self.assertEqual(self.permanent, [])

    def test_the_old_permanent_hold_is_replaced_once(self):
        self._zones(setpoint="8.0", mode="permanent override", ends_in=None)
        self._plugin()._apply_summer_off()
        self.assertEqual(len(self.ramses.calls), len(hl.ALL_RADIATOR_IDS))

    def test_a_room_changed_by_hand_is_left_alone_in_summer(self):
        self._zones(setpoint="8.0", mode="temporary override")
        room = _indigo.devices[hl.DEV_BEDROOM_3_ID]
        _hand(room, datetime.now() - timedelta(minutes=2), setpoint="19.0")
        self._plugin()._apply_summer_off()
        self.assertNotIn(hl.DEV_BEDROOM_3_ID, [c[1] for c in self.ramses.calls])
        self.assertEqual(len(self.ramses.calls), len(hl.ALL_RADIATOR_IDS) - 1)


if __name__ == "__main__":
    unittest.main()
