---
title: Version history
nav_order: 12
---

# Version history

The newest version is at the top.

## 1.18.0 — 2 October 2026

Fixes from an independent review of 1.17.0. None of them is known to have happened here.

- **A room whose temperature has stopped updating is left alone.** The plugin judged a room's reading by when the RAMSES ESP plugin last heard anything from it, and the Evohome controller keeps sending setpoints even when a temperature stops arriving, so an old reading could look current and the radiator be turned down or up on it. With RAMSES ESP 1.16.0 the plugin goes by when the temperature itself was last reported. A missing temperature is never treated as 0 degrees.
- **An overheating alert that does not get through is sent again.** When neither Pushover nor the email took it, the plugin still recorded it as sent and never tried again. Now it logs an error and tries every 30 minutes until one of them takes it. The **Critical Overheat Alert** trigger still fires once. The alert and the all-clear are written in plain sentences.
- **The En Suite morning ends even if the plugin missed 10am.** If the plugin was not running for the whole of the 10 o'clock hour, and the En Suite room was not reporting, the underfloor heating switch could stay on past the morning.
- **An old snow forecast no longer adds heat.** When OpenWeatherMap could not be reached, hours of snow that had already passed kept the snow boost on. A forecast is now read by its own times, and one more than three hours old is not used.
- **With the 1 hour setting, each room is renewed half way through.** It was renewed whenever less than an hour was left, which with a one-hour setting meant every five minutes.
- **Run Cycle Now, Away and saved settings always get their cycle.** Asked for while a check was already running, the request was lost until the next scheduled check.
- **The saved state cannot be spoilt by two saves at once.** An action and the heating check saving together could leave the file unreadable, which loses a running force-on or boost at the next restart.
- **The 30-minute drying test lasts 30 minutes on the night the clocks go back**, not 90.

## 1.17.0 — 30 September 2026

- **The En Suite drying run now looks at the room as well as the weather.** It used to start only when it was colder than 12 degrees outside, so a cold room on a mild morning got no heat. Now a run starts when the room is colder than **19 degrees**, whatever the weather, or when it is cold outside as before. It never starts when the room is already at the temperature the run would hold.
- The new setting is **Run when the room is colder than**, from 16 to 21 degrees, or **Ignore the room temperature** for the old rule.
- The room reading comes from the En Suite sensor, or from the radiator valve when the sensor has said nothing for three hours.
- The once-a-day line for a morning with no run now gives both readings and both limits, and the start line says which of the two started it.
- Nothing changes in the heating season: the drying run still only runs during the summer shut-off.

## 1.16.1 — 30 September 2026

- **A morning too warm for the En Suite drying run now says so.** The first time each day the run is held off because it is not cold enough outside, the Event Log has one line, such as *No drying run so far today: it is 17.1degC outside and a run only starts below 12degC. One will still start if it gets colder before 10:00.* Before, a mild morning wrote nothing, so there was no way to tell why the room had not warmed.

## 1.16.0 — 29 September 2026

- **A room changed by hand is left alone.** Change a room's temperature at the Evohome controller, on a valve's wheel or in the app, and the plugin no longer puts it back at its next check. It leaves the room until the room's plan next changes, or midnight if that comes first, and then carries on as normal. A room set permanently by hand is left alone for as long as it stays that way; pressing **Auto** on the controller, which puts the room back on its timetable, hands it back to the plugin. The Event Log says when a room is being left alone, such as *Bedroom 3 was set to 21 degrees by hand, so the heating plugin leaves it alone until 10pm*, and again when it comes back. This works during the summer shut-off too.
- **The summer hold ends by itself.** The 8 degree hold is now sent to run until midnight at the start of the day heating returns, instead of for ever. If Indigo is not running when that day comes, the house goes back to its Evohome timetable on time instead of staying cold into the winter. Tested on a real controller, which took an end date eight months away.
- Both need RAMSES ESP 1.15.0. With an older RAMSES ESP the summer hold stays permanent, as before, and hand changes are put back as before.

## 1.15.0 — 29 September 2026

