---
title: Version history
nav_order: 12
---

# Version history

The newest version is at the top.

## 1.10.0 — 27 September 2026

These are the things I found wrong while writing this guide.

- **The Dining Room stays at 16 degrees with a garden window or door open.** That was always meant to happen, but the plugin turned it straight back down to 8 degrees a moment later, so it never did.
- **The Pushover user key setting works.** Overheating alerts go to the key you set, or to the user set up in the Pushover plugin when it is blank. Before, the setting was ignored.
- **Away mode stops the En Suite drying run,** as the settings always said it would. It starts again that morning if away mode is switched off before the finish hour.
- **The drying run only starts when it knows it is cold outside.** With no Ecowitt sensor it used the fallback temperature of 6 degrees after a restart, which is below every limit, so it ran every morning whatever the weather. It now fetches the weather itself during the summer shut-off, and when there is no real reading it waits and says so once a day.
- **The En Suite Morning Cancelled trigger fires when opening the window ends the morning schedule,** as well as at 10am and on a warm morning.
- **A location of 0.0 and 0.0 in the shared settings file counts as not filled in,** so the Latitude and Longitude boxes are used instead of a point in the sea.
- **Empty outdoor record variables fill in.** A Highest or Lowest variable left empty used to stay empty for ever.
- **Toggle Timestamps in Log switches the time on every line** the plugin writes to the Event Log, not just a few of them, and remembers your choice straight away.

## 1.9.2 — 15 September 2026

- **The drying run only starts when it is cold outside,** below 12 degrees to start with. You can change the figure, or choose **No limit**, in the settings. It had been holding the En Suite radiator warm for three and a half hours on a morning that was 16.9 degrees outside at six.
- The plugin asks again every 30 seconds, so a morning that only turns cold at 7am still gets a run, and a run that has started is left to finish when the day warms up.
- The line that starts a run now gives the outdoor temperature, and **Show En Suite Drying Run Status** shows the limit, the temperature now and whether it counts as cold.

## 1.9.1 — 15 September 2026

- **The drying run stands down for the heating season.** From the day normal heating returns, the En Suite's 6am morning schedule looks after the room, and the drying run would otherwise have held it at its own, lower, temperature instead. It picks up again when the next summer shut-off begins, and stands down during a 24-hour **Force Heating On** too.
- It follows the summer shut-off dates in your settings, so moving those moves this with them.
- The 30-minute test run still works all year.
- **Show En Suite Drying Run Status** now says which side of the changeover you are on, and when heating returns.

## 1.9.0 — 12 September 2026

- **New En Suite drying run.** The radiator is held at 22 degrees from 5am to 10am to dry the room out, and stops the moment the window is opened. It runs through the summer shut-off and is not stopped by the mild-weather rules. It drives the radiator only, and never the underfloor heating.
- If the window sensor cannot be read, the run stops and the Event Log says why.
- An optional humidity sensor records how damp the room was at the start and end of each run.
- New menu items and actions to start a 30-minute test run, stop a run and show its status, and two new triggers for a run starting and ending.
- The times, the temperature and the whole feature can be changed in the settings.

## 1.8.2 — 11 September 2026

The plugin carries a note of where its code lives on GitHub, spelt the same way other Indigo plugins spell it. Nothing else changed.

## 1.8.1 — 7 September 2026

The settings window had grown wider than the screen allows, so the help text beside some settings was cut off. The longest help text now sits in its own paragraph, which wraps. No setting or behaviour changed.

## 1.8.0 — 6 September 2026

- **The summer shut-off is announced once,** when it starts, rather than about 21 times a day, and a new line says when it ends.
- **The hourly weather and room table stays out of the Event Log** unless you tick the new **Show the hourly weather and room table in the Indigo Event Log** setting. It is always in the plugin's own daily log, and **Show Full Weather Log** shows the weather report on demand.

## 1.7.4 — 8 August 2026

The **About** item in the Plugins menu opens this project's page. It went nowhere before.

## 1.7.3 — 21 July 2026

- Warnings and errors appear in the Event Log as warnings and errors. Before, they all appeared as ordinary lines.
- Log lines no longer come out with the time printed twice.

## 1.7.2 — 4 July 2026

