#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_18_review.py
# Description: 1.18.0 - the eight faults from the 02-10-2026 independent review:
#              temperature age from RAMSES ESP's temperatureSeen, overheat alerts that
#              report and retry a failed send, state saves that cannot interleave, a
#              missed 10am that still ends the morning, snow forecasts chosen by their
#              own time, renewals scaled to a 1-hour setting, a cycle request that a
#              running cycle cannot wipe, and the drying test timer across the clock
#              change. Every test here was watched failing against the 1.17.0 sources.
#              No Indigo runtime required - `indigo` is stubbed at import time.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0

import json
import os
import sys
import tempfile
import threading
import time
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
import weather as wx              # noqa: E402

_PLUGIN = plugin_mod.__name__
BST = timezone(timedelta(hours=1))
GMT = timezone.utc


def _stamp(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


# ===========================================================================
class TestTemperatureAge(unittest.TestCase):
    """Finding 1. RAMSES moves lastSeen on setpoint and mode reports as well as
    temperatures, so lastSeen said nothing about whether the temperature was current."""
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
        hl._ZONE_STALE_LATCH.clear()

    def _run(self, states):
        rad = types.SimpleNamespace(id=1, name="rad", states=dict(
            {"setpointHeat": "20.0", "zoneMode": "permanent override"}, **states))
        _indigo.devices[hl.DEV_CONSERVATORY_ID] = rad
        hl.process_room_temperature(
            room_name="Conservatory", room_schedule=[18] * 24, window_devices=[],
            ha_device_id=hl.DEV_CONSERVATORY_ID, current_hour=12, current_minute=5,
            current_outdoor_temp=5.0, last_setpoints={}, last_messages={},
            log_buffer=[], changes_buffer=[], overheat_monitor=None)

    def test_an_old_temperature_is_not_made_fresh_by_setpoint_reports(self):
        self._run({"temperatureInput1": "25.0", "lastSeen": _stamp(0),
                   "temperatureSeen": _stamp(180)})
        self.assertEqual(self.written, [], "a three-hour-old 25 degC must not be acted on")

    def test_a_fresh_temperature_is_used(self):
        self._run({"temperatureInput1": "15.0", "lastSeen": _stamp(0),
                   "temperatureSeen": _stamp(2)})
        self.assertEqual(len(self.written), 1)

    def test_a_temperature_never_reported_is_not_a_temperature(self):
        """RAMSES starts a new zone at 0 with a blank temperatureSeen."""
        self._run({"temperatureInput1": 0.0, "lastSeen": _stamp(0), "temperatureSeen": ""})
        self.assertEqual(self.written, [])

    def test_an_older_ramses_without_the_state_still_uses_last_seen(self):
        self._run({"temperatureInput1": "15.0", "lastSeen": _stamp(2)})
        self.assertEqual(len(self.written), 1)
        hl._ZONE_STALE_LATCH.clear()
        self.written.clear()
        self._run({"temperatureInput1": "15.0", "lastSeen": _stamp(180)})
        self.assertEqual(self.written, [])

    def test_a_missing_temperature_state_is_not_zero(self):
        self._run({"lastSeen": _stamp(0), "temperatureSeen": _stamp(0)})
        self.assertEqual(self.written, [])

    def test_a_genuine_zero_is_still_a_reading(self):
        self.assertEqual(hl.zone_reading_age_minutes(types.SimpleNamespace(
            states={"temperatureInput1": 0.0, "temperatureSeen": _stamp(1)})) < 5, True)


# ===========================================================================
class TestOverheatAlertDelivery(unittest.TestCase):
    """Finding 2. A send that no channel accepted was recorded as sent for good."""
# ===========================================================================

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.m = om.OverheatMonitor(self.path, run_interval_mins=5)
        self.m.email_address = "someone@example.com"
        self.push_ok = False
        self.mail_ok = False
        self.attempts = 0
        self.events = []

        def push(*a, **k):
            self.attempts += 1
            return self.push_ok
        self.m._send_pushover = push
        self.m._send_email = lambda *a, **k: self.mail_ok
        self.m.event_callback = self.events.append
        self.clock = [1000000.0]
        p = mock.patch.object(om.time, "time", lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        os.unlink(self.path)

    def _cycle(self):
        self.m.update_room("Bathroom", True, 7.0, 27.0, 20.0, 5.0)

    def test_a_failed_alert_is_not_marked_sent(self):
        self._cycle()
        self.assertFalse(self.m.history["Bathroom"]["alert_sent"])

    def test_it_is_tried_again_after_the_wait_not_every_cycle(self):
        self._cycle()
        self.clock[0] += 300
        self._cycle()
        self.assertEqual(self.attempts, 1, "not every five minutes")
        self.clock[0] += om.ALERT_RETRY_SECS
        self.push_ok = True
        self._cycle()
        self.assertEqual(self.attempts, 2)
        self.assertTrue(self.m.history["Bathroom"]["alert_sent"])

    def test_the_trigger_fires_once_however_many_tries(self):
        self._cycle()
        self.clock[0] += om.ALERT_RETRY_SECS
        self.push_ok = True
        self._cycle()
        self.assertEqual(self.events, ["overheatAlert"])

    def test_one_channel_is_enough(self):
        self.mail_ok = True
        self._cycle()
        self.assertTrue(self.m.history["Bathroom"]["alert_sent"])

    def test_with_no_channel_set_up_there_is_nothing_to_retry(self):
        self.m.email_address = ""
        with mock.patch.object(self.m, "_any_channel", return_value=False):
            self._cycle()
        self.assertTrue(self.m.history["Bathroom"]["alert_sent"])

    def test_a_room_that_settles_drops_the_pending_retry(self):
        self._cycle()
        self.m.update_room("Bathroom", False, 0.0, 20.0, 20.0, 5.0)
        self.assertIsNone(self.m.history["Bathroom"]["alert_retry_at"])

    def test_the_messages_are_plain_english(self):
        sent = []
        self.m._send_pushover = lambda t, b, priority=0: sent.append((t, b)) or True
        self._cycle()
        self.m.history["Bathroom"]["alert_timestamp"] = datetime.now().strftime(
            "%d-%m-%Y %H:%M:%S")
        self.m.send_all_clear("Bathroom")
        self.assertEqual(len(sent), 2)
        for title, body in sent:
            text = title + body
            text.encode("ascii")
            for bad in ("|", "=", "degC", ":  "):
                self.assertNotIn(bad, text)
            self.assertTrue(body.endswith("."))
            self.assertLess(len(body), 1024)


# ===========================================================================
class TestStateSaves(unittest.TestCase):
    """Finding 3. Two saves shared one '<path>.tmp' and could interleave."""
# ===========================================================================

    def test_a_write_inside_another_write_leaves_valid_json(self):
        """The interleaving, made deterministic: a second writer runs while the
        first is half way through its dump."""
        d = tempfile.mkdtemp()
        path = os.path.join(d, "plugin_state.json")
        real_dump = json.dump
        nested = {"done": False}

        def dump(obj, f, **kw):
            if not nested["done"]:
                nested["done"] = True
                f.write('{"first": ')
                plugin_mod._atomic_write_json(path, {"second": "x" * 500})
                f.write('"short"}')
                return
            real_dump(obj, f, **kw)

        with mock.patch.object(plugin_mod.json, "dump", dump):
            plugin_mod._atomic_write_json(path, {"first": "short"})
        with open(path, encoding="utf-8") as f:
            json.load(f)
        self.assertEqual([n for n in os.listdir(d) if n.endswith(".tmp")], [])

    def test_a_rewrite_keeps_the_files_mode(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "plugin_state.json")
        plugin_mod._atomic_write_json(path, {"a": 1})
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644, "a new file is 0644")
        os.chmod(path, 0o640)
        plugin_mod._atomic_write_json(path, {"a": 2})
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)

    def test_saves_from_two_threads_take_turns(self):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.data_dir = tempfile.mkdtemp()
        p.store = {"timed_boost_active": False, "en_suite_morning_active": False}
        inside, release, order = threading.Event(), threading.Event(), []
        real = p._save_state_locked

        def slow():
            order.append("first in")
            inside.set()
            release.wait(2)
            real()
            order.append("first out")

        def fast():
            order.append("second in")
            real()

        p._save_state_locked = slow
        a = threading.Thread(target=p._save_state)
        a.start()
        inside.wait(2)
        p._save_state_locked = fast
        b = threading.Thread(target=p._save_state)
        b.start()
        time.sleep(0.1)
        self.assertEqual(order, ["first in"], "the second save must wait its turn")
        release.set()
        a.join(2)
        b.join(2)
        self.assertEqual(order, ["first in", "first out", "second in"])


