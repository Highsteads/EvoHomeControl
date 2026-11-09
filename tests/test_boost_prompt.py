"""Explicit Boost acts promptly and does not inherit a below-target coast hold."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


def test_boost_requests_worker_cycle(plugin_mod):
    p = object.__new__(plugin_mod.Plugin)
    p.store = {}
    p._summer_lockout_active = lambda: False
    p._save_state = Mock()
    p._fire_event = Mock()
    p._start_timed_boost(1)
    assert p.store["cycle_requests"] == 1
    assert p.store["timed_boost_active"] is True
    assert p._save_state.call_count == 1


def test_request_wakes_loop_after_one_sleep(plugin_mod):
    p = object.__new__(plugin_mod.Plugin)
    p.store = {"cycle_requests": 0, "cycle_requests_served": 0}
    ticks, sleeps = [], []
    def tick(now):
        ticks.append(now)
        if len(ticks) == 2:
            raise p.StopThread()
    def sleep(seconds):
        sleeps.append(seconds)
        p._request_cycle()
    p._tick = tick
    p.sleep = sleep
    with pytest.raises(p.StopThread):
        p.runConcurrentThread()
    assert sleeps == [1]
    assert len(ticks) == 2


@pytest.mark.parametrize("temperature", [20.5, 21.4, 21.9])
def test_explicit_boost_releases_old_hold_below_target(hl, temperature):
    data = {"consecutive_cycles": 5, "off_since_cycle": 5,
            "is_coasting": True, "temp_history": [temperature - .2, temperature - .1]}
    monitor = SimpleNamespace(history={"Living Room Front": data}, initialize_room=lambda room: None)
    held, target, _ = hl.check_overheating(temperature, 22, "Living Room Front", monitor, boost=True)
    assert not held and target == 22
    assert data["consecutive_cycles"] == 0
    assert not data["is_coasting"]


def test_boost_does_not_disable_actual_overheating(hl):
    monitor = SimpleNamespace(history={"Living Room Front": {}}, initialize_room=lambda room: None)
    held, target, _ = hl.check_overheating(24, 22, "Living Room Front", monitor, boost=True)
    assert held and target < 22


def test_normal_schedule_retains_early_coast(hl):
    data = {"temp_history": [21.2, 21.3]}
    monitor = SimpleNamespace(history={"Living Room Front": data}, initialize_room=lambda room: None)
    held, _, _ = hl.check_overheating(21.5, 22, "Living Room Front", monitor)
    assert held
