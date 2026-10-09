#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_19_indigo_hand.py
# Description: 1.19.0 - a setpoint a person changes THROUGH Indigo (the client, the Home
#              app, a dashboard) is held like one changed by hand, instead of being put
#              back by the next cycle. RAMSES ESP tags both that and this plugin's own
#              sends "indigo", so the plugin tells them apart by what it last sent.
# Author:      CliveS & Claude Opus 5.5
# Date:        09-10-2026
# Version:     1.0

import json
import os
import tempfile
import types
import unittest
from datetime import datetime, timedelta

from test_timed_overrides import FakeZone, _Base, _indigo, hl, plugin_mod

_STAMP = "%Y-%m-%d %H:%M:%S"
PLAN = [16] * 7 + [20] * 15 + [16] * 2


def _through_indigo(dev, changed, setpoint="20.0", mode="permanent override"):
    dev.states.update({"setpointSource": "indigo", "zoneMode": mode,
                       "setpointHeat": setpoint, "setpointChangedAt": changed.strftime(_STAMP)})
    return dev


class TestTellingThemApart(unittest.TestCase):

    def setUp(self):
        hl._MANUAL_ANNOUNCED.clear()
        hl._SENT.clear()

    def tearDown(self):
        hl._SENT.clear()

    def test_a_person_changing_it_after_us_is_held_until_the_plan_moves(self):
        dev = FakeZone()
        hl.note_sent(dev, 8.0, when=datetime(2026, 10, 9, 7, 47, 18))
        _through_indigo(dev, datetime(2026, 10, 9, 7, 52, 50))
        end = hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 9, 8, 0))
        self.assertEqual(end, datetime(2026, 10, 9, 22, 0))

    def test_a_permanent_setting_through_indigo_is_not_held_for_good(self):
        # RAMSES sends Indigo's own thermostat command as permanent; nobody chose that.
        dev = FakeZone()
        hl.note_sent(dev, 8.0, when=datetime(2026, 10, 9, 21, 0))
        _through_indigo(dev, datetime(2026, 10, 9, 22, 30))
        self.assertEqual(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 9, 23, 0)),
                         datetime(2026, 10, 10, 0, 0))
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 10, 0, 0)))

    def test_our_own_send_coming_back_is_not_a_hold(self):
        dev = FakeZone()
        hl.note_sent(dev, 8.0, when=datetime(2026, 10, 9, 7, 57, 21))
        _through_indigo(dev, datetime(2026, 10, 9, 7, 57, 25), setpoint="8.0",
                        mode="temporary override")
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 9, 8, 0)))

    def test_a_change_older_than_our_last_send_is_not_a_hold(self):
        # Our send has not been confirmed yet; the zone still shows the earlier value.
        dev = FakeZone()
        hl.note_sent(dev, 8.0, when=datetime(2026, 10, 9, 7, 57, 21))
        _through_indigo(dev, datetime(2026, 10, 9, 7, 10, 0), setpoint="12.0")
        self.assertIsNone(hl.manual_hold_until(dev, [8] * 24, now=datetime(2026, 10, 9, 7, 58)))

    def test_with_nothing_on_record_the_change_is_taken_as_ours(self):
        dev = _through_indigo(FakeZone(), datetime(2026, 10, 9, 7, 52, 50))
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 9, 8, 0)))

    def test_an_unreadable_setpoint_is_not_a_hold(self):
        dev = FakeZone()
        hl.note_sent(dev, 8.0, when=datetime(2026, 10, 9, 7, 47))
        _through_indigo(dev, datetime(2026, 10, 9, 7, 52), setpoint="")
        self.assertIsNone(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 10, 9, 8, 0)))

    def test_a_hand_change_on_the_controller_still_holds_for_good(self):
        dev = FakeZone()
        dev.states.update({"setpointSource": "manual", "zoneMode": "permanent override",
                           "setpointHeat": "20.0",
                           "setpointChangedAt": datetime(2026, 10, 9, 7, 52).strftime(_STAMP)})
        self.assertEqual(hl.manual_hold_until(dev, PLAN, now=datetime(2026, 12, 1)),
                         "permanent")


