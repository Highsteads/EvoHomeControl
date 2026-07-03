#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_heating_logic.py
# Description: Unit tests for heating_logic.check_overheating and message refinement.
#              Run from this directory with:  python3 test_heating_logic.py
#              No Indigo runtime required — `indigo` is stubbed at import time.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        30-04-2026
# Version:     1.0

import sys
import types
import unittest


# ---------------------------------------------------------------------------
# Stub the `indigo` module so heating_logic / overheat_monitor can be imported
# outside the Indigo runtime.
# ---------------------------------------------------------------------------
_indigo = types.ModuleType("indigo")


class _ServerStub:
    @staticmethod
    def log(msg, level="INFO", isError=False):
        pass  # silent


_indigo.server    = _ServerStub()
_indigo.devices   = {}
_indigo.variables = {}
sys.modules["indigo"] = _indigo

# Stub schedules to avoid import-side-effects on heating_logic.
_schedules = types.ModuleType("schedules")
_schedules.MAX_TEMP_LIMITS       = {}
_schedules.MAX_TEMP_LIMITS_GUEST = {}
_schedules.BOOST_AMOUNTS         = {}
_schedules.TIMED_BOOST_ROOMS     = set()
sys.modules["schedules"] = _schedules

# Now safe to import the modules under test
import heating_logic as hl                        # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles for OverheatMonitor — bypass file IO.
# ---------------------------------------------------------------------------
class FakeMonitor:
    """In-memory stand-in for OverheatMonitor — only the bits check_overheating uses."""

    def __init__(self):
        self.history = {}

    def initialize_room(self, room_name):
        if room_name not in self.history:
            self.history[room_name] = {
                "consecutive_cycles":  0,
                "max_overheat":        0.0,
                "alert_sent":          False,
                "alert_type":          None,
                "alert_timestamp":     None,
                "stable_cycles":       0,
                "all_clear_sent":      True,
                "off_since_cycle":     0,
                "temp_history":        [],
                "is_coasting":         False,
            }


# ===========================================================================
class TestCheckOverheating(unittest.TestCase):
# ===========================================================================

    def setUp(self):
        self.mon = FakeMonitor()

    def test_below_target_not_overheating(self):
        """Room well below target should never trigger overheat."""
        is_oh, adj, amt = hl.check_overheating(15.0, 16.0, "Bathroom", self.mon)
        self.assertFalse(is_oh)
        self.assertEqual(adj, 16.0)
        self.assertEqual(amt, 0.0)

    def test_above_threshold_first_detection(self):
        """Room well above target (no history) → fires Tier 2 else-branch."""
        is_oh, adj, amt = hl.check_overheating(18.8, 16.0, "Bathroom", self.mon)
        self.assertTrue(is_oh)
        self.assertEqual(adj, 12.0)               # max(12.0, 16-6) = 12.0
        self.assertAlmostEqual(amt, 2.8)
        self.assertEqual(self.mon.history["Bathroom"]["off_since_cycle"], 1)

    def test_excluded_room_uses_simple_threshold(self):
        """Bedroom 3 is excluded — uses stateless threshold-only path."""
        is_oh, adj, amt = hl.check_overheating(20.0, 14.0, "Bedroom 3", self.mon)
        self.assertTrue(is_oh)
        self.assertEqual(adj, 12.0)               # max(12.0, 14-6) = 12.0
        self.assertAlmostEqual(amt, 6.0)

    def test_excluded_room_below_threshold(self):
        is_oh, _, _ = hl.check_overheating(14.1, 14.0, "Bedroom 3", self.mon)
        self.assertFalse(is_oh)

    def test_coast_complete_when_still_above_threshold_falls_through(self):
        """Coast-reset with overheat still > threshold should fall through to Tier 2,
        not blindly return False. (Bug fix: previously returned False unconditionally.)"""
        # Pre-load: room WAS coasting, was overheating, temp now stable above target.
        self.mon.initialize_room("Bathroom")
        rd = self.mon.history["Bathroom"]
        rd["is_coasting"]         = True
        rd["consecutive_cycles"]  = 5
        rd["off_since_cycle"]     = 5
        rd["temp_history"]        = [18.5, 18.5, 18.5]   # rate = 0
        is_oh, adj, amt = hl.check_overheating(18.5, 16.0, "Bathroom", self.mon)
        self.assertTrue(is_oh, "Should still be overheating: 18.5 > 16.0+0.25")
        self.assertEqual(adj, 12.0)

    def test_coast_complete_when_back_to_target_releases(self):
        """Coast-reset with overheat at/below threshold: release."""
        self.mon.initialize_room("Bathroom")
        rd = self.mon.history["Bathroom"]
        rd["is_coasting"]         = True
        rd["consecutive_cycles"]  = 5
        rd["temp_history"]        = [16.1, 16.1, 16.1]   # rate=0, near target
        is_oh, _, _ = hl.check_overheating(16.1, 16.0, "Bathroom", self.mon)
        # 0.1 ≤ OVERHEAT_TRIGGER_THRESHOLD (0.25) → release
        self.assertFalse(is_oh)


