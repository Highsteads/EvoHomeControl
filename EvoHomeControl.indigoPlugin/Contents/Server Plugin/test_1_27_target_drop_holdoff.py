#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_27_target_drop_holdoff.py
# Description: No overheat judgement for a hold-off after a room's target steps down, and
#              alert wording that is true at the moment it is sent (1.27.0).
# Author:      CliveS & Claude Fable 5.2
# Date:        10-11-2026
# Version:     1.0

import os
import re
import sys
import tempfile
import types
import unittest
from datetime import datetime
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
if "indigo" not in sys.modules:       # no Indigo runtime needed
    _ind = types.ModuleType("indigo")
    _ind.server = types.SimpleNamespace(log=lambda *a, **k: None,
                                        getPlugin=lambda *a, **k: None,
                                        sendEmailTo=lambda *a, **k: None)
    sys.modules["indigo"] = _ind

import overheat_monitor as om  # noqa: E402

ROOM = "Dining Room"
# 8pm on 30 October 2026, local time: the evening the audit quoted.
EIGHT_PM = datetime(2026, 10, 30, 20, 0, 0).timestamp()


class _Base(unittest.TestCase):
    ALERTS_ON = True

    def setUp(self):
        self.mon = om.OverheatMonitor(os.path.join(tempfile.mkdtemp(), "h.json"))
        self.sent = []          # (title, message, priority) for Pushover
        self.events = []
        self.logged = []
        self.mon._send_pushover = (
            lambda t, m, priority=0: self.sent.append((t, m, priority)) or True)
        self.mon._send_email = lambda t, m: True
        self.mon.event_callback = self.events.append
        self.now = EIGHT_PM
        for patcher in (
            mock.patch.object(om, "ALERT_WHEN_RADIATOR_DOWN", self.ALERTS_ON),
            mock.patch.object(om.time, "time", lambda: self.now),
            mock.patch.object(om, "_slog", lambda m, level="INFO": self.logged.append(m)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _cycle(self, temp, target, minutes=5, passive=False, reduced=12.0, outdoor=5.0,
               off_cycles=None):
        """One heating cycle `minutes` after the last, the way heating_logic calls it."""
        self.now += minutes * 60
        over = temp - target
        hot = over > 0.5
        if off_cycles is not None:
            self.mon.initialize_room(ROOM)
            self.mon.history[ROOM]["off_since_cycle"] = off_cycles
        self.mon.update_room(ROOM, hot, over if hot else 0.0, temp, target, outdoor,
                             is_passive=passive, reduced_temp=reduced if hot else None)

    def _evening_set_back(self):
        """Heated to 21 all afternoon, then the 8pm plan drops the target to 15."""
        self._cycle(21.0, 21.0)
        self._cycle(21.0, 15.0)


class TestHoldOffAfterAStepDown(_Base):

    def test_no_alert_minutes_after_the_evening_set_back(self):
        """The audit's case: six degrees 'too warm' one cycle after the target fell."""
        self._evening_set_back()
        self._cycle(20.9, 15.0)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.events, [])

    def test_the_same_overheat_with_no_step_down_alerts_at_once(self):
        """Control: the hold-off is the only thing keeping the test above quiet."""
        self._cycle(21.0, 15.0)
        self._cycle(21.0, 15.0)
        self.assertEqual(len(self.sent), 1)

    def test_it_is_judged_once_the_hold_off_has_passed(self):
        self._evening_set_back()
        for _ in range(17):                       # 85 minutes more: still held
            self._cycle(21.2, 15.0)
        self.assertEqual(self.sent, [])
        self._cycle(21.2, 15.0)                   # 90 minutes after the drop
        self.assertEqual(len(self.sent), 1)

    def test_the_default_hold_off_is_90_minutes(self):
        self.assertEqual(om.TARGET_DROP_HOLDOFF_MINS, 90)
        self.assertEqual(self.mon.target_drop_holdoff_mins, 90)

    def test_a_hold_off_of_nought_switches_it_off(self):
        self.mon.target_drop_holdoff_mins = 0
        self._evening_set_back()
        self.assertEqual(len(self.sent), 1)

    def test_a_shorter_hold_off_is_honoured(self):
        self.mon.target_drop_holdoff_mins = 30
        self._evening_set_back()
        for _ in range(5):
            self._cycle(21.0, 15.0)
        self.assertEqual(self.sent, [])
        self._cycle(21.0, 15.0)
        self.assertEqual(len(self.sent), 1)

    def test_a_drop_of_under_a_degree_is_not_a_step_down(self):
        self._cycle(21.5, 15.5)
        self.sent.clear()
        self.mon.history[ROOM]["alert_sent"] = False
        self._cycle(21.5, 15.0)
        self.assertEqual(len(self.sent), 1)

    def test_a_target_raised_again_ends_the_hold_off(self):
        """A boost 20 minutes after the set-back: over the HIGHER target is judged."""
        self._evening_set_back()
        self._cycle(21.0, 15.0)
        self._cycle(29.0, 22.0)
        self.assertEqual(len(self.sent), 1)

    def test_the_status_menu_still_lists_the_room_while_held(self):
        self._evening_set_back()
        self.assertIn(ROOM, self.mon.get_overheating_rooms())

    def test_held_time_does_not_count_towards_too_warm_for_six_hours(self):
        """4.5 over is only an alert after six hours of it. 90 held minutes are not it."""
        six_hours = self.mon.critical_duration_cycles
        self._cycle(19.5, 19.5)
        self._cycle(19.5, 15.0)                   # the step down, cycle 1 of the hold
        for _ in range(six_hours - 1):            # six hours since the drop in all
            self._cycle(19.5, 15.0)
        self.assertEqual(self.sent, [])
        for _ in range(18):                       # the 90 minutes that were held
            self._cycle(19.5, 15.0)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("too warm for about 6 hours", self.sent[0][1])

    def test_hours_too_warm_before_the_step_down_still_count(self):
        """Paused, not cleared: 5 hours at 4.5 over, a step down, then one more hour."""
        for _ in range(60):
            self._cycle(21.5, 17.0)
        self.assertEqual(self.sent, [])
        for _ in range(18):                       # 17 -> 15, and 90 held minutes
            self._cycle(21.5, 15.0)
        self.assertEqual(self.sent, [])
        self.mon.critical_overheat_temp = 99.0    # leave only the six-hour rule
        for _ in range(11):
            self._cycle(21.5, 15.0)
        self.assertEqual(self.sent, [])
        self._cycle(21.5, 15.0)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("too warm for about 6 hours", self.sent[0][1])

    def test_the_worst_figure_leaves_out_the_hold_off(self):
        self._evening_set_back()
        self.assertEqual(self.mon.history[ROOM]["max_overheat"], 0.0)

    def test_a_drop_time_in_the_future_holds_nothing_off(self):
        self._cycle(21.0, 15.0)
        self.mon.history[ROOM]["alert_sent"] = False
        self.sent.clear()
        self.mon.history[ROOM]["target_dropped_at"] = self.now + 86400
        self._cycle(21.0, 15.0)
        self.assertEqual(len(self.sent), 1)

    def test_a_saved_history_without_the_new_keys_still_works(self):
        """A file written by 1.26.0 has none of the 1.27.0 keys."""
        self.mon.history[ROOM] = {
            "consecutive_cycles": self.mon.critical_duration_cycles, "max_overheat": 4.5,
            "alert_sent": False, "alert_type": None, "alert_timestamp": None,
            "last_update": None, "stable_cycles": 0, "all_clear_sent": True,
            "off_since_cycle": 70, "temp_history": [], "is_coasting": False,
            "target_temp": 15.0,
        }
        self._cycle(19.5, 15.0, passive=True)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("too warm for about 6 hours", self.sent[0][1])


class TestTheSwitchOffIsKept(_Base):
    """1.25.9: with the alerts off nothing is ever sent, hold-off or not."""
    ALERTS_ON = False

    def test_the_shipped_default_is_still_off(self):
        self.assertIs(om.OverheatMonitor.__module__, om.__name__)
        with open(os.path.join(_HERE, "overheat_monitor.py"), encoding="utf-8") as fh:
            self.assertRegex(fh.read(), r"(?m)^ALERT_WHEN_RADIATOR_DOWN = False$")

    def test_nothing_is_sent_during_or_after_the_hold_off(self):
        self._evening_set_back()
        for _ in range(30):
            self._cycle(21.0, 15.0)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.events, [])

    def test_the_cooling_log_line_waits_for_the_hold_off_too(self):
        self._evening_set_back()
        self.assertEqual([m for m in self.logged if "no alert sent" in m], [])
        for _ in range(18):
            self._cycle(21.0, 15.0)
        self.assertEqual(len([m for m in self.logged if "no alert sent" in m]), 1)


