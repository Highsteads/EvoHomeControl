#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_timetable_check.py
# Description: 1.15.0 - the daily check that the Evohome controller's own timetable (read by
#              RAMSES ESP 1.13.0) still matches this plugin's plans.
#              Run from this directory with:  python3 test_timetable_check.py
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0

import importlib.util
import json
import os
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


class _ServerStub:
    @staticmethod
    def log(msg, level=None, isError=False, **kwargs):
        pass

    @staticmethod
    def getInstallFolderPath():
        return "/tmp/evohome-test"


class _PluginBaseStub:
    def __init__(self, *args, **kwargs):
        pass


_existing = sys.modules.get("indigo")
_indigo = _existing if _existing is not None else types.ModuleType("indigo")
if not hasattr(_indigo, "server") or not hasattr(_indigo.server, "getInstallFolderPath"):
    _indigo.server = _ServerStub()
for _name, _value in (
    ("PluginBase", _PluginBaseStub),
    ("devices",    {}),
    ("variables",  {}),
    ("thermostat", types.SimpleNamespace(setHeatSetpoint=lambda *a, **k: None)),
    ("device",     types.SimpleNamespace(turnOn=lambda *a, **k: None,
                                         turnOff=lambda *a, **k: None)),
    ("trigger",    types.SimpleNamespace(execute=lambda *a, **k: None)),
):
    if not hasattr(_indigo, _name):
        setattr(_indigo, _name, _value)
sys.modules["indigo"] = _indigo

if "schedules" not in sys.modules:
    _schedules = types.ModuleType("schedules")
    _schedules.MAX_TEMP_LIMITS       = {}
    _schedules.MAX_TEMP_LIMITS_GUEST = {}
    _schedules.BOOST_AMOUNTS         = {}
    _schedules.TIMED_BOOST_ROOMS     = set()
    sys.modules["schedules"] = _schedules

import timetable_check as tc      # noqa: E402
import plugin as plugin_mod       # noqa: E402

_PLUGIN = plugin_mod.__name__

# The real plans, loaded from the file rather than the stub the other tests share.
_spec = importlib.util.spec_from_file_location("schedules_real_tt", os.path.join(_HERE, "schedules.py"))
REAL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(REAL)
PLAN_NAMES = ("Bathroom", "Bedroom_1", "Bedroom_2", "Bedroom_3", "En_Suite", "Conservatory",
              "Dining_Room", "Hall_Bedroom", "Hall_Kitchen", "Living_Room_Front",
              "Living_Room_Door", "Utility_Room")


def as_written(hours):
    """The week exactly as ~/bin/evohome-write-plans put it on the controller on 29-09-2026:
    a switchpoint at each hour the plan changes, a flat day as midnight + 11:50pm."""
    points = [(h * 60, float(v)) for h, v in enumerate(hours) if h > 0 and v != hours[h - 1]]
    if not points:
        points = [(0, float(hours[0])), (23 * 60 + 50, float(hours[0]))]
    return {d: list(points) for d in range(7)}


# ===========================================================================
class TestCompare(unittest.TestCase):
# ===========================================================================

    def test_every_real_plan_matches_itself_as_written_to_the_controller(self):
        for name in PLAN_NAMES:
            hours = getattr(REAL, name)
            self.assertIsNone(tc.first_difference(hours, as_written(hours)), name)

    def test_a_flat_day_stored_as_one_switchpoint_also_matches(self):
        self.assertIsNone(tc.first_difference([14] * 24, {d: [(0, 14.0)] for d in range(7)}))

    def test_the_value_before_the_first_switchpoint_comes_from_the_day_before(self):
        hours = REAL.Living_Room_Front
        week = as_written(hours)
        week[6] = [(300, 17.0), (1320, 18.0)]           # Sunday ends at 18, not 16
        day, minutes, have, want = tc.first_difference(hours, week)
        self.assertEqual((have, want), (18.0, 16.0))

    def test_a_difference_is_found_and_described(self):
        hours = REAL.Dining_Room
        week = as_written(hours)
        week[0] = [(390, 21.0), (480, 18.0), (1080, 21.0), (1350, 16.0)]
        diff = tc.first_difference(hours, week)
        self.assertEqual(tc.describe_difference("Dining Room", diff),
                         "Dining Room: at 6am on Monday the controller has 16 degrees "
                         "where the plan has 18.")

    def test_a_missing_day_is_a_difference(self):
        week = as_written(REAL.Bathroom)
        del week[3], week[4], week[5], week[6], week[0], week[1], week[2]
        self.assertIsNotNone(tc.first_difference(REAL.Bathroom, week))

    def test_junk_data_reads_as_nothing(self):
        self.assertIsNone(tc.parse(""))
        self.assertIsNone(tc.parse("not json"))
        self.assertIsNone(tc.parse("{}"))

    def test_ramses_esp_s_format_parses(self):
        text = json.dumps({"0": [[300, 17.0], [540, 18.0]]}, separators=(",", ":"))
        self.assertEqual(tc.parse(text), {0: [(300, 17.0), (540, 18.0)]})