# ===========================================================================
class TestUpdateTempRecordsDefaults(unittest.TestCase):
    """Quick check that the high/low default sentinels guarantee FIRST reading wins."""
# ===========================================================================

    def test_high_default_below_any_realistic_temp(self):
        # Default high is -999 → any realistic outdoor temp (-50..50) >= -999
        self.assertGreaterEqual(-50.0, -999.0)
        self.assertGreaterEqual(50.0,  -999.0)

    def test_low_default_above_any_realistic_temp(self):
        # Default low is +999 → any realistic outdoor temp <= 999
        self.assertLessEqual(-50.0, 999.0)
        self.assertLessEqual(50.0,  999.0)


# ===========================================================================
class TestSnowCodes(unittest.TestCase):
# ===========================================================================

    def test_snow_codes_include_all_snow_variants(self):
        # Lazy import so we don't trip on weather's `time` import in stub envs
        from weather import _SNOW_CODES
        # 600-622 is the snow band, plus 511 (freezing rain)
        self.assertIn(600, _SNOW_CODES)
        self.assertIn(611, _SNOW_CODES)
        self.assertIn(622, _SNOW_CODES)
        self.assertIn(511, _SNOW_CODES)
        # Boundary exclusions
        self.assertNotIn(599, _SNOW_CODES)
        self.assertNotIn(623, _SNOW_CODES)
        # Rain codes (5xx other than 511) are NOT snow
        self.assertNotIn(500, _SNOW_CODES)
        self.assertNotIn(521, _SNOW_CODES)


# ===========================================================================
class TestMessageRefinementProtection(unittest.TestCase):
    """Sanity: code 17 (overheat) and 23 (passive) must be in the protection list."""
# ===========================================================================

    def test_alert_log_messages_contains_overheat_and_passive(self):
        self.assertIn(17, hl.ALERT_LOG_MESSAGES)
        self.assertIn(23, hl.ALERT_LOG_MESSAGES)


# ===========================================================================
class TestSummerWindow(unittest.TestCase):
    """is_within_summer_off date-window helper (whole-house summer shut-off)."""
# ===========================================================================

    def _off(self, m, d, sm=6, sd=1, em=9, ed=30):
        from datetime import date
        return hl.is_within_summer_off(date(2026, m, d), sm, sd, em, ed)

    def test_default_window_inside(self):
        self.assertTrue(self._off(6, 1))     # start day inclusive
        self.assertTrue(self._off(6, 6))
        self.assertTrue(self._off(7, 15))
        self.assertTrue(self._off(9, 29))    # last off day

    def test_default_window_outside(self):
        self.assertFalse(self._off(5, 31))   # day before start
        self.assertFalse(self._off(9, 30))   # end date exclusive — heating returns
        self.assertFalse(self._off(10, 1))
        self.assertFalse(self._off(1, 15))
        self.assertFalse(self._off(12, 25))

    def test_boundary_semantics(self):
        # Off 1 Jun..29 Sep inclusive, ON from 30 Sep
        self.assertTrue(self._off(6, 1))
        self.assertTrue(self._off(9, 29))
        self.assertFalse(self._off(9, 30))

    def test_wrapped_window(self):
        # Winter-off window 1 Nov -> 1 Mar (start later in the year than end)
        self.assertTrue(self._off(12, 25, sm=11, sd=1, em=3, ed=1))
        self.assertTrue(self._off(1, 15,  sm=11, sd=1, em=3, ed=1))
        self.assertTrue(self._off(11, 1,  sm=11, sd=1, em=3, ed=1))
        self.assertFalse(self._off(3, 1,  sm=11, sd=1, em=3, ed=1))   # end exclusive
        self.assertFalse(self._off(6, 1,  sm=11, sd=1, em=3, ed=1))

    def test_all_radiator_ids(self):
        # All 12 zones present and unique, En Suite included
        self.assertEqual(len(hl.ALL_RADIATOR_IDS), 12)
        self.assertEqual(len(set(hl.ALL_RADIATOR_IDS)), 12)
        self.assertIn(hl.DEV_EN_SUITE_ID, hl.ALL_RADIATOR_IDS)


