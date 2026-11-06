#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_25_9_quiet_overheat.py
# Description: A room that is too warm with its radiator already turned down sends
#              no Pushover, email, event or all-clear (CliveS, 06-11-2026).
# Author:      CliveS & Claude Sonnet 5.5
# Date:        06-11-2026
# Version:     1.0

import os
import sys
import tempfile
import types
import unittest

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


class TestQuietOverheat(unittest.TestCase):
    def setUp(self):
        self.mon = om.OverheatMonitor(os.path.join(tempfile.mkdtemp(), "h.json"))
        self.sent = []
        self.events = []
        self.mon._send_pushover = lambda t, m, priority=0: self.sent.append(t) or True
        self.mon._send_email = lambda t, m: self.sent.append(t) or True
        self.mon.event_callback = self.events.append

    def _hot(self, amount, cycles=1, passive=False):
        for _ in range(cycles):
            self.mon.update_room("Conservatory", True, amount, 18 + amount, 18.0, 8.0,
                                 is_passive=passive, reduced_temp=12.0)

    def test_the_default_is_quiet(self):
        self.assertFalse(om.ALERT_WHEN_RADIATOR_DOWN)

    def test_a_sudden_big_overheat_sends_nothing(self):
        self._hot(7.0)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.events, [])

    def test_a_long_persistent_overheat_sends_nothing(self):
        self._hot(4.5, cycles=self.mon.critical_duration_cycles + 2, passive=True)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.events, [])

    def test_no_all_clear_follows(self):
        self._hot(7.0)
        for _ in range(self.mon.all_clear_cycles + 1):
            self.mon.update_room("Conservatory", False, 0.0, 17.0, 18.0, 8.0)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.events, [])

    def test_the_status_menu_still_lists_the_room(self):
        self._hot(7.0)
        self.assertIn("Conservatory", self.mon.get_overheating_rooms())

    def test_switching_it_on_restores_the_alert(self):
        om.ALERT_WHEN_RADIATOR_DOWN = True
        try:
            self._hot(7.0)
        finally:
            om.ALERT_WHEN_RADIATOR_DOWN = False
        self.assertTrue(self.sent)


if __name__ == "__main__":
    unittest.main()
