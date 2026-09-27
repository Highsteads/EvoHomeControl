---
title: Actions and triggers
nav_order: 8
---

# Actions and triggers

## Actions

These can go in an action group, a schedule, a trigger or a control page button. They are listed with the Device Actions when you add an action, and none of them needs a device.

| Action | What it does |
|---|---|
| **Start Timed Boost (1 hour)** | Adds two degrees to the Dining Room, Hall Kitchen, Living Room Door and Living Room Front for an hour. Refused during the summer shut-off. |
| **Start Timed Boost (2 hours)** | The same, for two hours. |
| **Cancel Timed Boost** | Ends a timed boost now. |
| **Force Heating On (24 hours)** | Brings back normal heating for 24 hours during the summer shut-off. |
| **Cancel Forced Heating** | Ends the 24 hours early and puts the summer shut-off back. |
| **Show Summer Shut-off Status** | Writes the state of the summer shut-off to the Event Log. |
| **Run Heating Cycle Now** | Runs a heating check within 30 seconds rather than waiting for the next one. |
| **Set Away Mode** | Sets the Away variable. Choose **Active (14°C all rooms)** or **Inactive (resume schedule)**. It runs a heating check straight away. |
| **Start En Suite Drying Run (30 minute test)** | Starts a half-hour drying run now, whatever the time. |
| **Stop En Suite Drying Run** | Ends a drying run now. |
| **Show En Suite Drying Run Status** | Writes the drying run's settings and state to the Event Log. |

The [Modes and boosts](modes-and-boosts.md), [summer shut-off](summer-shut-off.md) and [En Suite](en-suite.md) pages explain each of these in full.

## Triggers

To run something when one of these happens, create a new trigger, set its type to **EvoHome Heating Controller**, and choose the event.

| Event | When it runs |
|---|---|
| **Critical Overheat Alert** | When an overheating alert is sent for a room. |
| **Room All Clear (back to target)** | When a room that had an alert sent has been back to normal for 30 minutes. |
| **Timed Boost Started** | When a timed boost starts. |
| **Timed Boost Ended** | When a timed boost runs out or is cancelled. |
| **Snow Forecast Detected** | When snow first appears in the forecast, if the snow boost is switched on. |
| **En Suite Morning Started** | When the En Suite morning schedule starts. |
| **En Suite Morning Cancelled** | When the morning schedule ends at 10am, or is skipped because it is a warm morning. It does not run when opening the window ends the schedule. |
| **Summer Force-On Started** | When a 24-hour Force Heating On starts. |
| **Summer Force-On Ended** | When the 24 hours run out or are cancelled. |
| **En Suite Drying Run Started** | When a drying run starts, including a test run. |
| **En Suite Drying Run Ended** | When a drying run finishes, for whatever reason. |

For example, a trigger on **Critical Overheat Alert** could flash a light or announce it on a speaker, for a house where not everyone has Pushover.

The **Heating Controller** device's states can be used in triggers as well, such as **Active Mode** changing — see [The Heating Controller device](devices.md).