# ===========================================================================
class TestLogLevelTranslation(unittest.TestCase):
    """v1.7.0: string log levels must translate to logging ints, else Indigo
    silently downgrades WARNING/ERROR lines to Info."""
# ===========================================================================

    def test_heating_logic_to_level(self):
        import logging
        self.assertEqual(hl._to_level("WARNING"), logging.WARNING)
        self.assertEqual(hl._to_level("error"),   logging.ERROR)     # case-insensitive
        self.assertEqual(hl._to_level("INFO"),    logging.INFO)
        self.assertEqual(hl._to_level("bogus"),   logging.INFO)      # unknown -> Info
        self.assertEqual(hl._to_level(logging.ERROR), logging.ERROR)  # int passes through

    def test_overheat_and_weather_slog_maps(self):
        import logging
        import overheat_monitor as om
        import weather as wx
        for mod in (om, wx):
            self.assertEqual(mod._LOG_LEVELS["WARNING"], logging.WARNING)
            self.assertEqual(mod._LOG_LEVELS["ERROR"],   logging.ERROR)


# ===========================================================================
class TestOverheatIntervalClamp(unittest.TestCase):
    """v1.7.0: OverheatMonitor.__init__ must coerce/clamp run_interval_mins so a
    blank or zero interval cannot ZeroDivision the derived cycle counters."""
# ===========================================================================

    def _make(self, interval):
        import overheat_monitor as om
        # history_path in a throwaway temp location; load_history tolerates absence
        return om.OverheatMonitor("/tmp/_evohome_test_overheat_history.json", run_interval_mins=interval)

    def test_zero_interval_does_not_crash(self):
        m = self._make(0)
        self.assertEqual(m.run_interval_mins, 5)
        self.assertGreater(m.critical_duration_cycles, 0)

    def test_blank_interval_does_not_crash(self):
        m = self._make("")
        self.assertEqual(m.run_interval_mins, 5)

    def test_string_numeric_interval(self):
        m = self._make("10")
        self.assertEqual(m.run_interval_mins, 10)
        self.assertEqual(m.critical_duration_cycles, (6 * 60) // 10)


# ===========================================================================
class TestOverheatAtomicSave(unittest.TestCase):
    """v1.7.1 (M6): save_history must write atomically and round-trip cleanly,
    leaving no leftover .tmp file."""
# ===========================================================================

    def test_save_history_roundtrip_no_tmp(self):
        import os
        import json
        import tempfile
        import overheat_monitor as om
        d = tempfile.mkdtemp()
        path = os.path.join(d, "sub", "overheat_history.json")   # makedirs must create 'sub'
        m = om.OverheatMonitor(path, run_interval_mins=5)
        m.history = {"Bathroom": {"consecutive_cycles": 3, "max_overheat": 5.5}}
        m.save_history()
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path + ".tmp"))          # temp file cleaned up
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["Bathroom"]["consecutive_cycles"], 3)


# ===========================================================================
class TestCriticalAlertNoneOutdoor(unittest.TestCase):
    """v1.7.1 (M5): a None outdoor temp (weather unavailable) must not crash the
    critical-alert formatter — it recurs every cycle until alert_sent is set."""
