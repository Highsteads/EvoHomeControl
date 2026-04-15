#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    schedules.py
# Description: 24-hour temperature schedule arrays and per-room limits for EvoHomeControl
# Author:      CliveS & Claude Sonnet 4.6
# Date:        15-04-2026
# Version:     1.0

# ---------------------------------------------------------------------------
# 24-HOUR TEMPERATURE SCHEDULES
# ---------------------------------------------------------------------------
# Each array has 24 entries — one target temperature (°C) per hour of the day.
# Index 0 = midnight, index 23 = 11pm.
# Guest schedules override the main schedule when guest mode is active for
# the relevant room.
# ---------------------------------------------------------------------------

Clock_Time        = [ 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,15,16,17,18,19,20,21,22,23]

Bathroom          = [18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18]
Bathroom_Guest    = [10,16,16,16,17,20,21,21,21,21,17,17,17,17,17,17,17,17,17,17,17,17,16,16]

Bedroom_1         = [16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16]

Bedroom_2         = [16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16]
Bedroom_2_Guest   = [17,17,17,17,17,17,17,17,17,17,17,17,17,17,17,17,17,17,17,17,18,18,18,17]

Bedroom_3         = [14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14]
Bedroom_3_Guest   = [14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14]

# En Suite: background floor heating means TRV contribution is modest.
# Morning period (06:00-09:59) is overridden to 22°C by en_suite_special_rules()
# when the morning schedule is active and the window is closed.
En_Suite          = [18,18,18,19,19,19,19,20,20,20,18,18,18,18,18,18,18,18,18,18,20,20,18,18]

Conservatory      = [12,12,12,12,12,12,19,19,19,19,19,20,20,20,20,20,19,18,18,12,12,12,12,12]

Dining_Room       = [16,16,16,16,16,16,18,21,20,20,20,20,20,20,20,20,21,21,21,21,16,16,16,16]

Hall_Bedroom      = [17,17,17,17,17,18,18,18,18,18,18,18,18,18,18,18,18,19,19,18,18,18,17,17]

Hall_Kitchen      = [17,17,17,18,18,18,18,18,18,18,18,18,18,18,18,18,18,19,19,19,19,18,17,17]

Living_Room_Door  = [16,16,16,16,16,17,17,17,17,18,18,18,20,20,20,20,20,20,20,21,21,20,16,16]
Living_Room_Front = [16,16,16,16,16,17,17,17,17,18,18,18,20,20,20,20,20,20,20,21,21,20,16,16]

Utility_Room      = [14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14,14]

# ---------------------------------------------------------------------------
# MAXIMUM TEMPERATURE LIMITS
# ---------------------------------------------------------------------------
# Rooms listed here have their setpoints capped to prevent overheating.
# Bedrooms are capped to prevent uncomfortable sleeping temperatures.
# Applied AFTER all other adjustments (boost, offset, etc.).

MAX_TEMP_LIMITS = {
    "Bedroom 1":    16,
    "Bedroom 2":    16,
    "Bedroom 3":    14,  # Fixed at 14°C — server room, no heating needed
    "Utility Room": 16,
}

MAX_TEMP_LIMITS_GUEST = {
    "Bedroom 1": 18,
    "Bedroom 2": 18,
    "Bedroom 3": 14,  # Fixed at 14°C even in guest mode — server room
}

# ---------------------------------------------------------------------------
# BOOST AMOUNTS (°C added to scheduled setpoint when boost mode is active)
# ---------------------------------------------------------------------------
# Rooms NOT listed here receive NO boost.
# Bedrooms intentionally excluded (already at comfortable temps).

BOOST_AMOUNTS = {
    "Conservatory":      3,
    "Dining Room":       2,
    "Hall Kitchen":      2,
    "Living Room Door":  2,
    "Living Room Front": 2,
}

# ---------------------------------------------------------------------------
# TIMED BOOST ROOMS
# ---------------------------------------------------------------------------
# The 4 rooms targeted by the 1h/2h timed boost actions.
# Conservatory uses the global boost only (not timed boost).

TIMED_BOOST_ROOMS = {
    "Dining Room",
    "Living Room Door",
    "Living Room Front",
    "Hall Kitchen",
}
