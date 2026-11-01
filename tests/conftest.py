#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    conftest.py
# Description: Test seam for the tests/ folder. Puts the bundle's Server Plugin folder on
#              sys.path and makes sure an `indigo` stand-in exists BEFORE plugin.py or
#              heating_logic.py is imported, so they load with no Indigo server.
#              The bundle's own tests (test_timed_overrides.py and friends) install the same
#              kind of stand-in, so this one only ADDS attributes that are missing and never
#              replaces a module object another test already bound to - swapping it would
#              leave heating_logic reading a stub nobody updates (see test_heating_logic.py).
#              Only names plugin code actually touches, and only real Indigo names.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import glob
import os
import sys
import types

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUNDLES  = sorted(glob.glob(os.path.join(REPO_ROOT, "*.indigoPlugin")))
SERVER_PLUGIN = os.path.join(_BUNDLES[0], "Contents", "Server Plugin") if _BUNDLES else ""

if SERVER_PLUGIN and SERVER_PLUGIN not in sys.path:
    sys.path.insert(0, SERVER_PLUGIN)


class _FakeServer:
    """indigo.server: log lines are kept so a test can read what was said."""

    def __init__(self):
        self.lines = []

    def log(self, message, type=None, level=None, isError=False):
        self.lines.append((message, level))

    def getInstallFolderPath(self):
        return "/tmp/evohome-test"

    def getPlugin(self, plugin_id):
        return None


class _FakePluginBase:
    """indigo.PluginBase, minimal."""

    class StopThread(Exception):
        pass

    def __init__(self, *args, **kwargs):
        pass


def _install_indigo():
    ind = sys.modules.get("indigo") or types.ModuleType("indigo")
    if not hasattr(ind, "server") or not hasattr(ind.server, "getInstallFolderPath"):
        ind.server = _FakeServer()
    for name, value in (
        ("PluginBase", _FakePluginBase),
        ("Dict",       dict),
        ("List",       list),
        ("devices",    {}),
        ("variables",  {}),
        ("thermostat", types.SimpleNamespace(setHeatSetpoint=lambda *a, **k: None,
                                             setHvacMode=lambda *a, **k: None)),
        ("device",     types.SimpleNamespace(turnOn=lambda *a, **k: None,
                                             turnOff=lambda *a, **k: None)),
        ("trigger",    types.SimpleNamespace(execute=lambda *a, **k: None)),
        ("kHvacMode",  types.SimpleNamespace(Heat="Heat", Off="Off")),
    ):
        if not hasattr(ind, name):
            setattr(ind, name, value)
    sys.modules["indigo"] = ind
    return ind


INDIGO = _install_indigo()


@pytest.fixture
def indigo_mod():
    return sys.modules["indigo"]


@pytest.fixture
def hl():
    """heating_logic, with its module-level send records cleared before and after."""
    import heating_logic
    for d in (heating_logic._SENT, heating_logic._REFUSED, heating_logic._OVERRIDE_WARNED,
              heating_logic._REFUSAL_ANNOUNCED):
        d.clear()
    yield heating_logic
    heating_logic.set_override_minutes(0)
    for d in (heating_logic._SENT, heating_logic._REFUSED, heating_logic._OVERRIDE_WARNED,
              heating_logic._REFUSAL_ANNOUNCED):
        d.clear()


@pytest.fixture
def plugin_mod():
    import plugin
    return plugin
