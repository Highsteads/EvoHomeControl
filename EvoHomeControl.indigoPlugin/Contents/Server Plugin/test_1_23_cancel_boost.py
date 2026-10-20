#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_1_23_cancel_boost.py
# Description: Cancel boost holds every radiator at 12 until its next plan change.
# Author:      CliveS & Codex GPT-6
# Date:        20-10-2026 UK
# Version:     1.0

import json
import threading
import types
from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from test_1_18_review import plugin_mod, hl
from test_1_22_open_window import _Rooms


def controller(hours=1):
    p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
    p._cycle_lock = threading.Lock()
    p.store = {"timed_boost_active": True, "timed_boost_hours": hours,
               "timed_boost_expiry": None, "en_suite_morning_active": False,
               "last_setpoints": {}, "last_messages": {}}
    p._save_state = Mock()
    p._save_setpoint_cache = Mock()
    p._fire_event = Mock()
    p._log_boost_revert_summary = Mock()
    return p


@pytest.mark.parametrize("hours", [1, 2])
def test_cancel_action_sends_twelve_to_every_radiator_and_saves_first(hours):
    p = controller(hours)
    ids = plugin_mod.ALL_RADIATOR_IDS
    plan = [16] * 24
    plan[17:] = [20] * 7
    zones = {i: types.SimpleNamespace(id=i, states={}) for i in ids}
    now = datetime(2026, 10, 20, 15, 30, tzinfo=hl.HOUSE_TZ).timestamp()
    calls = []
    def send(dev, target, until):
        assert p._save_state.called
        calls.append((dev.id, target, until))
    with patch.object(plugin_mod, "_room_plans", return_value=[(i, str(i), plan) for i in ids]), \
         patch.object(plugin_mod.indigo, "devices", zones), \
         patch.object(hl, "send_setpoint", side_effect=send), \
         patch.object(plugin_mod.time, "time", return_value=now):
        p.actionCancelTimedBoost(None)
    assert set(calls) == {(i, 12.0, "2026-10-20 17:00") for i in ids}
    assert len(calls) == len(ids) == 12
    assert not p.store["timed_boost_active"]
    assert len(p.store["cancel_boost_holds"]) == 12
    assert p.store["cycle_requests"] == 1


def test_natural_expiry_does_not_turn_every_room_down():
    p = controller()
    with patch.object(hl, "send_setpoint") as send:
        p._cancel_timed_boost("timer expired")
    send.assert_not_called()
    assert not p.store.get("cancel_boost_holds")
    p._log_boost_revert_summary.assert_called_once()


def test_hold_retries_a_different_setpoint_and_ends_on_time():
    dev = types.SimpleNamespace(id=1, states={"setpointHeat": 22})
    holds = {"1": 10000}
    with patch.object(hl, "send_setpoint") as send:
        assert hl.apply_cancel_hold(dev, holds, now=9000)
        assert send.call_args.args == (dev, 12.0)
        assert not hl.apply_cancel_hold(dev, holds, now=10000)
    assert not holds


@pytest.mark.parametrize("month,day,expected_hours", [(3,29,2), (10,25,4)])
def test_plan_boundary_crosses_clock_changes(month, day, expected_hours):
    now = datetime(2026, month, day, 0, 0, tzinfo=hl.HOUSE_TZ).timestamp()
    plan = [12] * 3 + [20] * 21
    end = hl.next_plan_change(plan, now)
    assert end - now == expected_hours * 3600
    assert hl.hold_wire_time(end).endswith("03:00")


def test_plan_change_after_midnight_is_not_cut_short():
    now = datetime(2026,10,20,23,30,tzinfo=hl.HOUSE_TZ).timestamp()
    plan = [12] * 6 + [20] * 16 + [12] * 2
    assert hl.hold_wire_time(hl.next_plan_change(plan, now)) == "2026-10-21 06:00"


def test_saved_hold_round_trip(tmp_path):
    p = controller()
    p.data_dir = str(tmp_path)
    end = 20000
    key = str(plugin_mod.ALL_RADIATOR_IDS[0])
    p.store["cancel_boost_holds"] = {key: end}
    p._save_state_locked()
    data = json.loads((tmp_path / "plugin_state.json").read_text())
    assert hl.valid_cancel_holds(data["cancel_boost_holds"], now=10000) == {key:end}
    assert hl.valid_cancel_holds(data["cancel_boost_holds"], now=end) == {}


class TestWindowPriority(_Rooms):
    def test_open_window_still_wins_over_cancel_hold(self):
        self._zone()
        self._contact(hl.DEV_BEDROOM_2_WINDOW_ID, True)
        import time
        self._run(cancel_boost_holds={str(hl.DEV_BEDROOM_2_ID):time.time()+3600})
        assert self.written == [(hl.DEV_BEDROOM_2_ID, hl.RADIATORS_OFF_TEMP)]

    def test_closed_room_holds_twelve_instead_of_schedule(self):
        self._zone()
        self._contact(hl.DEV_BEDROOM_2_WINDOW_ID, False)
        import time
        self._run(cancel_boost_holds={str(hl.DEV_BEDROOM_2_ID):time.time()+3600})
        assert self.written == [(hl.DEV_BEDROOM_2_ID, 12.0)]


def test_restart_loads_saved_hold_and_new_boost_clears_it(tmp_path):
    import time
    p = controller()
    p.data_dir = str(tmp_path)
    key = str(plugin_mod.ALL_RADIATOR_IDS[0])
    p.store["cancel_boost_holds"] = {key: time.time() + 3600}
    p._save_state_locked()
    restored = controller()
    restored.data_dir = str(tmp_path)
    restored._load_state()
    assert restored.store["cancel_boost_holds"] == p.store["cancel_boost_holds"]
    restored._summer_lockout_active = lambda: False
    restored._start_timed_boost(2)
    assert restored.store["cancel_boost_holds"] == {}


def test_one_failed_radiator_does_not_skip_the_other_eleven():
    p = controller()
    ids = plugin_mod.ALL_RADIATOR_IDS
    zones = {i: types.SimpleNamespace(id=i, states={}) for i in ids}
    calls = []
    def send(dev, *args, **kwargs):
        calls.append(dev.id)
        if dev.id == ids[0]:
            raise RuntimeError("test radio unavailable")
    with patch.object(plugin_mod, "_room_plans", return_value=[(i,str(i),[16]*24) for i in ids]), \
         patch.object(plugin_mod.indigo, "devices", zones), \
         patch.object(hl, "send_setpoint", side_effect=send):
        p.actionCancelTimedBoost(None)
    assert calls == list(ids)
    assert len(p.store["cancel_boost_holds"]) == 12
