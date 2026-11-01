#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_actions_and_menus.py
# Description: Every method the dialog XML names must exist on the Plugin class, and every
#              plugin event the code fires must be declared in Events.xml (and the reverse).
#              Indigo only looks a CallbackMethod up when somebody picks that action or menu
#              item, so a renamed method fails silently until then. Reads the source with
#              ast; imports nothing.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import ast
import glob
import os
import re
import xml.etree.ElementTree as ET

REPO   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = sorted(glob.glob(os.path.join(REPO, "*.indigoPlugin")))[0]
SERVER = os.path.join(BUNDLE, "Contents", "Server Plugin")
PLUGIN_PY = os.path.join(SERVER, "plugin.py")

# XML elements whose text, or attributes, name a method on the Plugin class.
_METHOD_ELEMENTS   = ("CallbackMethod", "ButtonPressed")
_METHOD_ATTRIBUTES = ("method", "callback", "callbackMethod")


def _plugin_methods():
    with open(PLUGIN_PY, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Plugin":
            return {n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    raise AssertionError("no class Plugin in plugin.py")


def _named_methods():
    """(file, method) for every method the dialog XML names."""
    out = []
    for path in sorted(glob.glob(os.path.join(SERVER, "*.xml"))):
        root = ET.parse(path).getroot()
        for el in root.iter():
            if el.tag in _METHOD_ELEMENTS and (el.text or "").strip():
                out.append((os.path.basename(path), el.text.strip()))
            for attr in _METHOD_ATTRIBUTES:
                if el.get(attr):
                    out.append((os.path.basename(path), el.get(attr)))
    return out


def _all_source():
    text = ""
    for path in glob.glob(os.path.join(SERVER, "*.py")):
        if os.path.basename(path).startswith("test_"):
            continue
        with open(path, encoding="utf-8") as fh:
            text += fh.read()
    return text


def test_the_xml_names_some_methods():
    """A scan that finds nothing would pass the test below without checking anything."""
    assert len(_named_methods()) >= 10


def test_every_callback_named_in_the_xml_exists_on_the_plugin():
    methods = _plugin_methods()
    missing = [f"{f}: {m}" for f, m in _named_methods() if m not in methods]
    assert not missing, "XML names methods plugin.py does not define:\n" + "\n".join(missing)


def test_action_and_menu_ids_are_unique():
    for name, tag in (("Actions.xml", "Action"), ("MenuItems.xml", "MenuItem")):
        root = ET.parse(os.path.join(SERVER, name)).getroot()
        ids = [el.get("id") for el in root.iter(tag)]
        assert len(ids) == len(set(ids)), f"{name}: duplicate {tag} ids"


def _declared_events():
    root = ET.parse(os.path.join(SERVER, "Events.xml")).getroot()
    return {el.get("id") for el in root.iter("Event")}


def _fired_events():
    src = _all_source()
    return set(re.findall(r'(?:_fire_event|event_callback)\(\s*["\'](\w+)["\']', src))


def test_every_fired_event_is_declared():
    """Firing an id Events.xml does not declare reaches no trigger, silently."""
    undeclared = _fired_events() - _declared_events()
    assert not undeclared, f"fired but not in Events.xml: {sorted(undeclared)}"


def test_every_declared_event_is_fired_somewhere():
    """An event in the Indigo trigger list that the code never fires is a trigger that
    can never go off - a user could rely on it for an alert that never comes."""
    never = _declared_events() - _fired_events()
    assert not never, f"in Events.xml but never fired: {sorted(never)}"
