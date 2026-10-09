---
title: The summer shut-off
nav_order: 5
---

# The summer shut-off

Through the warmer months there is no need to heat the house, so the plugin can turn the whole house off between two dates each year.

## What it does

While the shut-off is on:

- Every radiator is held at **8 degrees**, which keeps the valves shut on a summer day but still gives some protection if there is a cold snap. The hold is set to end at midnight at the start of the day heating returns, so if Indigo is not running on that day the house goes back to its Evohome timetable on time. If a radiator is changed by hand, at the controller, on its valve, in the app or through Indigo, the plugin leaves it until the room's plan next changes, or midnight, and then puts it back at 8 degrees. Any other change is put back at the next check.
- The **En Suite underfloor heating** thermostat is turned off.
- The normal heating check stops — the room plans, the weather adjustment, the modes and the overheating checks all wait until the shut-off ends.
- The En Suite morning schedule does not run, and a timed boost will not start.
- The En Suite [drying run](en-suite.md) is the one exception. It only runs during the shut-off.

The Event Log has one line when the shut-off starts, one when it ends, and one each time the plugin restarts while it is on. It does not repeat itself in between.

## The dates

It is switched on to start with, and runs from **1 June** until heating returns on **30 September**. The return date is the day heating comes back, so with those dates the house is off from 1 June to 29 September, and back to normal on 30 September.

Change the dates in **Plugins → EvoHome Heating Controller → Configure**, under **SUMMER SHUT-OFF**. A change takes effect as soon as you click Save. The dates can cross the new year — 1 November to 1 March works as you would expect.

To heat the house all year round, untick **Enable summer shut-off**.

## Heating for a day

If you want heat during the shut-off — a cold spell, or guests — choose **Plugins → EvoHome Heating Controller → Force Heating On (24 hours)**, or use the action of the same name. For the next 24 hours the house runs exactly as it does in winter, and then the shut-off returns by itself.

- **Cancel Forced Heating** ends it early.
- The 24 hours carry on after the plugin or Indigo restarts.
- It only works while the summer shut-off is switched on. Otherwise there is nothing to override, and the Event Log says so.
- The En Suite drying run stands down while it lasts.

## Checking where it stands

**Plugins → EvoHome Heating Controller → Show Summer Shut-off Status** writes to the Event Log whether the shut-off is on now, its dates, and how long a 24-hour override has left. The [Heating Controller device](devices.md) shows the same in its **Summer Shut-off Status** state.
