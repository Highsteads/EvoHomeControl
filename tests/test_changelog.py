#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_changelog.py
# Description: The version history (docs/changelog.md, which the README links to) must have
#              an entry for the version Info.plist ships, and that entry must be the newest.
#              plugin.py's header history must mention it too. test_version_consistency.py
#              checks the README, but this repo keeps its release notes in docs/.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import glob
import os
import plistlib
import re

import pytest

REPO      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = os.path.join(REPO, "docs", "changelog.md")
PLIST     = sorted(glob.glob(os.path.join(REPO, "*.indigoPlugin", "Contents", "Info.plist")))[0]
PLUGIN_PY = os.path.join(os.path.dirname(PLIST), "Server Plugin", "plugin.py")


def _version():
    with open(PLIST, "rb") as fh:
        return plistlib.load(fh)["PluginVersion"]


def _entries():
    with open(CHANGELOG, encoding="utf-8") as fh:
        return re.findall(r"^##\s+v?(\d+(?:\.\d+)+)\b", fh.read(), re.M)


@pytest.mark.skipif(not os.path.isfile(CHANGELOG), reason="no docs/changelog.md")
def test_changelog_has_entries():
    assert _entries(), "no '## x.y.z' headings found in docs/changelog.md"


@pytest.mark.skipif(not os.path.isfile(CHANGELOG), reason="no docs/changelog.md")
def test_newest_changelog_entry_is_the_shipped_version():
    entries = _entries()
    assert entries and entries[0] == _version(), (
        f"newest changelog entry is {entries[:1]}, Info.plist says {_version()}")


@pytest.mark.skipif(not os.path.isfile(CHANGELOG), reason="no docs/changelog.md")
def test_no_version_is_listed_twice():
    entries = _entries()
    dupes = sorted({v for v in entries if entries.count(v) > 1})
    assert not dupes, f"listed more than once: {dupes}"


def test_plugin_py_header_history_mentions_this_version():
    with open(PLUGIN_PY, encoding="utf-8") as fh:
        head = fh.read(20000)
    assert re.search(r"^#\s+v" + re.escape(_version()) + r"\b", head, re.M), (
        f"plugin.py header has no '# v{_version()}' history line")
