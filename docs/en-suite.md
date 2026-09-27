---
title: The En Suite
nav_order: 6
---

# The En Suite

The En Suite has a radiator and electric underfloor heating, and two rules of its own: a warm morning in the heating season, and a drying run in the summer.

## The morning schedule

This runs every morning outside the [summer shut-off](summer-shut-off.md).

- **At 6am** the radiator is set to **22 degrees**, the underfloor heating switch is turned on, and the underfloor heating thermostat is set to heat to 14 degrees, so the floor looks after itself for the morning. If the plugin starts later than 6am, the schedule starts then instead.
- **Opening the window ends it for the day.** I take opening the window to mean the shower is over. At the next heating check, within five minutes, the radiator goes down while the window is open and the underfloor heating is switched off. After that the room follows its normal plan.
- **At 10am** it ends, and the underfloor heating switch is turned off.

### Warm mornings

When the schedule is due to start, the plugin checks the outdoor temperature. If it is **10 degrees or warmer**, the morning is skipped for the day — the radiator is held at 8 degrees until 10am, the underfloor heating is left off, and its thermostat is not touched. The 10 degrees is fixed in the plugin rather than a setting.

On a morning that starts cold and turns mild, the usual rule for mild weather still applies, so above 14 degrees outside the radiator goes down to 8 degrees.

## The drying run

Our En Suite sits above 70% humidity much of the time, and wet towels are the likely cause. The drying run holds the radiator warm on summer mornings, while the rest of the heating is off, to dry the room out.

### When it runs

It runs only **during the summer shut-off**. From the day normal heating returns, the morning schedule looks after the room, so the drying run stands down, and it picks up again when the next shut-off begins. It also stands down during a 24-hour **Force Heating On**.

Within that, a run starts when all of these are true:

- **Dry the En Suite out every morning** is ticked in the settings.
- The time is between the start and finish hours, **5am and 10am** to start with.
- It is **colder outside than the limit** you set, **12 degrees** to start with, unless you chose **No limit**.
- **Away mode** is off.
- The **En Suite window is shut**, and has not already been opened during a run that day.

The plugin asks again every 30 seconds, so a morning that only turns cold at 7am still gets a run.

### What it does

It holds the En Suite radiator at the temperature you choose, **22 degrees** to start with. It drives the radiator only, and never touches the underfloor heating, which stays yours to switch by hand.

The mild-weather rules that turn the rest of the house down do not apply to it, and a morning turning warmer does not stop a run that has started.

### When it stops

- At the finish hour, **10am** to start with.
- Within 30 seconds of the **window being opened**. It does not start again that day.
- Within 30 seconds of **away mode** being switched on. If it is switched off again before the finish hour, the run starts again.
- When normal heating returns for the winter, or a 24-hour **Force Heating On** starts.
- When you untick **Dry the En Suite out every morning**, or choose **Stop En Suite Drying Run**.

The radiator then goes back to what the rest of the house is doing, which during the summer shut-off is 8 degrees.

### The window sensor

The drying run needs to be sure the window is shut. If its sensor is missing from Indigo, disabled, reported offline by zigbee2mqtt, owned by a plugin that is stopped, or has never reported open or shut, a run does not start, and one that is going stops. The Event Log says why, once, rather than every 30 seconds. It reads the contact state that zigbee2mqtt window sensors report, so a sensor of another kind counts as one that has never reported.

This is stricter than the rest of the plugin, which treats a sensor it cannot read as shut. Holding a radiator warm into an open window for five hours costs more than a damp towel.

### Humidity

If you set **En Suite humidity sensor device ID** to a temperature and humidity sensor in the room, each run records how damp the room was when it started and when it finished, and says so when it ends:

```
[EnSuiteDrying] Finished (the 10:00 finish was reached). Humidity fell from 78% to 64%, so the room dried out by 14 points.
```

Nothing decides whether to run from that reading. I added it so that a rule for skipping the run when the room is already dry can be set later from real mornings. A reading is ignored when the sensor is missing, disabled, offline, has not reported for more than three hours, or gives a figure outside 1 to 100%, because a sensor that has dropped off the network can go on showing its last value, and one that has never reported shows 0%.

### The outdoor temperature in summer

The drying run needs a real outdoor reading: the Ecowitt sensor, or OpenWeatherMap weather fetched within the last hour. The **Fallback temperature** does not count, because it is a number you chose, not the weather. During the summer shut-off the rest of the plugin fetches no weather, so when the drying run has no reading it fetches OpenWeatherMap itself, no more than once every five minutes. With no reading at all, no run starts, and the Event Log says so once a day.

### Trying it out

**Plugins → EvoHome Heating Controller → Start En Suite Drying Run (30 minute test)** starts a run straight away, whatever the time, the season, the weather or away mode, and ends it after half an hour, or sooner if the window is opened. **Dry the En Suite out every morning** has to be ticked, or the test stops within 30 seconds.

**Show En Suite Drying Run Status** writes to the Event Log whether the drying run is switched on, which side of the summer shut-off it is, whether away mode is holding it, its hours and temperature, the outdoor limit against the temperature now, whether a run is going, whether the window reads shut, the humidity, and whether a run has been stopped for today.
