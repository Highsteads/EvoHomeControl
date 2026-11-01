#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_heating_rules.py
# Description: Small, hardware-free checks of heating_logic's own rules: the outdoor
#              offset, the summer window, plan-change times across the October clock
#              change, reading ages, window contacts, cancel-hold validation and the
#              timed-to-permanent fallback in send_setpoint.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import types
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

LONDON = ZoneInfo("Europe/London")


def _zone(dev_id=None, **states):
    return types.SimpleNamespace(id=dev_id or 1, name="Test Zone", states=dict(states))


class _Ramses:
    def __init__(self, enabled=True, raises=None, version="1.18.0"):
        self.enabled, self.raises, self.pluginVersion = enabled, raises, version
        self.calls = []

    def isEnabled(self):
        return self.enabled

    def executeAction(self, action_id, deviceId=0, props=None, **kw):
        if self.raises:
            raise self.raises
        self.calls.append((action_id, deviceId, dict(props or {})))


@pytest.fixture
def wire(indigo_mod, monkeypatch):
    """A fake RAMSES ESP and thermostat namespace; records permanent sends and log lines."""
    rec = types.SimpleNamespace(ramses=_Ramses(), permanent=[], lines=[])
    monkeypatch.setattr(indigo_mod, "server", types.SimpleNamespace(
        log=lambda msg, level=None, **k: rec.lines.append((msg, level)),
        getInstallFolderPath=lambda: "/tmp/evohome-test",
        getPlugin=lambda pid: rec.ramses))
    monkeypatch.setattr(indigo_mod, "thermostat", types.SimpleNamespace(
        setHeatSetpoint=lambda dev, value=None: rec.permanent.append((dev.id, value))))
    return rec


# ------------------------------------------------------------- outdoor offset

def test_no_outdoor_reading_means_no_offset(hl):
    assert hl.calculate_temp_offset(None) == 0.0


def test_offset_steps_at_its_two_triggers(hl):
    low, high = hl.WARM_WEATHER_TRIGGER_LOW, hl.WARM_WEATHER_TRIGGER
    assert hl.calculate_temp_offset(low) == 0.0                     # "above", not "at"
    assert hl.calculate_temp_offset(low + 0.1) == -hl.WARM_WEATHER_REDUCTION_LOW
    assert hl.calculate_temp_offset(high) == -hl.WARM_WEATHER_REDUCTION_LOW
    assert hl.calculate_temp_offset(high + 0.1) == -hl.WARM_WEATHER_REDUCTION


# ------------------------------------------------------------- summer window

@pytest.mark.parametrize("day, off", [
    (date(2026, 5, 31), False), (date(2026, 6, 1), True),
    (date(2026, 9, 29), True),  (date(2026, 9, 30), False),   # heating back ON on the end date
])
def test_summer_window_is_start_inclusive_end_exclusive(hl, day, off):
    assert hl.is_within_summer_off(day, 6, 1, 9, 30) is off


@pytest.mark.parametrize("day, off", [
    (date(2026, 10, 31), False), (date(2026, 11, 1), True),
    (date(2027, 1, 15), True),   (date(2027, 3, 1), False),
])
def test_a_window_across_new_year_wraps(hl, day, off):
    assert hl.is_within_summer_off(day, 11, 1, 3, 1) is off


# ------------------------------------------------- plan changes and the clocks

def _epoch(y, m, d, hh, mm=0, fold=0):
    return datetime(y, m, d, hh, mm, tzinfo=LONDON, fold=fold).timestamp()


def test_next_plan_change_across_the_october_clock_change(hl):
    """25-10-2026: 02:00 BST becomes 01:00 GMT. From 00:30 BST the next change of a plan
    that steps up at 07:00 is 07:00 GMT that morning - 7.5 real hours, not 6.5."""
    plan = [16] * 7 + [20] * 17
    start = _epoch(2026, 10, 25, 0, 30)
    got = hl.next_plan_change(plan, start)
    assert got == _epoch(2026, 10, 25, 7)
    assert (got - start) / 3600 == 7.5


def test_a_constant_plan_changes_at_midnight(hl):
    got = hl.next_plan_change([18] * 24, _epoch(2026, 11, 1, 15, 20))
    assert got == _epoch(2026, 11, 2, 0)


def test_hold_wire_time_is_house_time(hl):
    assert hl.hold_wire_time(_epoch(2026, 7, 1, 9)) == "2026-07-01 09:00"


# ------------------------------------------------------------- cancel holds

def test_cancel_holds_keep_only_future_deadlines_for_real_radiators(hl):
    now = 1_800_000_000
    real = sorted(hl.ALL_RADIATOR_IDS)[0]
    raw = {str(real): now + 3600,          # good
           "999999999": now + 3600,         # not a radiator
           str(sorted(hl.ALL_RADIATOR_IDS)[1]): now - 1,           # already over
           str(sorted(hl.ALL_RADIATOR_IDS)[2]): now + 27 * 3600}   # too far ahead
    assert hl.valid_cancel_holds(raw, now=now) == {str(real): now + 3600}
    assert hl.valid_cancel_holds("rubbish", now=now) == {}


