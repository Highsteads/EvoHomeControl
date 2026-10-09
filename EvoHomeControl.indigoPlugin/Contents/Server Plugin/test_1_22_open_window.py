#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_22_open_window.py
# Description: 1.22.0 - an open window or outside door beats everything. CliveS,
#              09-10-2026: "Whenever a window opens then that overrides heating". The
#              En Suite sat at 25 degC, set by hand, with its window open, because the
#              hand hold returned before the window was read. Also: the Bathroom's
#              window id pointed at a device that no longer existed.
# Author:      CliveS & Claude Opus 5.5
# Date:        09-10-2026
# Version:     1.0

import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

import plugin as plugin_mod
from test_fixes_1_12 import FakeDevice, _ago, _indigo, hl

_STAMP = "%Y-%m-%d %H:%M:%S"
ROOM_ID, WIN_ID, DOOR_ID = hl.DEV_BEDROOM_2_ID, hl.DEV_BEDROOM_2_WINDOW_ID, hl.DEV_UTILITY_DOOR_ID


class _Rooms(unittest.TestCase):

    def setUp(self):
        self._saved_devices = dict(_indigo.devices)
        self._saved_thermo  = _indigo.thermostat
        self._saved_device  = _indigo.device
        self.written, self.modes, self.lines = [], [], []
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda d, value=None, **k: self.written.append((d.id, value)),
            setHvacMode=lambda d, value=None, **k: self.modes.append((d.id, value)))
        _indigo.device = types.SimpleNamespace(turnOn=lambda *a, **k: None,
                                               turnOff=lambda *a, **k: None)
        self._saved_log = hl._log
        hl._log = lambda msg, **k: self.lines.append(msg)
        hl._MANUAL_ANNOUNCED.clear()
        hl._WINDOW_OVERRIDE_ANNOUNCED.clear()
        hl._SENT.clear()
        hl._FLOOR["off_sent_at"] = 0.0
        hl.set_override_minutes(0)

    def tearDown(self):
        hl._log = self._saved_log
        _indigo.thermostat = self._saved_thermo
        _indigo.device     = self._saved_device
        _indigo.devices.clear()
        _indigo.devices.update(self._saved_devices)
        hl._SENT.clear()

    def _zone(self, dev_id=ROOM_ID, **states):
        base = {"temperatureInput1": "19.0", "setpointHeat": "20.0",
                "zoneMode": "temporary override", "lastSeen": _ago(1)}
        base.update(states)
        dev = FakeDevice(base)
        dev.id, dev.name = dev_id, f"Zone {dev_id}"
        _indigo.devices[dev_id] = dev
        return dev

    def _contact(self, dev_id, open_):
        _indigo.devices[dev_id] = FakeDevice({"contact": not open_})

    def _run(self, room="Bedroom 2", dev_id=ROOM_ID, windows=(WIN_ID,), doors=(),
             special=None, outdoor=5.0, away=False, **kw):
        last = {}
        hl.process_room_temperature(
            room_name=room, room_schedule=[20] * 24, window_devices=list(windows),
            door_devices=list(doors), special_rules=special, ha_device_id=dev_id,
            current_hour=8, current_minute=5, current_outdoor_temp=outdoor, is_away=away,
            last_setpoints={}, last_messages=last, log_buffer=[], changes_buffer=[],
            overheat_monitor=None, **kw)
        return last


