#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_25_review_fixes.py
# Description: 1.25.0 - the EvoHomeControl findings of the 17-Oct-2026 joint review with
#              RAMSES ESP: (3) a command RAMSES ESP refused is not recorded as sent;
#              (4) times survive the clocks going back; (5) a room still too warm after its
#              radiator was turned down alerts; (7) the timetable check says what it could
#              not check and tries again; (9) the alert quotes the target and setting used.
#              Finding 6 (the minimum off time) is in test_heating_logic.py.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-10-2026
# Version:     1.0

import json
import os
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from test_timed_overrides import FakeRamses, FakeZone, _Base, _indigo, hl, plugin_mod
from test_timetable_check import REAL, _PLUGIN, as_written

import overheat_monitor as om
import weather

LONDON = ZoneInfo("Europe/London")


class _Answer(dict):
    """What executeAction hands back from RAMSES ESP 1.18.0: something with .get()."""


class AnsweringRamses(FakeRamses):
    def __init__(self, answer, **kw):
        super().__init__(version="1.18.0", **kw)
        self.answer = answer

    def executeAction(self, action_id, deviceId=0, props=None, **kw):
        super().executeAction(action_id, deviceId, props, **kw)
        return _Answer(self.answer)


# ===========================================================================
class TestARefusedCommandIsNotRecorded(_Base):
# ===========================================================================

    def setUp(self):
        super().setUp()
        hl._REFUSED.clear()
        hl._REFUSAL_ANNOUNCED.clear()

    def test_an_accepted_command_is_recorded(self):
        self.ramses = AnsweringRamses({"accepted": True, "reason": ""})
        zone = FakeZone()
        self.assertTrue(hl.send_setpoint(zone, 19.0))
        self.assertEqual(hl._SENT[zone.id][0], 19.0)
        self.assertIsNone(hl.last_refusal(zone))

    def test_a_refused_command_is_not_recorded(self):
        self.ramses = AnsweringRamses({"accepted": False, "reason": "the gateway is offline"})
        zone = FakeZone()
        self.assertFalse(hl.send_setpoint(zone, 19.0))
        self.assertNotIn(zone.id, hl._SENT)
        self.assertEqual(hl.last_refusal(zone), "the gateway is offline")
        self.assertEqual(self.permanent, [], "a refusal must not fall back to a permanent send")

    def test_an_older_ramses_that_answers_nothing_counts_as_sent(self):
        zone = FakeZone()
        self.assertTrue(hl.send_setpoint(zone, 19.0))
        self.assertIn(zone.id, hl._SENT)

    def test_the_cycle_keeps_its_cache_and_says_so_once(self):
        self.ramses = AnsweringRamses({"accepted": False, "reason": "the gateway is offline"})
        zone = FakeZone(setpoint="16.0")
        lines, cache = [], {"Bedroom 2": 16.0}
        with mock.patch.object(hl, "_log", lambda msg, **k: lines.append(msg)):
            for _ in range(2):
                hl.update_radiator_setpoint(zone, 19.0, 11, "Bedroom 2", cache, {}, [], [])
        self.assertEqual(cache["Bedroom 2"], 16.0, "a refused send changed the cache")
        self.assertEqual(sum("not reaching Evohome" in l for l in lines), 1)
        self.ramses.answer = {"accepted": True, "reason": ""}
        with mock.patch.object(hl, "_log", lambda msg, **k: lines.append(msg)):
            hl.update_radiator_setpoint(zone, 19.0, 11, "Bedroom 2", cache, {}, [], [])
        self.assertEqual(cache["Bedroom 2"], 19.0)
        self.assertTrue(any("reaching Evohome again" in l for l in lines))


