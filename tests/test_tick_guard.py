#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_tick_guard.py
# Description: 1.25.4, review finding 5: a fault in one of _tick's per-poll checks (summer
#              force-on, En Suite morning, En Suite drying, boost expiry) must not stop the
#              heating cycle, must be logged once rather than every 30 seconds, and its
#              recovery must be said once.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import types

import pytest

CHECKS = ("_check_summer_force_expiry", "_check_en_suite_morning",
          "_check_en_suite_drying", "_check_timed_boost_expiry")


@pytest.fixture
def rig(plugin_mod, indigo_mod, monkeypatch):
    """A Plugin built without __init__, as test_1_18_review.py does, with every per-tick
    check stubbed out and the heating cycle counted."""
    lines = []
    monkeypatch.setattr(plugin_mod, "_log", lambda msg, level="INFO": lines.append((msg, level)))
    p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
    p.pluginPrefs = {}
    p.store = {"last_heating_cycle": 0.0, "cycle_requests": 0, "cycle_requests_served": 0}
    for name in CHECKS + ("_check_en_suite_window_interlock", "_check_contacts_changed"):
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