- **Every morning at 4am the plugin checks the timetable stored on the Evohome controller against its own plans.** That timetable is what each room goes back to if Indigo stops. If a room differs, the Event Log says where, such as *Dining Room: at 6am on Monday the controller has 16 degrees where the plan has 18*, and you get one Pushover message whenever the list of rooms that differ changes. Nothing is logged when everything matches.
- It uses the timetable RAMSES ESP 1.13.0 reads from the controller each night, and says so when a reading is more than 30 hours old.
- New action and menu item: **Check Evohome Timetable Against the Plans**.

## 1.14.0 — 28 September 2026

- **Timed boosts and the 24-hour Force Heating On last the right time across a clock change.** When the clocks went back, a 1-hour boost would have run for 2 hours and a force-on for 25.
- **Away mode no longer adds up with other modes.** Away with Both out gave 10 degrees (12 instead of 16 in a frost), and Away with Boost gave 16. Both are now ignored while away mode is on.
- **An open window closes the radiator even while away mode is on.** It used to stay at 14 or 16 degrees.
- **Both out leaves an open window's setting alone.** It also no longer made the next check report a window as closed while it was still open.
- **The Boost variable is no longer cancelled by overheat checking.** A room was judged against its normal target, so one warming towards its boosted temperature had its radiator turned down. The Conservatory's extra three degrees could never happen.
- The Bathroom's guest plan at midnight is 16 degrees, like the rest of the night, instead of 10.
- "No overheat-alert email configured" is no longer logged as an error. It only means the alerts go by Pushover alone.
- Old settings from earlier versions that nothing reads are removed once, among them an old weather key stored in plain text.

## 1.13.0 — 28 September 2026

**If Indigo stops, the house goes back to the Evohome timetable.** Each radiator's temperature is now sent for two hours at a time and renewed about once an hour, instead of being held indefinitely. If Indigo, this plugin or RAMSES ESP stops, each radiator goes back to the timetable on the Evohome controller when its time runs out, rather than staying at whatever it was last told - which could have been 8 degrees in January. Tested on the real controller first.

- A new setting chooses how long: 1, 2 (to start with) or 4 hours, or never.
- The summer 8 degree hold is still permanent, so a stopped Indigo in summer cannot switch the heating back on. The En Suite drying run is timed, so it cannot outlast Indigo either.
- Needs RAMSES ESP 1.12.0 or later. With an older one the plugin sends permanent settings as before and says so once.
- A restart during the summer shut-off no longer logs that an empty overheating record was too old to use.

## 1.12.0 — 28 September 2026

Four fixes made before the heating came back on after the summer.

- **Overheating starts fresh after the summer.** The plugin kept last spring's overheating record on disk, with three rooms still marked as having a stuck valve, and a restart would have loaded it back. Every room would have started the season with its radiator turned down, and the plugin would have sent all-clear messages for rooms that were fine. It now clears the record when the shut-off begins, and ignores one more than an hour old.
- **A stopped Ecowitt station is noticed.** The Ecowitt plugin never marks its sensor offline, so a station that had stopped kept its last temperature for ever. On a mild day that would have held every radiator at 8 degrees. A reading that has not changed for 30 minutes is no longer used, and OpenWeatherMap weather more than three hours old is not used either.
- **A room that has gone quiet is left alone.** When the RAMSES ESP gateway stopped from 26 to 31 May, every room kept its last temperature for five days, and the plugin went on acting on them. A room the gateway has not heard from for 45 minutes now keeps its radiator where it is, and the Event Log says so once.
- **The En Suite underfloor heating is not left on.** Three things could leave it running until 10am the next day: the plugin not running at 10am, away mode (the morning schedule still switched it on at 6am), and opening the window while away mode was on. Away mode now stops the morning schedule, and the other two switch it off.

## 1.11.0 — 27 September 2026

A boost, or a timed boost, no longer heats a room with a window or outside door open. Boosting a room with the garden door open only heated the garden. The room keeps its open-window setting instead, so the Dining Room stays at 16 degrees with the garden door open rather than going to 18, and it picks the boost up again as soon as everything is shut.

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