# ===========================================================================
class TestTheClocksGoingBack(unittest.TestCase):
# ===========================================================================

    def setUp(self):
        hl._SENT.clear()
        # The Ecowitt cases read local times in the process's own zone, as the plugin does
        # on the house Mac: pin it to the house's zone so the suite runs anywhere.
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/London"
        time.tzset()

    def tearDown(self):
        hl._SENT.clear()
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def test_a_change_after_our_send_in_the_repeated_hour_is_a_persons(self):
        """Our send at 01:55 BST, a change through Indigo at 01:10 GMT - fifteen minutes
        LATER, though its local time reads earlier. The review reproduced the hold lost."""
        dev = FakeZone()
        sent = datetime(2026, 10, 25, 1, 55, tzinfo=LONDON)                 # BST, fold 0
        changed = datetime(2026, 10, 25, 1, 10, tzinfo=LONDON, fold=1)      # GMT
        hl.note_sent(dev, 8.0, when=sent.replace(tzinfo=None), epoch=sent.timestamp())
        dev.states.update({"setpointSource": "indigo", "zoneMode": "temporary override",
                           "setpointHeat": "20.0",
                           "setpointChangedAt": "2026-10-25 01:10:00",
                           "setpointChangedAtEpoch": int(changed.timestamp())})
        self.assertTrue(hl._changed_through_indigo(dev, datetime(2026, 10, 25, 1, 10)))

    def test_without_the_epoch_the_local_times_are_compared_as_before(self):
        dev = FakeZone()
        hl.note_sent(dev, 8.0, when=datetime(2026, 10, 9, 7, 47, 18))
        dev.states.update({"setpointSource": "indigo", "setpointHeat": "20.0",
                           "setpointChangedAt": "2026-10-09 07:52:50"})
        self.assertTrue(hl._changed_through_indigo(dev, datetime(2026, 10, 9, 7, 52, 50)))

    def test_a_stale_ecowitt_reading_is_not_read_as_fresh(self):
        """A reading at 01:20 BST looked at 01:10 GMT is 50 minutes old, not -10."""
        dev = types.SimpleNamespace(states={"lastUpdate": "2026-10-25 01:20:00"})
        now = datetime(2026, 10, 25, 1, 10, tzinfo=LONDON, fold=1).timestamp()
        self.assertAlmostEqual(weather.WeatherData._ecowitt_age_secs(dev, now), 50 * 60)

    def test_an_ordinary_reading_age_is_unchanged(self):
        dev = types.SimpleNamespace(states={"lastUpdate": "2026-10-09 07:50:00"})
        now = datetime(2026, 10, 9, 8, 0, tzinfo=LONDON).timestamp()
        self.assertAlmostEqual(weather.WeatherData._ecowitt_age_secs(dev, now), 600)


# ===========================================================================
class TestOverheatAlerts(unittest.TestCase):
# ===========================================================================

    def setUp(self):
        self.mon = om.OverheatMonitor(os.path.join(tempfile.mkdtemp(), "h.json"))
        self.pushes = []
        self.mon._send_pushover = lambda t, m, priority=0: self.pushes.append((t, m, priority)) or True
        self.mon._send_email = lambda t, m: False

    def _overheat_for_hours(self, passive, reduced=14.0, target=20.0):
        room = "Living Room Front"
        self.mon.initialize_room(room)
        self.mon.history[room]["consecutive_cycles"] = self.mon.critical_duration_cycles
        self.mon.update_room(room, True, self.mon.persistent_overheat_temp + 0.1,
                             target + self.mon.persistent_overheat_temp + 0.1, target, 5.0,
                             is_passive=passive, reduced_temp=reduced)
        return room

    def test_a_room_still_too_warm_after_being_turned_down_alerts(self):
        """Passive warmth used to suppress this alert, so a stuck valve said nothing."""
        self._overheat_for_hours(passive=True)
        self.assertEqual(len(self.pushes), 1)
        title, message, priority = self.pushes[0]
        self.assertIn("stuck open", message)
        self.assertIn("Sun or other heat", message)
        self.assertEqual(priority, 0)

    def test_a_room_overheating_while_heated_alerts_at_high_priority(self):
        self._overheat_for_hours(passive=False)
        self.assertEqual(self.pushes[0][2], 1)

    def test_the_alert_quotes_the_setting_and_target_actually_used(self):
        """Finding 9: a boosted room judged against 22 and turned down to 16 must not be
        described against its plain 20 schedule and a recomputed 14."""
        self._overheat_for_hours(passive=False, reduced=16.0, target=22.0)
        message = self.pushes[0][1]
        self.assertIn("down to 16 degrees", message)
        self.assertIn("22 it should be", message)


