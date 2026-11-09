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


TARGETS = {"Living Room Front": 22.0, "Dining Room": 22.0, "Conservatory": 22.0, "Hall Kitchen": 22.0}
ROOMS = [(11, "Living Room Front"), (9, "Dining Room"), (2, "Conservatory"),
         (3, "Hall Kitchen"), (5, "Bedroom 1")]


def test_boost_outcome_says_who_got_it_and_why_not(plugin_mod):
    out = plugin_mod.boost_outcome(
        ROOMS,
        {"Living Room Front": 22.0, "Dining Room": 16.0, "Conservatory": 12.0},
        {"Living Room Front": 12, "Dining Room": 23, "Conservatory": 5},
        TARGETS, "2026-11-09T16:00:00+00:00")
    assert set(out) == {"11", "9", "2", "3"}, "only boost rooms"
    assert out["11"]["held"] == "" and out["11"]["requested"] == 22.0
    assert out["9"]["held"] == "it is already warm from the sun or the rest of the house"
    assert out["2"]["held"] == "its sliding door is shut"
    assert out["3"]["requested"] is None and out["3"]["held"] == "", "not reached yet"


def test_boost_outcome_unknown_code_has_plain_reason(plugin_mod):
    out = plugin_mod.boost_outcome([(9, "Dining Room")], {"Dining Room": 18.0},
                                   {"Dining Room": 99}, TARGETS, "t")
    assert out["9"]["held"] == "the heating rules"


def test_outcome_cleared_on_start_and_saved(plugin_mod):
    p = object.__new__(plugin_mod.Plugin)
    p.store = {"timed_boost_outcome": {"11": {"room": "old"}}}
    p._summer_lockout_active = lambda: False
    p._save_state = Mock()
    p._fire_event = Mock()
    p._start_timed_boost(1)
    assert p.store["timed_boost_outcome"] == {}


def test_record_outcome_only_while_boosting(plugin_mod, monkeypatch):
    # Other tests stub the schedules module's plans, so supply the room list here.
    monkeypatch.setattr(plugin_mod, "_room_plans",
                        lambda: tuple((i, r, None) for i, r in ROOMS))
    monkeypatch.setattr(plugin_mod.schedules, "TIMED_BOOST_ROOMS", set(TARGETS), raising=False)
    monkeypatch.setattr(plugin_mod.schedules, "BOOST_TARGETS", TARGETS, raising=False)
    p = object.__new__(plugin_mod.Plugin)
    p._save_state = Mock()
    p.store = {"timed_boost_active": False, "timed_boost_outcome": {"x": 1}}
    p._record_boost_outcome()
    assert p.store["timed_boost_outcome"] == {}
    p.store.update(timed_boost_active=True, last_setpoints={"Living Room Front": 22.0},
                   last_messages={"Living Room Front": 12})
    p._record_boost_outcome()
    rooms = {v["room"] for v in p.store["timed_boost_outcome"].values()}
    assert rooms == set(TARGETS)
