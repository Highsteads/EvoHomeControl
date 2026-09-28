#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_14_fixes.py
# Description: 1.14.0 - timers that survive the clock change, Away that no longer
#              stacks with Boost or Both Out or beats an open window, a global Boost
#              that overheat detection no longer cancels, the guest Bathroom plan,
#              and the old settings removed.
#              Run from this directory with:  python3 test_1_14_fixes.py
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5.5
# Date:        28-09-2026
# Version:     1.0

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
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

import heating_logic as hl        # noqa: E402
import overheat_monitor as om     # noqa: E402
import plugin as plugin_mod       # noqa: E402

_PLUGIN = plugin_mod.__name__
BST = timezone(timedelta(hours=1))
GMT = timezone.utc


def _bare_plugin(store=None, prefs=None):
    p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
    p.pluginPrefs = prefs if prefs is not None else {}
    p.store = {"timed_boost_active": False, "timed_boost_expiry": None,
               "timed_boost_hours": 0, "summer_force_active": False,
               "summer_force_expiry": None}
    p.store.update(store or {})
    p._save_state = lambda: None
    p._fire_event = lambda *a, **k: None
    p._log_boost_revert_summary = lambda: None
    p._summer_lockout_active = lambda: False
    p._summer_enabled = lambda: True
    p._summer_status_str = lambda: "status"
    return p


# ===========================================================================
class TestTheClockChange(unittest.TestCase):
    """25 October 2026: at 02:00 BST the clocks go back to 01:00 GMT. A 1-hour boost
    started at 01:30 BST must end at 01:30 GMT - one real hour later - not at
    02:30 GMT, which is what a naive 01:30 + 1h = 02:30 gave."""
# ===========================================================================

    def test_a_boost_across_the_change_ends_after_one_real_hour(self):
        started = datetime(2026, 10, 25, 1, 30, tzinfo=BST)
        p = _bare_plugin()
        with mock.patch(_PLUGIN + "._now_aware", return_value=started):
            p._start_timed_boost(1)
        self.assertTrue(p.store["timed_boost_active"])
        with mock.patch(_PLUGIN + "._now_aware",
                        return_value=datetime(2026, 10, 25, 1, 29, tzinfo=GMT)):
            p._check_timed_boost_expiry()
        self.assertTrue(p.store["timed_boost_active"], "a minute early")
        with mock.patch(_PLUGIN + "._now_aware",
                        return_value=datetime(2026, 10, 25, 1, 31, tzinfo=GMT)):
            p._check_timed_boost_expiry()
        self.assertFalse(p.store["timed_boost_active"])

    def test_a_force_on_across_the_change_lasts_24_real_hours(self):
        started = datetime(2026, 10, 24, 12, 0, tzinfo=BST)
        p = _bare_plugin()
        with mock.patch(_PLUGIN + "._now_aware", return_value=started):
            p._start_summer_force(24)
        with mock.patch(_PLUGIN + "._now_aware",
                        return_value=datetime(2026, 10, 25, 11, 1, tzinfo=GMT)):
            p._check_summer_force_expiry()
        self.assertFalse(p.store["summer_force_active"], "24 real hours is 11:00 GMT")

    def test_an_expiry_saved_by_an_older_version_still_works(self):
        p = _bare_plugin({"timed_boost_active": True,
                          "timed_boost_expiry": datetime.now() - timedelta(minutes=1)})
        p._check_timed_boost_expiry()
        self.assertFalse(p.store["timed_boost_active"])

    def test_the_expiry_is_shown_in_the_current_local_time(self):
        exp = datetime(2026, 10, 25, 2, 30, tzinfo=BST)
        self.assertEqual(plugin_mod._local_clock(exp),
                         exp.astimezone().strftime("%H:%M"))


