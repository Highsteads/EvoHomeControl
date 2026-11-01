#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_setpoint_cache_load.py
# Description: 1.25.5, review finding 6: an unreadable setpoint_cache.json is reported once
#              and kept aside, never ignored without a word; a missing one is a quiet fresh
#              start; good files in both layouts still load.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import json
import os
import types

import pytest


@pytest.fixture
def rig(plugin_mod, hl, tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(plugin_mod, "_log", lambda msg, level="INFO": lines.append((msg, level)))
    p = plugin_mod.Plugin.__new__(plugin_mod.Plugin)
    p.store = {"last_setpoints": {}, "last_messages": {}}
    return types.SimpleNamespace(p=p, hl=hl, path=str(tmp_path / "setpoint_cache.json"),
                                 lines=lines)


def _warnings(rig):
    return [m for m, lvl in rig.lines if lvl == "WARNING"]


def test_no_file_is_a_quiet_fresh_start(rig):
    rig.p._load_setpoint_cache(rig.path)
    assert rig.lines == [] and rig.p.store["last_setpoints"] == {}


def test_a_corrupt_file_is_reported_once_and_kept_aside(rig):
    with open(rig.path, "w") as fh:
        fh.write('{"setpoints": {"Bathroom": 19.0}, "sent": {"12')   # cut off mid-write
    rig.p._load_setpoint_cache(rig.path)
    warned = _warnings(rig)
    assert len(warned) == 1
    assert "could not be read" in warned[0] and "by hand" in warned[0]
    with open(rig.path + ".unreadable") as fh:
        assert fh.read().startswith('{"setpoints"')
    assert rig.p.store["last_setpoints"] == {}


@pytest.mark.parametrize("content", ['["not", "a", "dict"]', '"text"',
                                     '{"setpoints": [1, 2], "messages": {}}'])
def test_valid_json_in_the_wrong_layout_is_reported(rig, content):
    with open(rig.path, "w") as fh:
        fh.write(content)
    rig.p._load_setpoint_cache(rig.path)
    assert len(_warnings(rig)) == 1
    assert rig.p.store["last_setpoints"] == {}


def test_the_current_layout_loads_with_the_sent_record(rig):
    with open(rig.path, "w") as fh:
        json.dump({"setpoints": {"Bathroom": 19.0}, "messages": {"Bathroom": 11},
                   "sent": {"123": [19.0, "2026-11-01T10:00:00", 1793527200.0]}}, fh)
    rig.p._load_setpoint_cache(rig.path)
    assert rig.lines == []
    assert rig.p.store["last_setpoints"] == {"Bathroom": 19.0}
    assert rig.p.store["last_messages"] == {"Bathroom": 11}
    assert rig.hl._SENT[123][0] == 19.0


def test_the_old_layout_still_loads_quietly(rig):
    with open(rig.path, "w") as fh:
        json.dump({"Bathroom": 18.5}, fh)
    rig.p._load_setpoint_cache(rig.path)
    assert rig.lines == [] and rig.p.store["last_setpoints"] == {"Bathroom": 18.5}


def test_a_file_that_cannot_be_opened_is_reported(rig):
    os.mkdir(rig.path)            # a folder where the file should be: IsADirectoryError
    rig.p._load_setpoint_cache(rig.path)
    assert len(_warnings(rig)) == 1