class TestTheWindowWins(_Rooms):

    def test_a_room_set_by_hand_goes_down_when_its_window_opens(self):
        self._zone(setpointHeat="25.0", zoneMode="permanent override", setpointSource="manual",
                   setpointChangedAt=(datetime.now() - timedelta(minutes=30)).strftime(_STAMP))
        self._contact(WIN_ID, True)
        msgs = self._run()
        self.assertEqual(self.written, [(ROOM_ID, hl.RADIATORS_OFF_TEMP)])
        self.assertEqual(msgs["Bedroom 2"], 1)

    def test_it_says_so_once(self):
        self._zone(setpointHeat="25.0", zoneMode="permanent override", setpointSource="manual",
                   setpointChangedAt=(datetime.now() - timedelta(minutes=30)).strftime(_STAMP))
        self._contact(WIN_ID, True)
        self._run()
        self._run()
        said = [line for line in self.lines if "gives way" in line]
        self.assertEqual(len(said), 1)
        self.assertIn("Bedroom 2: a window is open", said[0])

    def test_the_same_room_with_the_window_shut_is_left_alone(self):
        self._zone(setpointHeat="25.0", zoneMode="permanent override", setpointSource="manual",
                   setpointChangedAt=(datetime.now() - timedelta(minutes=30)).strftime(_STAMP))
        self._contact(WIN_ID, False)
        self._run()
        self.assertEqual(self.written, [])

    def test_a_missing_reading_does_not_keep_the_heat_on(self):
        self._zone(temperatureInput1="")
        self._contact(WIN_ID, True)
        self._run()
        self.assertEqual(self.written, [(ROOM_ID, hl.RADIATORS_OFF_TEMP)])

    def test_a_stale_reading_does_not_keep_the_heat_on(self):
        self._zone(lastSeen=_ago(hl.ZONE_STALE_MINUTES + 30), temperatureSeen=_ago(hl.ZONE_STALE_MINUTES + 30))
        self._contact(WIN_ID, True)
        self._run()
        self.assertEqual(self.written, [(ROOM_ID, hl.RADIATORS_OFF_TEMP)])

    def test_an_outside_door_counts_too(self):
        self._zone(dev_id=hl.DEV_UTILITY_ROOM_ID)
        self._contact(hl.DEV_UTILITY_WINDOW_ID, False)
        self._contact(DOOR_ID, True)
        msgs = self._run(room="Utility Room", dev_id=hl.DEV_UTILITY_ROOM_ID,
                         windows=(hl.DEV_UTILITY_WINDOW_ID,), doors=(DOOR_ID,))
        self.assertEqual(self.written, [(hl.DEV_UTILITY_ROOM_ID, hl.RADIATORS_OFF_TEMP)])
        self.assertEqual(msgs["Utility Room"], 3)


class TestRoomRules(_Rooms):

    def test_the_conservatory_sliding_door_rule_no_longer_beats_a_garden_window(self):
        self._zone(dev_id=hl.DEV_CONSERVATORY_ID)
        self._contact(hl.DEV_GARDEN_WINDOW_L_ID, True)
        self._contact(hl.DEV_GARDEN_WINDOW_R_ID, False)
        self._contact(hl.DEV_GARDEN_DOOR_ID, False)
        _indigo.devices[hl.DEV_SLIDE_DOOR_ID] = FakeDevice({"contact": "true"})   # shut
        self._run(room="Conservatory", dev_id=hl.DEV_CONSERVATORY_ID,
                  windows=(hl.DEV_GARDEN_WINDOW_L_ID, hl.DEV_GARDEN_WINDOW_R_ID),
                  doors=(hl.DEV_GARDEN_DOOR_ID,), special=hl.conservatory_special_rules)
        self.assertEqual(self.written, [(hl.DEV_CONSERVATORY_ID, hl.RADIATORS_OFF_TEMP)])

    def _dining(self, **kw):
        self._zone(dev_id=hl.DEV_DINING_ROOM_ID, setpointHeat="20.0")
        self._contact(hl.DEV_GARDEN_WINDOW_L_ID, False)
        self._contact(hl.DEV_GARDEN_WINDOW_R_ID, False)
        self._contact(hl.DEV_GARDEN_DOOR_ID, True)
        return self._run(room="Dining Room", dev_id=hl.DEV_DINING_ROOM_ID,
                         windows=(hl.DEV_GARDEN_WINDOW_L_ID, hl.DEV_GARDEN_WINDOW_R_ID),
                         doors=(hl.DEV_GARDEN_DOOR_ID,), special=hl.dining_room_special_rules, **kw)

    def test_the_dining_room_still_turns_down_to_sixteen(self):
        self._dining()
        self.assertEqual(self.written, [(hl.DEV_DINING_ROOM_ID, 16.0)])

    def test_the_dining_room_goes_to_eight_with_away_on(self):
        self._dining(away=True)
        self.assertEqual(self.written, [(hl.DEV_DINING_ROOM_ID, hl.RADIATORS_OFF_TEMP)])

    def test_the_en_suite_window_ends_the_morning_and_the_floor(self):
        self._zone(dev_id=hl.DEV_EN_SUITE_ID, setpointHeat="20.0")
        self._contact(hl.DEV_EN_SUITE_WINDOW_ID, True)
        switch = FakeDevice({"onOffState": True})
        switch.id = hl.DEV_EN_SUITE_FLOOR_HEAT_ID
        therm = FakeDevice({"hvacOperationModeIsHeat": True, "hvacOperationModeIsOff": False,
                            "setpointHeat": 14.0})
        therm.id = hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID
        _indigo.devices[switch.id] = switch
        _indigo.devices[therm.id] = therm
        store = {"en_suite_morning_active": True}
        self._run(room="En Suite", dev_id=hl.DEV_EN_SUITE_ID, windows=(hl.DEV_EN_SUITE_WINDOW_ID,),
                  special=lambda *a, **k: hl.en_suite_special_rules(*a, store=store, **k),
                  floor_heat_device=hl.DEV_EN_SUITE_FLOOR_THERMOSTAT_ID,
                  floor_heat_restore_enabled=True)
        self.assertEqual(self.written, [(hl.DEV_EN_SUITE_ID, hl.RADIATORS_OFF_TEMP)])
        self.assertFalse(store["en_suite_morning_active"])
        self.assertEqual(store["en_suite_morning_cancelled_reason"], "window_open")
        self.assertEqual(self.modes, [(therm.id, _indigo.kHvacMode.Off)])