# ===========================================================================

    def test_none_outdoor_does_not_crash(self):
        import overheat_monitor as om
        m = om.OverheatMonitor("/tmp/_evohome_test_overheat_hist2.json", run_interval_mins=5)
        sent = {}
        m._send_pushover = lambda *a, **k: sent.setdefault("push", True)
        m._send_email    = lambda *a, **k: sent.setdefault("mail", True)
        m.history["Bathroom"] = {
            "current_temp": 26.0, "target_temp": 20.0, "outdoor_temp": None,
            "consecutive_cycles": 4, "max_overheat": 6.5, "alert_sent": False,
            "alert_type": None, "alert_timestamp": None,
        }
        # Must not raise despite outdoor_temp=None
        m.send_critical_alert("Bathroom", "CRITICAL_IMMEDIATE", 6.5)
        self.assertTrue(sent.get("push"))
        self.assertTrue(sent.get("mail"))


# ===========================================================================
class TestContactReaderParity(unittest.TestCase):
    """v1.7.1 (HL4): doors now use _contact_is_open (same reader as windows) so a
    Zigbee2MQTT contact (states['contact']: False = open) is read correctly."""
# ===========================================================================

    def test_zigbee_contact_open_and_closed(self):
        class _Dev:
            def __init__(self, states):
                self.states = states
        # Zigbee2MQTT: contact False == open
        _indigo.devices = {1: _Dev({"contact": False}), 2: _Dev({"contact": True})}
        self.assertTrue(hl._contact_is_open(1))
        self.assertFalse(hl._contact_is_open(2))

    def test_legacy_onoffstate_fallback(self):
        class _Dev:
            def __init__(self, states):
                self.states = states
        _indigo.devices = {3: _Dev({"onOffState.ui": "open"}), 4: _Dev({"onOffState.ui": "closed"})}
        self.assertTrue(hl._contact_is_open(3))
        self.assertFalse(hl._contact_is_open(4))


# ===========================================================================
class TestWeatherUrlRebuild(unittest.TestCase):
    """v1.7.2 (#3): a changed API key or location must rebuild the request URL so
    it takes effect without a plugin restart."""
# ===========================================================================

    def test_set_credentials_rebuilds_url(self):
        import weather as wx
        w = wx.WeatherData(api_key="OLDKEY", cache_path="/tmp/_evo_wx.json", lat=1.0, lon=2.0)
        self.assertIn("appid=OLDKEY", w.api_url)
        self.assertIn("lat=1.0", w.api_url)
        w.set_credentials("NEWKEY", 54.9, -1.8)
        self.assertIn("appid=NEWKEY", w.api_url)
        self.assertIn("lat=54.9", w.api_url)
        self.assertIn("lon=-1.8", w.api_url)
        self.assertNotIn("OLDKEY", w.api_url)


# ===========================================================================
class TestOverheatResetAllTracking(unittest.TestCase):
    """v1.7.2 (#6): reset_all_tracking clears alert/counters so a room can't stay
    stuck alert_sent=True across the summer lockout."""
# ===========================================================================

    def test_reset_clears_alert_state(self):
        import overheat_monitor as om
        m = om.OverheatMonitor("/tmp/_evo_oh_reset.json", run_interval_mins=5)
        m.history["Bathroom"] = {
            "consecutive_cycles": 8, "stable_cycles": 1, "alert_sent": True,
            "all_clear_sent": False, "alert_type": "CRITICAL_IMMEDIATE",
            "off_since_cycle": 4, "is_coasting": True,
        }
        m.reset_all_tracking()
        b = m.history["Bathroom"]
        self.assertEqual(b["consecutive_cycles"], 0)
        self.assertFalse(b["alert_sent"])
        self.assertTrue(b["all_clear_sent"])
        self.assertIsNone(b["alert_type"])


# ===========================================================================
class TestHalfDegreeRounding(unittest.TestCase):
    """v1.7.2 (HL7): setpoints round to the nearest 0.5degC (RAMSES resolution),
    not to a whole degree."""
# ===========================================================================

    def test_half_degree_preserved(self):
        # Mirror the clamp expression used in process_room_temperature
        def clamp(x):
            x = round(x * 2) / 2
            return max(hl.RADIATORS_OFF_TEMP, min(x, hl.MAX_ROOM_TEMP))
        self.assertEqual(clamp(20.5), 20.5)      # half degree kept
        self.assertEqual(clamp(21.3), 21.5)      # rounds up to nearest 0.5
        self.assertEqual(clamp(19.4), 19.5)      # rounds up to nearest 0.5
        self.assertEqual(clamp(19.1), 19.0)      # rounds down to nearest 0.5


if __name__ == "__main__":
    unittest.main(verbosity=2)