# ===========================================================================
class TestMissedTenAm(unittest.TestCase):
    """Finding 4. A morning still active after 10:59 was never ended by the plugin."""
# ===========================================================================

    def _plugin(self, hour):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs = {}
        p.store = {"en_suite_morning_active": True}
        p.weather = None
        p._summer_lockout_active = lambda: False
        p._away_mode_on = lambda: False
        p._save_state = lambda: None
        p._fire_event = lambda *a, **k: None
        self.floor_off = []
        p._en_suite_floor_off = lambda: self.floor_off.append(True)
        with mock.patch(_PLUGIN + ".datetime") as dt:
            dt.now.return_value = datetime(2026, 12, 1, hour, 5)
            p._check_en_suite_morning()
        return p

    def test_resuming_at_eleven_ends_the_morning(self):
        p = self._plugin(11)
        self.assertFalse(p.store["en_suite_morning_active"])
        self.assertEqual(self.floor_off, [True])

    def test_resuming_in_the_afternoon_ends_it_too(self):
        self.assertFalse(self._plugin(15).store["en_suite_morning_active"])

    def test_inside_the_morning_it_carries_on(self):
        p = self._plugin(8)
        self.assertTrue(p.store["en_suite_morning_active"])
        self.assertEqual(self.floor_off, [])