# ------------------------------------------------------------- reading ages

def test_the_epoch_beats_the_local_text(hl):
    now = datetime(2026, 11, 1, 12, 0, tzinfo=LONDON)
    dev = _zone(temperatureSeenEpoch=str(int(now.timestamp()) - 600),
                temperatureSeen="2020-01-01 00:00:00")
    assert hl.zone_reading_age_minutes(dev, now=now) == pytest.approx(10.0)


def test_a_blank_temperature_seen_is_infinitely_old(hl):
    """RAMSES starts a new zone at 0 degC; that is not a reading."""
    assert hl.zone_reading_age_minutes(_zone(temperatureSeen="")) == float("inf")


def test_nothing_to_go_on_is_cannot_tell(hl):
    assert hl.zone_reading_age_minutes(_zone()) is None


def test_a_reading_in_the_repeated_hour_is_not_from_the_future(hl):
    """01:30 happens twice on 25-10-2026. At 01:40 GMT a 01:30 text is 10 minutes old
    (the GMT 01:30), not 70 (the BST one) and not negative."""
    now = datetime(2026, 10, 25, 1, 40, tzinfo=LONDON, fold=1)
    dev = _zone(temperatureSeen="2026-10-25 01:30:00")
    assert hl.zone_reading_age_minutes(dev, now=now) == pytest.approx(10.0)


# ------------------------------------------------------------- window contacts

def test_contact_states(hl, indigo_mod, monkeypatch):
    monkeypatch.setattr(indigo_mod, "devices", {
        1: _zone(1, contact=False), 2: _zone(2, contact=True), 3: _zone(3, contact="false"),
        4: _zone(4, **{"onOffState.ui": "open"})})
    assert hl._contact_is_open(1) is True       # Zigbee2MQTT: contact False = open
    assert hl._contact_is_open(2) is False
    assert hl._contact_is_open(3) is True
    assert hl._contact_is_open(4) is True       # legacy fallback
    assert hl._contact_is_open(99) is False     # missing device reads as closed


# ------------------------------------------------- timed vs permanent sends

def test_timed_send_goes_through_ramses_with_the_minutes(hl, wire):
    hl.set_override_minutes(120)
    assert hl.send_setpoint(_zone(7), 19.5) is True
    assert wire.ramses.calls == [("setTemporarySetpoint", 7,
                                  {"setpoint": "19.50", "minutes": "120"})]
    assert wire.permanent == []


def test_permanent_when_override_minutes_is_zero(hl, wire):
    hl.set_override_minutes(0)
    hl.send_setpoint(_zone(7), 19.0)
    assert wire.permanent == [(7, 19.0)] and wire.ramses.calls == []


def test_a_disabled_ramses_falls_back_to_permanent_and_says_so(hl, wire):
    hl.set_override_minutes(120)
    wire.ramses.enabled = False
    hl.send_setpoint(_zone(7), 19.0)
    assert wire.permanent == [(7, 19.0)]
    assert any("Could not send a timed setpoint" in m for m, _ in wire.lines)


@pytest.mark.xfail(strict=True, reason=(
    "BUG: set_override_minutes() clears _OVERRIDE['broken'] but not _OVERRIDE_WARNED, so "
    "after the user saves the settings to retry, the same failure falls back to permanent "
    "overrides again WITHOUT any warning (heating_logic.py set_override_minutes / "
    "send_setpoint)."))
def test_a_second_fallback_after_saving_the_settings_is_warned_again(hl, wire):
    hl.set_override_minutes(120)
    wire.ramses.enabled = False
    hl.send_setpoint(_zone(7), 19.0)
    wire.lines.clear()
    hl.set_override_minutes(120)          # what closedPrefsConfigUi does on Save
    hl.send_setpoint(_zone(7), 19.0)
    assert any("Could not send a timed setpoint" in m for m, _ in wire.lines)


def test_one_failure_latches_every_later_send_to_permanent(hl, wire):
    """Documents current behaviour (by design, but see the review): a single failed timed
    send makes EVERY later send permanent until the settings are saved or the plugin
    restarts, even once RAMSES ESP is healthy again."""
    hl.set_override_minutes(120)
    wire.ramses.raises = RuntimeError("busy")
    hl.send_setpoint(_zone(7), 19.0)
    wire.ramses.raises = None
    hl.send_setpoint(_zone(8), 19.0)
    assert wire.ramses.calls == []
    assert wire.permanent == [(7, 19.0), (8, 19.0)]


def test_wanting_permanent_means_a_timed_zone_is_resent(hl):
    hl.set_override_minutes(0)
    assert hl.needs_override_refresh(_zone(zoneMode="temporary override")) is True
    assert hl.needs_override_refresh(_zone(zoneMode="permanent override")) is False