class TestWordingIsTrueWhenSent(_Base):

    def _alert(self, **kw):
        self._cycle(21.0, 15.0, **kw)
        self.assertEqual(len(self.sent), 1)
        return self.sent[0]

    def test_for_a_while_is_gone(self):
        _title, message, _p = self._alert(passive=True, off_cycles=3)
        self.assertNotIn("for a while", message)

    def test_a_radiator_only_just_turned_down_is_said_so(self):
        _title, message, _p = self._alert(off_cycles=1)
        self.assertIn("has just turned its radiator down to 12 degrees.", message)

    def test_how_long_it_has_been_turned_down_is_the_real_figure(self):
        _title, message, _p = self._alert(passive=True, off_cycles=9)
        self.assertIn("has had its radiator turned down for about 45 minutes, now to "
                      "12 degrees, and the room is still too warm.", message)

    def test_a_recent_step_down_is_named_with_its_time(self):
        self._evening_set_back()                  # drop seen at 8:10pm
        for _ in range(18):
            self._cycle(21.0, 15.0, off_cycles=19)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Its target came down from 21 to 15 degrees at 8:10pm, so some of "
                      "this is the room cooling from its earlier setting.", self.sent[0][1])

    def test_no_step_down_no_sentence_about_one(self):
        _title, message, _p = self._alert()
        self.assertNotIn("came down", message)

    def test_one_degree_outside_is_singular(self):
        _title, message, _p = self._alert(outdoor=1.0)
        self.assertIn("It is 1 degree outside.", message)
        self.assertIsNone(re.search(r"(?<![\d.])1 degrees", message), message)

    def test_the_title_carries_the_answer(self):
        title, _message, _p = self._alert()
        self.assertEqual(title, "The Dining Room is 6 degrees too warm")

    def test_plain_ascii_sentences(self):
        self._evening_set_back()
        for _ in range(18):
            self._cycle(21.25, 15.0, passive=True, off_cycles=19, outdoor=-1.0)
        title, message, _p = self.sent[0]
        for text in (title, message):
            self.assertTrue(text.isascii(), text)
            self.assertIsNone(re.search(r"[|=\[\]{}]", text), text)
            self.assertNotIn(".0 ", text)
        self.assertTrue(message.endswith("."))
        self.assertLessEqual(len(message), 1024)
        self.assertIn("It is -1 degree outside.", message)

    def test_an_all_clear_days_later_says_days(self):
        self._alert()
        self.mon.history[ROOM]["alert_timestamp"] = "05-11-2026 22:00:21"
        with mock.patch.object(om, "dt") as fake:
            fake.now.return_value = datetime(2026, 11, 9, 10, 52)
            fake.strptime = datetime.strptime
            self.mon.send_all_clear(ROOM)
        self.assertIn("The alert went out about 4 days ago.", self.sent[-1][1])
        self.assertNotIn("85 hours", self.sent[-1][1])