# ===========================================================================
class TestSnowForecast(unittest.TestCase):
    """Finding 5. The first N cached hours were read without looking at their time."""
# ===========================================================================

    NOW = 1790000000.0

    def _weather(self, hours_from_now, loaded_minutes_ago=5):
        w = wx.WeatherData.__new__(wx.WeatherData)
        w.hourly = [{"dt": int(self.NOW + h * 3600), "weather": [{"id": 601}]}
                    for h in hours_from_now]
        w.last_update = datetime.now() - timedelta(minutes=loaded_minutes_ago)
        return w

    def test_hours_already_past_do_not_count(self):
        w = self._weather([-96, -95, -94])
        self.assertEqual(w.get_snow_forecast(12, now_ts=self.NOW), [])

    def test_a_forecast_not_refreshed_for_hours_is_not_trusted(self):
        w = self._weather([1, 2], loaded_minutes_ago=4 * 60)
        self.assertEqual(w.get_snow_forecast(12, now_ts=self.NOW), [])

    def test_the_current_and_coming_hours_count_with_real_offsets(self):
        w = self._weather([-3, -0.5, 2, 13])
        got = w.get_snow_forecast(12, now_ts=self.NOW)
        self.assertEqual([g["hour_offset"] for g in got], [0, 2])

    def test_an_hour_without_a_time_is_skipped(self):
        w = self._weather([])
        w.hourly = [{"weather": [{"id": 601}]}]
        self.assertEqual(w.get_snow_forecast(12, now_ts=self.NOW), [])


# ===========================================================================
class TestRenewalThreshold(unittest.TestCase):
    """Finding 6. With 1-hour settings a fixed 60-minute renewal resent every cycle."""