- A new OpenWeatherMap key or location takes effect as soon as you click Save, rather than after a restart.
- The En Suite underfloor heating is no longer switched back on at a restart during the summer shut-off.
- The overheating records start clean at each summer shut-off, so a room cannot be left marked as alerted all summer.
- Alerts give the real amount a radiator was turned down by.
- Radiator targets keep their half degrees, rather than being rounded to a whole degree.
- The Ecowitt sensors and the solar forecast are no longer looked for by the device numbers from my house.

## 1.7.1 — 3 July 2026

- The plugin's saved files — boost and override timers, the overheating history and the weather — are written in a way that a power cut part-way through cannot spoil, and a spoilt or old one no longer stops the plugin loading.
- An overheating alert no longer fails when there is no outdoor temperature.
- A radiator with no temperature reading is left at its last target for that check, rather than being treated as freezing.
- Door sensors are read the same way as window sensors.
- The OpenWeatherMap key no longer appears in the log when the weather cannot be fetched.

## 1.7.0 — 3 July 2026

- One error in a room, a blank setting or a missing variable no longer stops the heating. Before, one error could stop every room until the plugin was restarted, with the plugin still showing as running.
- Every number in the settings is read carefully, so a cleared or mistyped setting cannot stop the plugin.
- Warnings and errors show in the Event Log as warnings and errors.
- **Start Timed Boost**, **Cancel Timed Boost**, **Run Heating Cycle Now** and **Set Away Mode** can be used as actions without a Heating Controller device.

## 1.6.2 — 10 June 2026

Tidying of the code and an automatic check each time it changes. No change in behaviour.

## 1.6.1 — 7 June 2026

New **Show Summer Shut-off Status** action, so a control page or dashboard can ask for the summer shut-off's state.

## 1.6.0 — 6 June 2026

- **New summer shut-off.** Between two dates you choose, 1 June to 30 September to start with, every radiator is held at 8 degrees and the En Suite underfloor heating is off.
- **Force Heating On (24 hours)** and **Cancel Forced Heating**, as menu items and actions, bring the heating back for a day. The 24 hours carry on after a restart.
- Two new triggers, and a **Summer Shut-off Status** state on the Heating Controller device.

## 1.5.7 — 5 June 2026

A setting holding something other than a number — the Ecowitt device, the location or the fallback temperature — no longer stops the plugin loading. The Pushover alert priority is passed the way the Pushover plugin expects.

## 1.5.6 — 4 June 2026

The heating check's log lines show the time to the thousandth of a second, like the rest of the plugin.

## 1.5.5 — 3 June 2026

The four outdoor temperature record variables are found by name. Before, making one of them again gave it a new number and the plugin logged an error at every check.

## 1.5.4 — 29 May 2026

The hourly report no longer stops for days at a time. It used to wait for a check that landed exactly on the hour, and the checks drift by a few seconds an hour.

## 1.5.3 — 25 May 2026

A behind-the-scenes change to how the plugin looks after its own device. No change in behaviour.

## 1.5.2 — 23 May 2026

Every log line starts with the time to the thousandth of a second, with a menu item to turn that off.

## 1.5.1 — 23 May 2026

A behind-the-scenes change so my home location cannot appear in the code. No change in behaviour.

## 1.5 — 23 May 2026

**The En Suite morning is skipped on a warm morning.** If it is 10 degrees or warmer outside at 6am, the radiator stays down and the underfloor heating stays off until 10am.

## 1.4 — 13 May 2026

- The overheating alert email address and your location can be kept in the shared settings file, with the Configure boxes as a fallback.
- The Ecowitt sensor settings no longer come filled in with the numbers from my house.
- The plugin's triggers work. Before, they never ran.
- A timed boost is no longer cancelled out by a room that is warm from the sun.

## 1.3 — 3 May 2026

- **An Ecowitt outdoor sensor** is the first choice for the outdoor temperature, with OpenWeatherMap behind it.
- **The snow boost,** with its settings.
- **Triggers** for alerts, boosts, snow and the En Suite morning.
- **Show Full Weather Log** in the Plugins menu.

Also since 1.0: a room warm from the sun is shown as **Above Target (solar gain)** and sends no alert, the timed boost is in the Plugins menu, the En Suite morning is no longer mistaken for overheating, and the plugin switches the En Suite underfloor heating and sets its thermostat itself.

## 1.0 — 15 April 2026

First release. My old heating script, rebuilt as a plugin that runs all the time, with the timed boost and the En Suite morning schedule added.

Versions 1.1 and 1.2 are not recorded.
