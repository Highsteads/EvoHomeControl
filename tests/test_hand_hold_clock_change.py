#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_hand_hold_clock_change.py
# Description: 1.25.6, review finding 7: a temperature set by hand is held until the room's
#              plan next changes, worked out in REAL hours, so the clocks changing in March
#              and October neither shorten nor stretch it.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import types
from datetime import datetime
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
STAMP  = "%Y-%m-%d %H:%M:%S"


def _hand(changed, epoch=None):
    """A zone changed on the controller by hand to a timed setting."""
    states = {"setpointSource": "manual", "zoneMode": "temporary override",
              "setpointHeat": "22.0", "setpointChangedAt": changed.strftime(STAMP)}
    if epoch is not None:
        states["setpointChangedAtEpoch"] = str(int(epoch))
    return types.SimpleNamespace(id=1, name="Zone", states=states)


def test_spring_a_plan_hour_that_never_happens_does_not_end_the_hold(hl):
    """29-03-2026: 01:00 GMT becomes 02:00 BST, so the plan's 01:00 hour never happens.
    The plan reads 18 at midnight and 18 again at 02:00, so the room's target never
    moves and the hold runs on to midnight. It used to end at the missing 01:00."""
    plan = [18, 20] + [18] * 22
    dev  = _hand(datetime(2026, 3, 29, 0, 30))
    now  = datetime(2026, 3, 29, 2, 30, tzinfo=LONDON)
    assert hl.manual_hold_until(dev, plan, now=now) == datetime(2026, 3, 30, 0, 0)


def test_spring_a_real_change_still_ends_it(hl):
    plan = [18] * 7 + [20] * 17
    dev  = _hand(datetime(2026, 3, 29, 0, 30))
    assert hl.manual_hold_until(dev, plan, now=datetime(2026, 3, 29, 6, 59, tzinfo=LONDON)) \
        == datetime(2026, 3, 29, 7, 0)
    assert hl.manual_hold_until(dev, plan, now=datetime(2026, 3, 29, 7, 0, tzinfo=LONDON)) is None


def test_autumn_a_change_in_the_repeated_hour_is_read_as_the_recent_one(hl):
    """25-10-2026: 01:50 happens twice. Changed at 01:50 GMT (the second), with the plan
    moving at 02:00: at 01:55 GMT the hold has five minutes left, and ends at 02:00 GMT."""
    plan = [18, 18, 20] + [20] * 21
    dev  = _hand(datetime(2026, 10, 25, 1, 50))
    now  = datetime(2026, 10, 25, 1, 55, tzinfo=LONDON, fold=1)
    assert hl.manual_hold_until(dev, plan, now=now) == datetime(2026, 10, 25, 2, 0)
    after = datetime(2026, 10, 25, 2, 0, tzinfo=LONDON)
    assert hl.manual_hold_until(dev, plan, now=after) is None


def test_autumn_the_repeated_01_00_is_not_a_plan_change(hl):
    """01:00 GMT follows 01:00 BST: the same plan hour, so it does not end a hold made at
    00:30 when the plan only moves at 02:00."""
    plan = [18, 20, 22] + [22] * 21
    dev  = _hand(datetime(2026, 10, 25, 1, 10))          # 01:10 BST, the first one
    now  = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1)   # an hour and 20 later
    assert hl.manual_hold_until(dev, plan, now=now) == datetime(2026, 10, 25, 2, 0)


def test_ramses_own_epoch_is_preferred_to_the_text(hl):
    changed = datetime(2026, 11, 1, 8, 15, tzinfo=LONDON)
    dev = _hand(datetime(2026, 11, 1, 3, 0), epoch=changed.timestamp())   # text is wrong
    plan = [18] * 10 + [20] * 14
    assert hl.manual_hold_until(dev, plan, now=datetime(2026, 11, 1, 9, 0, tzinfo=LONDON)) \
        == datetime(2026, 11, 1, 10, 0)


def test_an_ordinary_day_is_unchanged(hl):
    plan = [18] * 22 + [16] * 2
    dev  = _hand(datetime(2026, 11, 3, 8, 15))
    assert hl.manual_hold_until(dev, plan, now=datetime(2026, 11, 3, 12, 0)) \
        == datetime(2026, 11, 3, 22, 0)