# ===========================================================================
class TestDailyCheck(unittest.TestCase):
# ===========================================================================

    NOW = datetime(2026, 10, 5, 4, 5)

    def setUp(self):
        self._saved = dict(_indigo.devices)
        self.saved_patch = mock.patch.object(plugin_mod, "schedules", REAL)
        self.saved_patch.start()
        self.pushes = []
        for dev_id, room, hours in plugin_mod._room_plans():
            _indigo.devices[dev_id] = types.SimpleNamespace(id=dev_id, name=room, states={
                "timetableData": json.dumps({str(d): [[m, sp] for m, sp in pts]
                                             for d, pts in as_written(hours).items()}),
                "timetableRead": (self.NOW - timedelta(minutes=50)).strftime("%Y-%m-%d %H:%M"),
            })
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs, p.store = {}, {}
        p._save_state = lambda: None
        p.logger = mock.MagicMock()
        p.overheat = types.SimpleNamespace(
            _send_pushover=lambda title, body, priority=0: self.pushes.append((title, body)))
        self.p = p

    def tearDown(self):
        self.saved_patch.stop()
        _indigo.devices.clear()
        _indigo.devices.update(self._saved)

    def _change(self, dev_id, week):
        _indigo.devices[dev_id].states["timetableData"] = json.dumps(
            {str(d): [[m, sp] for m, sp in pts] for d, pts in week.items()})

    def test_all_matching_is_quiet(self):
        with mock.patch(_PLUGIN + "._log") as log:
            self.p._check_timetable(self.NOW)
        log.assert_not_called()
        self.assertEqual(self.pushes, [])

    def test_a_room_that_differs_warns_and_pushes_once(self):
        self._change(plugin_mod.DEV_UTILITY_ROOM_ID, {d: [(390, 21.0), (480, 18.0)] for d in range(7)})
        with mock.patch(_PLUGIN + "._log") as log:
            self.p._check_timetable(self.NOW)
            self.p._check_timetable(self.NOW + timedelta(days=1))
        warnings = [c for c in log.call_args_list if c.kwargs.get("level") == "WARNING"]
        self.assertEqual(len(warnings), 2, "the warning repeats each day")
        self.assertEqual(len(self.pushes), 1, "the push does not")
        title, body = self.pushes[0]
        self.assertEqual(title, "Evohome timetable differs in the Utility Room")
        self.assertTrue(body.isascii() and "|" not in body and "=" not in body)

    def test_putting_it_right_re_arms_the_push(self):
        self._change(plugin_mod.DEV_UTILITY_ROOM_ID, {d: [(0, 21.0)] for d in range(7)})
        self.p._check_timetable(self.NOW)
        self._change(plugin_mod.DEV_UTILITY_ROOM_ID, as_written(REAL.Utility_Room))
        self.p._check_timetable(self.NOW)
        self._change(plugin_mod.DEV_UTILITY_ROOM_ID, {d: [(0, 21.0)] for d in range(7)})
        self.p._check_timetable(self.NOW)
        self.assertEqual(len(self.pushes), 2)

    def test_an_old_reading_is_reported_not_trusted(self):
        _indigo.devices[plugin_mod.DEV_BATHROOM_ID].states["timetableRead"] = "2026-10-01 03:15"
        with mock.patch(_PLUGIN + "._log") as log:
            self.p._check_timetable(self.NOW)
        self.assertIn("Bathroom", log.call_args.args[0])
        self.assertEqual(log.call_args.kwargs.get("level"), "WARNING")
        self.assertEqual(self.pushes, [])

    def test_without_ramses_1_13_it_says_so_only_when_asked(self):
        for dev_id, _room, _h in plugin_mod._room_plans():
            del _indigo.devices[dev_id].states["timetableData"]
        with mock.patch(_PLUGIN + "._log") as log:
            self.p._check_timetable(self.NOW)
            log.assert_not_called()
            self.p._check_timetable(self.NOW, manual=True)
        self.assertIn("RAMSES ESP 1.13.0", log.call_args.args[0])

    def test_it_runs_once_a_day_after_four(self):
        calls = []
        self.p._check_timetable = lambda now, manual=False: calls.append(now)
        self.p._maybe_check_timetable(datetime(2026, 10, 5, 3, 59))
        self.p._maybe_check_timetable(datetime(2026, 10, 5, 4, 0))
        self.p._maybe_check_timetable(datetime(2026, 10, 5, 9, 0))
        self.p._maybe_check_timetable(datetime(2026, 10, 6, 4, 1))
        self.assertEqual(calls, [datetime(2026, 10, 5, 4, 0), datetime(2026, 10, 6, 4, 1)])


if __name__ == "__main__":
    unittest.main()