class TestTheRecord(_Base):

    def test_send_setpoint_records_what_it_sent(self):
        zone = FakeZone()
        before = datetime.now()
        hl.send_setpoint(zone, 17.5)
        value, when = hl._SENT[zone.id]
        self.assertEqual(value, 17.5)
        self.assertGreaterEqual(when, before)

    def test_the_record_survives_a_round_trip_and_junk_is_skipped(self):
        hl.note_sent(FakeZone(dev_id=11), 8.0, when=datetime(2026, 10, 9, 7, 47, 18))
        snap = json.loads(json.dumps(hl.sent_snapshot()))
        hl._SENT.clear()
        snap["bad"] = ["x"]
        snap["22"] = ["nine", "2026-10-09T07:00:00"]
        hl.restore_sent(snap)
        hl.restore_sent("not a dict")
        self.assertEqual(hl._SENT, {11: (8.0, datetime(2026, 10, 9, 7, 47, 18))})

    def test_the_plugin_saves_and_reloads_it_with_the_setpoint_cache(self):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.data_dir = tempfile.mkdtemp()
        p.store = {"last_setpoints": {}, "last_messages": {}}
        hl.note_sent(FakeZone(dev_id=11), 8.0, when=datetime(2026, 10, 9, 7, 47, 18))
        p._save_setpoint_cache()
        hl._SENT.clear()
        p._load_state()
        self.assertEqual(hl._SENT, {11: (8.0, datetime(2026, 10, 9, 7, 47, 18))})
        self.assertTrue(os.path.exists(os.path.join(p.data_dir, "setpoint_cache.json")))


class TestTheCycleLeavesItAlone(_Base):

    def setUp(self):
        super().setUp()
        hl._MANUAL_ANNOUNCED.clear()
        self.lines = []
        self._saved_log = hl._log
        hl._log = lambda msg, **k: self.lines.append(msg)

    def tearDown(self):
        hl._log = self._saved_log
        super().tearDown()

    def _run(self, zone):
        _indigo.devices[zone.id] = zone
        hl.process_room_temperature(
            room_name="Bedroom 2", room_schedule=[8] * 24, ha_device_id=zone.id,
            current_hour=12, current_minute=5, current_outdoor_temp=5.0,
            last_setpoints={}, last_messages={}, log_buffer=[], changes_buffer=[],
            overheat_monitor=None,
        )

    def test_a_room_turned_up_through_indigo_is_not_put_back(self):
        zone = FakeZone(ends_in=None)
        hl.note_sent(zone, 8.0, when=datetime.now() - timedelta(minutes=6))
        _through_indigo(zone, datetime.now() - timedelta(minutes=1))
        self._run(zone)
        self.assertEqual(self.ramses.calls, [])
        self.assertEqual(self.permanent, [])
        self.assertTrue(any("set to 20 degrees by hand through Indigo" in l for l in self.lines))

    def test_our_own_setting_is_still_renewed(self):
        zone = FakeZone(setpoint="8.0", ends_in=10)
        hl.note_sent(zone, 8.0, when=datetime.now() - timedelta(minutes=110))
        _through_indigo(zone, datetime.now() - timedelta(minutes=110), setpoint="8.0",
                        mode="temporary override")
        self._run(zone)
        self.assertEqual(len(self.ramses.calls), 1)


class TestSummerToo(_Base):

    def test_a_room_turned_up_through_indigo_is_left_alone_in_summer(self):
        self.ramses.pluginVersion = "1.15.0"
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs = {"enSuiteDryingTemp": "20"}
        p.store = {"en_suite_drying_active": False, "last_setpoints": {}, "last_messages": {}}
        p._save_state = lambda: None
        saved = []
        p._save_setpoint_cache = lambda: saved.append(True)
        p._summer_window = lambda: (6, 1, 10, 14)
        for dev_id in hl.ALL_RADIATOR_IDS:
            _indigo.devices[dev_id] = FakeZone(dev_id=dev_id, setpoint="8.0")
        _indigo.devices[hl.DEV_EN_SUITE_FLOOR_HEAT_ID] = types.SimpleNamespace(onState=False)
        room = _indigo.devices[hl.DEV_BEDROOM_3_ID]
        hl.note_sent(room, 8.0, when=datetime.now() - timedelta(minutes=10))
        _through_indigo(room, datetime.now() - timedelta(minutes=2), setpoint="19.0")
        p._apply_summer_off()
        self.assertNotIn(hl.DEV_BEDROOM_3_ID, [c[1] for c in self.ramses.calls])
        # What was sent is saved, because the heating cycle that normally does it is off.
        self.assertEqual(saved, [True])


if __name__ == "__main__":
    unittest.main()