# ===========================================================================
class _Rooms(unittest.TestCase):
# ===========================================================================

    def setUp(self):
        self._saved_devices = dict(_indigo.devices)
        self._saved_thermo = _indigo.thermostat
        self.written = []
        _indigo.thermostat = types.SimpleNamespace(
            setHeatSetpoint=lambda dev, value=None: self.written.append(value))
        hl.set_override_minutes(0)
        hl._ZONE_STALE_LATCH.clear()

    def tearDown(self):
        _indigo.thermostat = self._saved_thermo
        _indigo.devices.clear()
        _indigo.devices.update(self._saved_devices)

    def _room(self, temp=15.0, window_open=False, **kw):
        rad = types.SimpleNamespace(id=1, name="rad", states={
            "temperatureInput1": str(temp), "setpointHeat": "20.0",
            "zoneMode": "permanent override",
            "lastSeen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        win = types.SimpleNamespace(id=2, name="win", states={"contact": not window_open})
        _indigo.devices[hl.DEV_CONSERVATORY_ID] = rad
        _indigo.devices[hl.DEV_GARDEN_WINDOW_L_ID] = win
        msgs = {}
        args = dict(room_name="Conservatory", room_schedule=[18] * 24,
                    window_devices=[hl.DEV_GARDEN_WINDOW_L_ID],
                    ha_device_id=hl.DEV_CONSERVATORY_ID, current_hour=12, current_minute=5,
                    current_outdoor_temp=5.0, last_setpoints={}, last_messages=msgs,
                    log_buffer=[], changes_buffer=[], overheat_monitor=None)
        args.update(kw)
        hl.process_room_temperature(**args)
        return msgs.get("Conservatory")


class TestAway(_Rooms):

    def test_an_open_window_closes_the_valve_even_with_away_on(self):
        msg = self._room(window_open=True, is_away=True)
        self.assertEqual(self.written, [hl.RADIATORS_OFF_TEMP])
        self.assertIn(msg, (1, 2))

    @mock.patch.dict(hl.schedules.BOOST_AMOUNTS, {"Conservatory": 3})
    def test_boost_does_not_add_to_away(self):
        self._room(is_away=True, is_boost=True)
        self.assertEqual(self.written, [hl.AWAY_TEMP])

    def test_both_out_does_not_take_four_off_away(self):
        self._room(is_away=True, is_both_out=True)
        self.assertEqual(self.written, [hl.AWAY_TEMP])

    def test_frost_protection_keeps_its_sixteen(self):
        self._room(is_away=True, is_both_out=True, current_outdoor_temp=1.0)
        self.assertEqual(self.written, [hl.AWAY_TEMP + 2.0])

    def test_both_out_leaves_an_open_window_alone(self):
        msg = self._room(window_open=True, is_both_out=True)
        self.assertEqual(self.written, [hl.RADIATORS_OFF_TEMP])
        self.assertIn(msg, (1, 2), "not relabelled 13, which next cycle reads as 'closed'")

    def test_both_out_still_works_on_its_own(self):
        self._room(is_both_out=True)
        self.assertEqual(self.written, [18.0 + hl.BOTH_OUT_OFFSET])


class TestGlobalBoostAndOverheat(_Rooms):
    """The Conservatory's +3 only comes from the global Boost variable, and a room
    still warming within 0.8 degC of its normal target was coasting - valve shut."""

    @mock.patch.dict(hl.schedules.BOOST_AMOUNTS, {"Conservatory": 3})
    def test_a_warming_room_on_global_boost_gets_its_boost(self):
        monitor = om.OverheatMonitor(os.path.join(tempfile.mkdtemp(), "h.json"))
        monitor.initialize_room("Conservatory")
        monitor.history["Conservatory"]["temp_history"] = [18.3, 18.4]
        self._room(temp=18.6, is_boost=True, overheat_monitor=monitor)
        self.assertEqual(self.written, [21.0])

    @mock.patch.dict(hl.schedules.BOOST_AMOUNTS, {"Conservatory": 3})
    def test_a_room_already_past_its_boosted_target_is_still_turned_down(self):
        monitor = om.OverheatMonitor(os.path.join(tempfile.mkdtemp(), "h.json"))
        monitor.initialize_room("Conservatory")
        monitor.history["Conservatory"]["temp_history"] = [21.2, 21.4]
        self._room(temp=21.6, is_boost=True, overheat_monitor=monitor)
        # Judged against the boosted 21, so backed off from there.
        self.assertEqual(self.written, [21.0 - hl.OVERHEAT_BACKOFF])


# ===========================================================================
class TestTheGuestBathroom(unittest.TestCase):
# ===========================================================================

    def test_midnight_matches_the_rest_of_the_night(self):
        spec = importlib.util.spec_from_file_location(
            "schedules_real_1_14", os.path.join(_HERE, "schedules.py"))
        real = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real)
        night = real.Bathroom_Guest[0:4] + real.Bathroom_Guest[22:24]
        self.assertEqual(set(night), {16})


# ===========================================================================
class TestOldSettings(unittest.TestCase):
# ===========================================================================

    def test_old_settings_go_and_current_ones_stay(self):
        p = _bare_plugin(prefs={"apiKey": "SECRET-VALUE", "separator4b": "",
                                "owmApiKey": "keep", "overrideMinutes": "120"})
        p.savePluginPrefs = mock.MagicMock()
        with mock.patch(_PLUGIN + "._log") as log:
            p._remove_orphan_prefs()
        self.assertEqual(set(p.pluginPrefs), {"owmApiKey", "overrideMinutes"})
        p.savePluginPrefs.assert_called_once()
        self.assertNotIn("SECRET-VALUE", log.call_args.args[0])

    def test_nothing_to_remove_says_nothing(self):
        p = _bare_plugin(prefs={"owmApiKey": "keep"})
        with mock.patch(_PLUGIN + "._log") as log:
            p._remove_orphan_prefs()
        log.assert_not_called()

    def test_no_setting_the_dialog_or_the_code_uses_is_on_the_list(self):
        import re
        import xml.etree.ElementTree as ET
        fields = {f.get("id") for f in
                  ET.parse(os.path.join(_HERE, "PluginConfig.xml")).getroot().iter("Field")}
        src = "".join(open(os.path.join(_HERE, n), encoding="utf-8").read()
                      for n in ("plugin.py", "heating_logic.py", "weather.py",
                                "overheat_monitor.py"))
        read = set(re.findall(r'''Prefs(?:\.get\(|\[)\s*["']([A-Za-z_0-9]+)["']''', src))
        self.assertEqual(set(plugin_mod._ORPHAN_PREF_KEYS) & (fields | read), set())


if __name__ == "__main__":
    unittest.main()
