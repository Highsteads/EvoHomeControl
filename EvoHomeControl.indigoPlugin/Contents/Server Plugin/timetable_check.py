#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    timetable_check.py
# Description: Compare the timetable stored on the Evohome controller (read daily by RAMSES
#              ESP 1.13.0 into each zone's timetableData state) with this plugin's hourly
#              plans. That timetable is what each room falls back to if Indigo stops (1.13.0
#              timed overrides), so it must not drift from the plans. No indigo import.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0

import json

SLOT_MINUTES  = 10
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES
DAY_NAMES     = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MATCH_C       = 0.05


def parse(text):
    """{day: [(minutes, setpoint_c), ...]} from RAMSES ESP's timetableData, or None."""
    if not text:
        return None
    try:
        data = json.loads(text)
        week = {int(d): sorted((int(m), float(sp)) for m, sp in points) for d, points in data.items()}
    except (ValueError, TypeError):
        return None
    return week if week else None


def controller_slots(week):
    """The setpoint in force in each 10-minute slot of the week, Monday midnight first.
    Before a day's first switchpoint the previous day's last one still holds."""
    last_of = {d: (week.get(d) or [None])[-1] for d in range(7)}
    slots = []
    for day in range(7):
        current, back = None, day
        for _ in range(7):
            back = (back - 1) % 7
            if last_of[back] is not None:
                current = last_of[back][1]
                break
        points = list(week.get(day) or [])
        for slot in range(SLOTS_PER_DAY):
            minute = slot * SLOT_MINUTES
            while points and points[0][0] <= minute:
                current = points.pop(0)[1]
            slots.append(current)
    return slots


def plan_slots(hours):
    """The same, from a 24-entry hourly plan that repeats every day."""
    return [float(hours[(slot * SLOT_MINUTES) // 60]) for _d in range(7) for slot in range(SLOTS_PER_DAY)]


def first_difference(hours, week):
    """None when the controller matches the plan everywhere, else
    (day, minutes, controller_value, plan_value) at the first slot that differs."""
    have, want = controller_slots(week), plan_slots(hours)
    for index, (h, w) in enumerate(zip(have, want)):
        if h is None or abs(h - w) > MATCH_C:
            day, slot = divmod(index, SLOTS_PER_DAY)
            return day, slot * SLOT_MINUTES, h, w
    return None


def clock(minutes):
    h, m = divmod(int(minutes), 60)
    if (h, m) == (0, 0):
        return "midnight"
    if (h, m) == (12, 0):
        return "noon"
    suffix = "am" if h < 12 else "pm"
    return f"{h % 12 or 12}{suffix}" if m == 0 else f"{h % 12 or 12}:{m:02d}{suffix}"


def describe_difference(room, diff):
    """One sentence, e.g. 'Dining Room: at 6:30am on Monday the controller has 21 degrees
    where the plan has 18.'"""
    day, minutes, have, want = diff
    have_text = "nothing" if have is None else f"{have:g} degrees"
    return (f"{room}: at {clock(minutes)} on {DAY_NAMES[day]} the controller has {have_text} "
            f"where the plan has {want:g}.")


def join_names(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