# ===========================================================================

    def tearDown(self):
        hl.set_override_minutes(0)

    def _needs(self, minutes, left):
        hl.set_override_minutes(minutes)
        now = datetime(2026, 12, 1, 12, 0)
        dev = types.SimpleNamespace(states={
            "zoneMode": "temporary override",
            "zoneOverrideUntil": (now + timedelta(minutes=left)).strftime("%Y-%m-%d %H:%M")})
        return hl.needs_override_refresh(dev, now=now)

    def test_a_one_hour_setting_is_not_renewed_five_minutes_in(self):
        self.assertFalse(self._needs(60, 56))

    def test_a_one_hour_setting_is_renewed_half_way(self):
        self.assertTrue(self._needs(60, 25))

    def test_the_two_hour_setting_is_unchanged(self):
        self.assertFalse(self._needs(120, 65))
        self.assertTrue(self._needs(120, 55))

    def test_twelve_five_minute_cycles_send_a_one_hour_zone_about_twice(self):
        hl.set_override_minutes(60)
        start, end, sent = datetime(2026, 12, 1, 12, 0), None, 0
        for i in range(12):
            now = start + timedelta(minutes=5 * i)
            dev = types.SimpleNamespace(states={
                "zoneMode": "temporary override" if end else "schedule",
                "zoneOverrideUntil": end.strftime("%Y-%m-%d %H:%M") if end else ""})
            if hl.needs_override_refresh(dev, now=now):
                sent += 1
                end = now + timedelta(minutes=61)
        self.assertLessEqual(sent, 3)


# ===========================================================================
class TestCycleRequestDuringACycle(unittest.TestCase):
    """Finding 7. A request made while a cycle ran was wiped when it finished."""
# ===========================================================================

    def test_a_request_made_mid_cycle_gets_its_own_cycle(self):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs = {}
        p.store = {"last_heating_cycle": 0.0, "cycle_requests": 0,
                   "cycle_requests_served": 0}
        for name in ("_check_summer_force_expiry", "_check_en_suite_morning",
                     "_check_en_suite_drying", "_check_timed_boost_expiry"):
            setattr(p, name, lambda: None)
        p._maybe_check_timetable = lambda now: None
        runs = []

        def cycle():
            runs.append(True)
            if len(runs) == 1:
                p.actionRunCycleNow(None)   # arrives while this cycle is running
        p._run_heating_cycle = cycle
        p._tick(10000.0)
        p._tick(10030.0)
        p._tick(10060.0)
        self.assertEqual(len(runs), 2, "one scheduled, one asked for, then quiet")


# ===========================================================================
class TestDryingTestTimerAcrossTheClockChange(unittest.TestCase):
    """Finding 8. A 30-minute test begun in the repeated hour ran for 90."""
# ===========================================================================

    def test_thirty_minutes_is_thirty_real_minutes(self):
        p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
        p.pluginPrefs = {"enSuiteDryingMaxOutdoor": "0"}
        p.weather = None
        p.store = {"en_suite_drying_active": True,
                   "en_suite_drying_manual_expiry":
                       datetime(2026, 10, 25, 1, 40, tzinfo=BST) + timedelta(minutes=30)}
        p._en_suite_window_is_shut = lambda: True
        stopped = []
        p._stop_en_suite_drying = lambda reason, cancel_for_today=False: stopped.append(reason)
        # 45 real minutes after 01:40 BST is 01:25 GMT, the second 01:25 that morning.
        later = datetime(2026, 10, 25, 1, 25, tzinfo=GMT)
        with mock.patch(_PLUGIN + "._now_aware", return_value=later), \
                mock.patch(_PLUGIN + ".datetime") as dt:
            dt.now.return_value = datetime(2026, 10, 25, 1, 25)
            p._check_en_suite_drying()
        self.assertEqual(len(stopped), 1)
        self.assertIn("time limit", stopped[0])

    def test_the_timer_is_set_with_its_offset(self):
        src = plugin_mod.Plugin._start_en_suite_drying.__code__.co_names
        self.assertIn("_now_aware", src)


if __name__ == "__main__":
    unittest.main()