class TestHelpers(unittest.TestCase):

    def test_the_setting_is_coerced_and_guarded(self):
        for raw, want in (("90", 90), (" 45 ", 45), (60, 60), ("30.0", 30), ("0", 0),
                          ("", 90), (None, 90), ("ninety", 90), (True, 90), (False, 90),
                          ("-5", 0), ("99999", 720), ("nan", 90), ("inf", 90)):
            with self.subTest(raw=raw):
                self.assertEqual(om.coerce_holdoff_mins(raw), want)

    def test_a_bad_value_on_the_monitor_falls_back_rather_than_raising(self):
        mon = om.OverheatMonitor(os.path.join(tempfile.mkdtemp(), "h.json"))
        mon.target_drop_holdoff_mins = ""
        mon.initialize_room(ROOM)
        mon.history[ROOM]["target_dropped_at"] = 1000.0
        self.assertTrue(mon.in_target_drop_holdoff(ROOM, now=1000.0 + 89 * 60))
        self.assertFalse(mon.in_target_drop_holdoff(ROOM, now=1000.0 + 90 * 60))

    def test_times_as_a_person_says_them(self):
        for (h, m), want in (((20, 0), "8pm"), ((20, 2), "8:02pm"), ((11, 41), "11:41am"),
                             ((0, 5), "12:05am"), ((12, 0), "12pm")):
            with self.subTest(want=want):
                self.assertEqual(
                    om._clock_text(datetime(2026, 11, 10, h, m).timestamp()), want)

    def test_durations_as_a_person_says_them(self):
        self.assertEqual(om._duration_text(0.25), "about 15 minutes")
        self.assertEqual(om._duration_text(1.0), "about an hour")
        self.assertEqual(om._duration_text(6.0), "about 6 hours")
        self.assertEqual(om._duration_text(39.0), "about 2 days")
        self.assertEqual(om._duration_text(85.0), "about 4 days")

    def test_degrees(self):
        self.assertEqual(om._degrees(1.0), "1 degree")
        self.assertEqual(om._degrees(-1.0), "-1 degree")
        self.assertEqual(om._degrees(12.0), "12 degrees")
        self.assertEqual(om._degrees(12.5), "12.5 degrees")
        self.assertEqual(om._degrees(-0.04), "0 degrees")


class TestTheSettingIsWired(unittest.TestCase):

    def test_the_configure_dialog_has_the_field_defaulting_to_90(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(_HERE, "PluginConfig.xml")).getroot()
        field = [f for f in root.iter("Field") if f.get("id") == "overheatHoldOffMins"]
        self.assertEqual(len(field), 1)
        self.assertEqual(field[0].get("defaultValue"), "90")

    def test_plugin_reads_it_at_start_and_on_save(self):
        with open(os.path.join(_HERE, "plugin.py"), encoding="utf-8") as fh:
            code = "\n".join(line for line in fh.read().splitlines()
                             if not line.lstrip().startswith("#"))
        self.assertIn("self._overheat_holdoff_mins(self.pluginPrefs)", code)
        self.assertIn("self._overheat_holdoff_mins(values_dict)", code)


if __name__ == "__main__":
    unittest.main()
