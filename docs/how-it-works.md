---
title: How it works
nav_order: 3
---

# How it works

You do not need to know all of this to use the plugin. It is here so you can tell why a room is at the temperature it is.

## The heating check

Every five minutes, or every 10 or 15 if you choose, the plugin runs a heating check. It reads the outdoor temperature and the mode variables, works out the right temperature for each of the twelve rooms in turn, and sends any change to that room's radiator through the RAMSES ESP plugin.

It sets each radiator to a target for two hours at a time — Evohome calls this a **temporary override** — and renews it about once an hour, so while the plugin runs, the timetable in your Evohome controller does not run those radiators. If Indigo or the plugin stops, each radiator goes back to that timetable within two hours. You can change the two hours, or choose to hold the last setting indefinitely, in the [settings](settings.md). The summer 8 degree hold is always permanent.

Because that timetable is the fallback, the plugin checks it every morning at 4am against its own plans, room by room, using the copy RAMSES ESP reads from the controller each night. If a room differs, the Event Log says where and you get one Pushover message.

Between heating checks, the plugin looks every 30 seconds at the things that need a quicker answer: a boost or a 24-hour override running out, the En Suite's 6am start and 10am finish, and the En Suite window during a drying run.

If one room fails — a radiator missing from Indigo, say — the other rooms are still done. If a radiator has no temperature reading, that room is left at its last target for that check, rather than being treated as freezing. The same goes for a room the RAMSES ESP plugin has not heard from for 45 minutes, because its reading may be out of date: the plugin says so once in the Event Log, and again once the room is reporting.

## How each room's temperature is decided

For each room, the plugin starts from the room's plan and works down this list. Where two things apply, the one lower down the list changes the answer the one above gave.

1. **The room's plan.** The temperature for this hour from `schedules.py`, or the guest plan when that room has a guest.
2. **The weather.** One degree comes off above 8 degrees outside, and two above 9. When snow is forecast, a little is added — one degree to start with.
3. **Bedroom limits.** Bedroom 1, Bedroom 2 and the Utility Room go no higher than 16 degrees, or 18 for Bedroom 2 when it has a guest. Bedroom 3, which holds my computers, goes no higher than 14.
4. **Overheating.** If the room is too warm, its radiator is turned down, and nothing below this in the list changes that, except an open window or door, which takes it lower still. The section below explains it.
5. **The room's own rule.** The Conservatory is held at 12 degrees while its sliding door is shut, whatever its garden windows are doing. The Dining Room is held at 16 degrees while a garden window or the garden door is open, rather than going down to 8. The En Suite has its [morning schedule and drying run](en-suite.md).
6. **Away, windows and doors.** Away mode sets every room to 14 degrees, or 16 when it is below 3 degrees outside. An open window or door then takes the radiator down to 8 degrees, whether away mode is on or not. The Dining Room keeps the 16 degrees its own rule gave it. An open En Suite window switches the underfloor heating off whether away mode is on or not.
7. **Mild weather.** Above 14 degrees outside, the radiator goes down to 8 degrees.
8. **Boost.** The boost, or the timed boost, adds its two or three degrees, but not to a room with a window or outside door open, which keeps its open-window setting, and not while away mode is on or it is mild outside.
9. **Both out.** Takes four degrees off, except while away mode is on, when it is mild outside, or for a room with a window or door open.

The answer is rounded to the nearest half degree, which is as fine as Evohome goes, and kept between 8 and 30 degrees.

## Which sensors each room watches

| Room | Windows and doors it watches |
|---|---|
| Bathroom | The bathroom window |
| Bedroom 1, Bedroom 2, Bedroom 3 | Each bedroom's window |
| En Suite | The En Suite window |
| Conservatory | The two garden windows and the garden door, and its sliding door |
| Dining Room | The two garden windows and the garden door |
| Living Room Front, Living Room Door | The two living room windows |
| Utility Room | The utility room window and door |
| Hall Bedroom, Hall Kitchen | None |

## Stopping a room overheating

A radiator is still warm for a while after its valve shuts, so a room that is heated right up to its target will overshoot. The plugin watches how quickly each room is warming, and turns the radiator down by six degrees, never below 12, when the room:

- is more than a quarter of a degree above its target, or
- is warming fast and is almost at its target, or
- is still warming and is within a set margin of its target — half a degree for most rooms, up to 0.8 of a degree for the rooms that overshoot most, and none for the Bathroom and En Suite.

It turns the radiator back up once the room has stopped warming and settled back near its target.

If a room stays warm after its radiator has been turned down for three checks in a row, the warmth is coming from the sun or from inside the house, not the radiator. The plugin's log calls that **Above Target (solar gain)** rather than **Overheat**.

### Overheating alerts

If a room is six degrees or more above its target, or four degrees or more above it for six hours, the plugin sends a Pushover message and an email to warn that a radiator valve may be stuck. It does not send one when it is above 12 degrees outside, or when the warmth is coming from the sun. Once the room has been back to normal for 30 minutes, an all-clear follows.

Bedroom 3 is left out of the alerts, because its computers keep it warm whatever the radiator does.

## The outdoor temperature

The plugin takes the outdoor temperature from the first of these it can read:

1. Your **Ecowitt outdoor sensor**, if you have set one, unless **Force OWM temperature** is ticked. A reading that has not changed for 30 minutes is not used, because the station has probably stopped.
2. **OpenWeatherMap**, which the plugin asks for the weather at most once every 15 minutes. Weather more than three hours old is not used.
3. The **Fallback temperature** in the settings, 6 degrees to start with.

OpenWeatherMap also supplies the forecast the snow boost looks at, and the wind, cloud and sunrise details in the hourly report.

During the [summer shut-off](summer-shut-off.md) the heating check stops, and so does the plugin's asking OpenWeatherMap for new weather.

## What goes in the logs

The Indigo Event Log only has the things worth knowing about: a boost starting and ending, the En Suite schedule and drying run starting and finishing, the summer shut-off starting and ending, the underfloor heating going off for an open window, the overheating alerts, and any warning or error.

Everything else goes to the plugin's own daily files, which are kept for 14 days:

- `radiator_` followed by the date — once an hour, a full report of the weather, the temperature records, which modes are on, and a line for every room with its temperature, its plan and what the plugin did. In between, a line whenever an open window or door, overheating or the En Suite changes a room.
- `changes_` followed by the date — one line for every change to a radiator's target, with the reason, such as **Window opened** or **Schedule step up**.

They are in your Indigo folder, such as `Indigo 2025.2`, under `Preferences`, `Plugins`, `com.clives.indigoplugin.evohomecontrol`, `logs`.

If you have Indigo variables named `solcast_today_kwh` and `solcast_tomorrow_kwh`, the hourly report shows those solar forecasts as well.
