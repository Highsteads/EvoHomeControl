#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_30_timed_boost_holds.py
# Description: 1.30.0 - a timed boost holds its rooms at the boost temperature for the
#              whole time. It beats the overheat and passive-warmth holds, the mild-weather
#              cut-off, both-out and a setting made by hand before it started. An open
#              window, Away and the Conservatory's shut sliding door still beat it, and a
#              setting made by hand after it started is still left alone.
# Author:      CliveS & Claude Fable 5.2
# Date:        25-11-2026
# Version:     1.0

import time
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

from test_timed_overrides import FakeZone, _Base, _indigo, hl, plugin_mod

_STAMP  = "%Y-%m-%d %H:%M:%S"
TARGETS = {"Dining Room": 22.0, "Conservatory": 22.0}
ROOMS   = {"Dining Room", "Conservatory"}
PLAN    = [18] * 24


def _monitor(history=None):
    return types.SimpleNamespace(history=history if history is not None else {},
                                 initialize_room=lambda room: None,
                                 update_room=lambda **kw: None)


class TestATimedBoostHoldsItsTemperature(_Base):

    def setUp(self):
        super().setUp()
        hl._MANUAL_ANNOUNCED.clear()
        self._patches = [mock.patch.object(hl.schedules, "BOOST_TARGETS", TARGETS, create=True),
                         mock.patch.object(hl.schedules, "MAX_TEMP_LIMITS", {}, create=True)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        super().tearDown()

    def _run(self, zone, room="Dining Room", monitor=None, since=None, **kw):
        _indigo.devices[zone.id] = zone
        setpoints, messages = {}, {}
        args = dict(room_name=room, room_schedule=PLAN, ha_device_id=zone.id,
                    current_hour=12, current_minute=5, current_outdoor_temp=5.0,
                    last_setpoints=setpoints, last_messages=messages, log_buffer=[],
                    changes_buffer=[], overheat_monitor=monitor or _monitor(),
                    timed_boost_active=True, timed_boost_rooms=ROOMS,
                    timed_boost_since=since)
        args.update(kw)
        hl.process_room_temperature(**args)
        return setpoints.get(room), messages.get(room)

    def _zone(self, temperature, setpoint="18.0"):
        zone = FakeZone(setpoint=setpoint)
        zone.states["temperatureInput1"] = str(temperature)
        return zone

    def test_a_room_already_over_its_target_is_still_set_to_22(self):
        # 25-Nov-2026: the page said "kept at 14 degrees because it is already warm".
        self.assertEqual(self._run(self._zone(23.4)), (22.0, 12))

    def test_a_passive_warmth_hold_from_before_does_not_carry_in(self):
        history = {"Dining Room": {"off_since_cycle": 6, "is_coasting": True,
                                   "consecutive_cycles": 6, "temp_history": [22.5, 22.6]}}
        self.assertEqual(self._run(self._zone(22.6), monitor=_monitor(history)), (22.0, 12))
        self.assertEqual(history["Dining Room"]["off_since_cycle"], 0)
        self.assertFalse(history["Dining Room"]["is_coasting"])

    def test_a_mild_day_outside_does_not_cancel_it(self):
        self.assertEqual(self._run(self._zone(19.0), current_outdoor_temp=15.0), (22.0, 12))

    def test_both_out_does_not_take_four_degrees_off(self):
        self.assertEqual(self._run(self._zone(19.0), is_both_out=True), (22.0, 12))

    def test_away_still_beats_it(self):
        setpoint, message = self._run(self._zone(17.0), is_away=True)
        self.assertEqual(message, 8)
        self.assertLess(setpoint, 22.0)

    def test_the_conservatory_with_its_door_shut_is_not_boosted(self):
        with mock.patch.object(hl, "_slide_door_open", return_value=False):
            self.assertFalse(hl.timed_boost_wins("Conservatory", True, ROOMS, False))
        with mock.patch.object(hl, "_slide_door_open", return_value=True):
            self.assertTrue(hl.timed_boost_wins("Conservatory", True, ROOMS, False))

    def test_who_the_boost_decides_for(self):
        self.assertTrue(hl.timed_boost_wins("Dining Room", True, ROOMS, False))
        self.assertFalse(hl.timed_boost_wins("Dining Room", False, ROOMS, False))
        self.assertFalse(hl.timed_boost_wins("Dining Room", True, ROOMS, True))
        self.assertFalse(hl.timed_boost_wins("Bedroom 1", True, ROOMS, False))
        self.assertFalse(hl.timed_boost_wins("Dining Room", True, None, False))

    def test_without_a_timed_boost_an_overheating_room_is_still_turned_down(self):
        setpoint, message = self._run(self._zone(23.4), timed_boost_active=False,
                                      room_schedule=[20] * 24)
        self.assertIn(message, (17, 23))
        self.assertLess(setpoint, 20.0)

    # ---- settings made by hand ----

    def _by_hand(self, zone, made, setpoint="20.0"):
        hl.note_sent(zone, 18.0, when=made - timedelta(minutes=5))
        zone.states.update({"setpointSource": "indigo", "zoneMode": "permanent override",
                            "setpointHeat": setpoint,
                            "setpointChangedAt": made.strftime(_STAMP)})
        return zone

    def test_a_setting_made_by_hand_before_the_boost_is_replaced(self):
        made = datetime.now().replace(microsecond=0) - timedelta(minutes=10)
        zone = self._by_hand(self._zone(19.0), made)
        since = time.time() - 60
        self.assertEqual(self._run(zone, since=since), (22.0, 12))

    def test_a_setting_made_by_hand_during_the_boost_is_left_alone(self):
        made = datetime.now().replace(microsecond=0) - timedelta(minutes=2)
        zone = self._by_hand(self._zone(19.0), made)
        since = time.time() - 600
        self.assertEqual(self._run(zone, since=since), (None, None))

    def test_with_no_start_time_the_hold_stands(self):
        made = datetime.now().replace(microsecond=0) - timedelta(minutes=10)
        zone = self._by_hand(self._zone(19.0), made)
        self.assertEqual(self._run(zone, since=None), (None, None))
        self.assertFalse(hl.hand_set_before(zone, "soon"))
        self.assertFalse(hl.hand_set_before(zone, 0))

    def test_the_list_of_held_rooms_leaves_out_what_the_boost_replaced(self):
        made = datetime.now().replace(microsecond=0) - timedelta(minutes=10)
        before, during = FakeZone(dev_id=1), FakeZone(dev_id=2)
        self._by_hand(before, made)
        self._by_hand(during, made)
        rooms = ((1, "Dining Room", PLAN), (2, "Hall", PLAN))
        devices = {1: before, 2: during}
        since = time.time() - 60
        self.assertEqual(set(hl.hand_holds(rooms, devices)), {"1", "2"})
        self.assertEqual(set(hl.hand_holds(rooms, devices, boost_since=since,
                                           boost_rooms={"Dining Room"})), {"2"},
                         "only a boost room loses its hold")
        self.assertEqual(set(hl.hand_holds(rooms, devices, boost_since=time.time() - 3600,
                                           boost_rooms={"Dining Room"})), {"1", "2"},
                         "made during the boost, so still held")


class TestWhatThePageIsTold(unittest.TestCase):

    def test_a_room_set_by_hand_reports_the_radiators_own_setting(self):
        # 25-Nov-2026: the Conservatory was at 22 by hand and the page said 20.
        out = plugin_mod.boost_outcome(
            [(2, "Conservatory"), (9, "Dining Room")],
            {"Conservatory": 20.0, "Dining Room": 22.0}, {"Conservatory": 11, "Dining Room": 12},
            TARGETS, "t", hand={"2": {"setpoint": 21.0, "until": 123.0}})
        self.assertEqual(out["2"]["requested"], 21.0)
        self.assertTrue(out["2"]["by_hand"])
        self.assertEqual(out["2"]["until"], 123.0)
        self.assertEqual(out["2"]["held"], "it was set by hand")
        self.assertEqual((out["9"]["by_hand"], out["9"]["held"], out["9"]["requested"]),
                         (False, "", 22.0))

    def test_a_blocked_room_names_the_real_reason(self):
        out = plugin_mod.boost_outcome(
            [(2, "Conservatory")], {"Conservatory": 12.0}, {"Conservatory": 23}, TARGETS, "t",
            blocked={"Conservatory": "its sliding door is shut"})
        self.assertEqual(out["2"]["held"], "its sliding door is shut")

    def test_the_start_of_a_restored_boost(self):
        expiry = datetime.fromtimestamp(10_000.0)
        f = plugin_mod._boost_started
        self.assertEqual(f(4321.5, expiry, 2), 4321.5)
        self.assertEqual(f(None, expiry, 2), expiry.timestamp() - 7200)
        self.assertEqual(f("rubbish", expiry, 1), expiry.timestamp() - 3600)
        self.assertEqual(f(True, expiry, 1), expiry.timestamp() - 3600)
        self.assertIsNone(f(None, None, 1))


if __name__ == "__main__":
    unittest.main()