class TestEveryContactIsChecked(_Rooms):

    def test_a_missing_contact_is_reported_at_startup(self):
        for dev_id, _ in hl.WATCHED_CONTACTS:
            _indigo.devices[dev_id] = FakeDevice({"contact": True})
        del _indigo.devices[hl.DEV_BATHROOM_WINDOW_ID]
        logged = []
        with mock.patch.object(_indigo.server, "log", lambda msg, **k: logged.append(msg), create=True):
            hl.validate_configuration()
        self.assertTrue(any("Bathroom window" in m and "Missing" in m for m in logged), logged)

    def test_every_room_contact_is_watched(self):
        watched = {dev_id for dev_id, _ in hl.WATCHED_CONTACTS}
        src = open(plugin_mod.__file__, encoding="utf-8").read()
        import re
        lists = re.findall(r"(?:window|door)_devices\s*=\s*\[([^\]]*)\]", src)
        used = {n for body in lists for n in re.findall(r"DEV_\w+_ID", body)}
        self.assertTrue(used)
        for name in used:
            self.assertIn(getattr(hl, name), watched, name)


class TestAChangeGetsACycleAtOnce(unittest.TestCase):

    def setUp(self):
        self._saved = dict(_indigo.devices)
        for dev_id, _ in hl.WATCHED_CONTACTS:
            _indigo.devices[dev_id] = FakeDevice({"contact": True})
        self.p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        self.p.store = {"cycle_requests": 0}

    def tearDown(self):
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def test_first_look_only_records(self):
        self.p._check_contacts_changed()
        self.assertEqual(self.p.store["cycle_requests"], 0)

    def test_an_opening_and_a_shutting_each_ask_for_a_cycle(self):
        self.p._check_contacts_changed()
        _indigo.devices[hl.DEV_BEDROOM_1_WINDOW_ID].states["contact"] = False
        self.p._check_contacts_changed()
        self.p._check_contacts_changed()
        self.assertEqual(self.p.store["cycle_requests"], 1)
        _indigo.devices[hl.DEV_BEDROOM_1_WINDOW_ID].states["contact"] = True
        self.p._check_contacts_changed()
        self.assertEqual(self.p.store["cycle_requests"], 2)


if __name__ == "__main__":
    unittest.main()