# ===========================================================================
class TestTheTimetableCheckIsHonest(unittest.TestCase):
# ===========================================================================

    NOW = datetime(2026, 10, 5, 4, 5)

    def setUp(self):
        self._saved = dict(_indigo.devices)
        self.patch = mock.patch.object(plugin_mod, "schedules", REAL)
        self.patch.start()
        self.plans = plugin_mod._room_plans()
        for dev_id, room, hours in self.plans:
            _indigo.devices[dev_id] = types.SimpleNamespace(id=dev_id, name=room, states={
                "timetableData": json.dumps({str(d): [[m, sp] for m, sp in pts]
                                             for d, pts in as_written(hours).items()}),
                "timetableRead": (self.NOW - timedelta(minutes=50)).strftime("%Y-%m-%d %H:%M"),
            })
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs, p.store = {}, {}
        p._save_state = lambda: None
        p.logger = mock.MagicMock()
        p.overheat = types.SimpleNamespace(_send_pushover=lambda *a, **k: None)
        self.p = p

    def tearDown(self):
        self.patch.stop()
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def test_a_complete_check_says_so(self):
        with mock.patch(_PLUGIN + "._log"):
            self.assertTrue(self.p._check_timetable(self.NOW, manual=True))

    def test_a_room_with_no_timetable_is_named(self):
        dev_id, room, _h = self.plans[0]
        del _indigo.devices[dev_id].states["timetableData"]
        with mock.patch(_PLUGIN + "._log") as log:
            self.assertFalse(self.p._check_timetable(self.NOW, manual=True))
        text = " ".join(str(c.args[0]) for c in log.call_args_list)
        self.assertIn(room, text)
        self.assertIn("could not be checked", text)
        self.assertNotIn(f"all {len(self.plans)} rooms", text)

    def test_it_never_claims_a_match_in_no_rooms(self):
        for dev_id, _room, _h in self.plans:
            _indigo.devices[dev_id].states["timetableRead"] = "2026-09-01 03:15"
        with mock.patch(_PLUGIN + "._log") as log:
            self.assertFalse(self.p._check_timetable(self.NOW, manual=True))
        text = " ".join(str(c.args[0]) for c in log.call_args_list)
        self.assertNotIn("matches the plan", text)
        self.assertIn("No room could be checked", text)

    def test_an_incomplete_daily_check_is_tried_again_an_hour_later(self):
        calls = []
        self.p._check_timetable = lambda now, manual=False: calls.append(now) or False
        for hour, minute in ((4, 5), (4, 30), (5, 4)):
            self.p._maybe_check_timetable(datetime(2026, 10, 5, hour, minute))
        self.assertEqual(calls, [datetime(2026, 10, 5, 4, 5)], "retried within the hour")
        self.p._maybe_check_timetable(datetime(2026, 10, 5, 5, 6))
        self.assertEqual(calls[-1], datetime(2026, 10, 5, 5, 6))
        self.assertNotEqual(self.p.store.get("timetable_check_date"), "2026-10-05")

    def test_a_check_that_raises_is_tried_again_too(self):
        def boom(now, manual=False):
            raise RuntimeError("no devices")
        self.p._check_timetable = boom
        with mock.patch(_PLUGIN + "._log"):
            self.p._maybe_check_timetable(datetime(2026, 10, 5, 4, 5))
        self.assertNotEqual(self.p.store.get("timetable_check_date"), "2026-10-05")
        self.assertTrue(self.p.store.get("timetable_retry_after"))


if __name__ == "__main__":
    unittest.main()
