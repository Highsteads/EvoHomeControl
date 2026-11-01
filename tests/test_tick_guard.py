#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_tick_guard.py
# Description: 1.25.4, review finding 5, and 1.25.7: a fault in any of _tick's per-poll
#              checks (the four from 1.25.4, plus the En Suite window, timetable and
#              window/door checks since 1.25.7) must not stop the
#              heating cycle, must be logged once rather than every 30 seconds, and its
#              recovery must be said once.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.1

import types

import pytest

CHECKS = ("_check_summer_force_expiry", "_check_en_suite_morning",
          "_check_en_suite_drying", "_check_timed_boost_expiry",
          "_check_en_suite_window_interlock", "_check_contacts_changed")


@pytest.fixture
def rig(plugin_mod, indigo_mod, monkeypatch):
    """A Plugin built without __init__, as test_1_18_review.py does, with every per-tick
    check stubbed out and the heating cycle counted."""
    lines = []
    monkeypatch.setattr(plugin_mod, "_log", lambda msg, level="INFO": lines.append((msg, level)))
    p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
    p.pluginPrefs = {}
    p.store = {"last_heating_cycle": 0.0, "cycle_requests": 0, "cycle_requests_served": 0}
    for name in CHECKS:
        setattr(p, name, lambda: None)
    p._maybe_check_timetable = lambda now: None
    runs = []
    p._run_heating_cycle = lambda: runs.append(True)
    return types.SimpleNamespace(p=p, runs=runs, lines=lines)


def _boom():
    raise RuntimeError("device 123 not found")


@pytest.mark.parametrize("check", CHECKS)
def test_a_failing_check_does_not_stop_the_heating_cycle(rig, check):
    setattr(rig.p, check, _boom)
    rig.p._tick(10000.0)
    assert rig.runs == [True]


@pytest.mark.parametrize("check", CHECKS)
def test_the_checks_after_a_failing_one_still_run(rig, check):
    ran = []
    for name in CHECKS:
        setattr(rig.p, name, (lambda n=name: ran.append(n)))
    setattr(rig.p, check, _boom)
    rig.p._tick(10000.0)
    assert set(ran) == set(CHECKS) - {check}


def test_a_lasting_fault_is_logged_once_with_its_traceback(rig):
    rig.p._check_en_suite_morning = _boom
    for i in range(5):
        rig.p._tick(10000.0 + 30 * i)
    errors = [(m, lvl) for m, lvl in rig.lines if "morning check failed" in m]
    assert len(errors) == 1
    assert errors[0][1] == "ERROR" and "Traceback" in errors[0][0]


def test_a_different_fault_is_logged_again(rig):
    rig.p._check_timed_boost_expiry = _boom
    rig.p._tick(10000.0)

    def other():
        raise KeyError("timed_boost_active")
    rig.p._check_timed_boost_expiry = other
    rig.p._tick(10030.0)
    assert len([m for m, _ in rig.lines if "boost expiry check failed" in m]) == 2


def test_the_timetable_check_is_guarded_too(rig):
    """It takes the time as an argument, so it is not in CHECKS."""
    def boom(now):
        raise RuntimeError("no timetable")
    rig.p._maybe_check_timetable = boom
    for i in range(3):
        rig.p._tick(10000.0 + 30 * i)
    assert rig.runs == [True]
    assert len([m for m, _ in rig.lines if "timetable check failed" in m]) == 1


def test_the_morning_and_en_suite_window_faults_are_remembered_apart(rig):
    """Before 1.25.7 both logged as [EnSuiteMorning]; one key for both would let one
    fault hide the other."""
    rig.p._check_en_suite_morning = _boom
    rig.p._check_en_suite_window_interlock = _boom
    rig.p._tick(10000.0)
    rig.p._tick(10030.0)
    failed = [m for m, _ in rig.lines if "failed" in m]
    assert len(failed) == 2
    assert any(m.startswith("[EnSuiteMorning]") for m in failed)
    assert any(m.startswith("[EnSuiteWindow]") for m in failed)


def test_recovery_is_said_once(rig):
    rig.p._check_en_suite_drying = _boom
    rig.p._tick(10000.0)
    rig.p._check_en_suite_drying = lambda: None
    rig.p._tick(10030.0)
    rig.p._tick(10060.0)
    assert len([m for m, _ in rig.lines if "drying-run check is working again" in m]) == 1


def test_stop_thread_is_never_swallowed(rig, plugin_mod, monkeypatch):
    """Indigo stops a plugin by raising StopThread; catching it would hang shutdown."""
    class StopThread(Exception):
        pass
    monkeypatch.setattr(plugin_mod.Plugin, "StopThread", StopThread, raising=False)

    def stop():
        raise StopThread()
    rig.p._check_summer_force_expiry = stop
    with pytest.raises(StopThread):
        rig.p._tick(10000.0)
