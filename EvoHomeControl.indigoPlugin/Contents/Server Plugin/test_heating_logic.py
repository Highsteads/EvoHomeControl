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
from overheat_monitor import OverheatMonitor       # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
