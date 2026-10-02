---
title: When something goes wrong
nav_order: 11
---

# When something goes wrong

Each section starts with what you see, then what it means and what to do.

## The log says a required variable or device is missing

When it starts, the plugin checks that each radiator and mode variable it knows about is in Indigo. A line such as **Missing required device: Bathroom TRV** means the number for it in `heating_logic.py` does not match anything in your Indigo.

- On a new install, this is expected until you have fitted the plugin to your house — see [Getting started](getting-started.md).
- If it was working before, check whether that device or variable has been deleted and made again, which gives it a new number. Put the new number in `heating_logic.py` and choose **Plugins → EvoHome Heating Controller → Reload**.

## The log says "No overheat-alert email configured"

Neither the **Overheat alert email** setting nor the shared settings file has an address. Fill one in, or ignore it if you do not want the alerts by email. The heating is not affected.

## The log says "No OWM API key found"

The plugin has no OpenWeatherMap key. The heating still runs on your Ecowitt sensor, or on the **Fallback temperature** if you have no Ecowitt sensor, but there is no snow forecast. Add the key in the settings or the shared settings file.

## The log says the Ecowitt device is offline, and it is falling back to OWM

The plugin cannot read your Ecowitt outdoor sensor, so it is using OpenWeatherMap's temperature for your area instead. It says so at most once every 30 minutes. Check the Ecowitt plugin and the station. If the station will be out of action for a while, tick **Force OWM temperature** in the settings.

## The log says the Ecowitt outdoor reading has not changed for so many minutes

Your Ecowitt outdoor sensor has stopped updating, so the plugin is using OpenWeatherMap's temperature for your area instead. The Ecowitt plugin still shows the device as online, which is why the plugin goes by how old the reading is. Check the Ecowitt station and its plugin.

## The log says no temperature has been reported for a zone

The room's temperature has not been reported for more than 45 minutes, so its temperature may be out of date and the plugin leaves its radiator where it is. When every room says so at once, the RAMSES ESP gateway has stopped: check that plugin and its gateway. When one room says so, check that radiator's valve and its batteries. The plugin says once in the Event Log when the room is reporting again. Just after RAMSES ESP is updated to 1.16.0, each room says it has not reported a temperature yet, until the controller next sends them a few minutes later.

## The log says a room's controller timetable does not match its plan

Every morning at 4am the plugin compares the timetable stored on the Evohome controller with its own plan for each room. That timetable is what a room goes back to if Indigo stops, so the two should agree. The line says the first time of day where they differ, such as *Dining Room: at 6am on Monday the controller has 16 degrees where the plan has 18.* Somebody may have changed the timetable on the controller or in the Evohome app. Write the plans to the controller again, or change the plan to match. You also get one Pushover message when the list of rooms that differ changes.

## The log says RAMSES ESP has not read the Evohome timetable

The rooms named have no timetable reading from the last 30 hours, so they could not be checked. RAMSES ESP reads them at 3:15am. Check that RAMSES ESP is running and its gateway is online, or use its **Read Evohome Timetables Now** menu item.

## Every radiator is at 8 degrees

Check whether the summer shut-off is on — choose **Plugins → EvoHome Heating Controller → Show Summer Shut-off Status**. If it is and you want heat, choose **Force Heating On (24 hours)**, or change the dates in the settings.

If the shut-off is not on, it is probably more than 14 degrees outside, which turns the radiators down. **Show Full Weather Log** shows the outdoor temperature the plugin is using.

## One room is colder than its plan says

Look at the plugin's own daily log for that room — the [How it works](how-it-works.md) page says where to find it. The last column says what the plugin did and why, such as **Window open**, **Overheat** or **Outdoor >14.0degC**, each followed by **(valve closed)**. A window sensor that shows open when the window is shut will keep that room cold.

## A room shows "Above Target (solar gain)"

The room is warmer than its target although its radiator has been turned down for a while, so the warmth is coming from the sun or from inside the house. It is not a fault, and no alert is sent for it.

## The log says a room's temperature is unavailable and it is skipped

The RAMSES ESP plugin has no temperature reading for that radiator, so the plugin leaves it at its last target rather than guessing. It usually sorts itself out within a few minutes. If it goes on, look at the RAMSES ESP plugin and the radiator's batteries.

## A timed boost is "Ignored — whole-house summer shut-off is active"

A timed boost does not start during the summer shut-off. Choose **Force Heating On (24 hours)** first, then start the boost.

## The drying run did not happen

Choose **Plugins → EvoHome Heating Controller → Show En Suite Drying Run Status**. It shows each thing that decides whether a run starts:

- **Season** — the drying run only runs during the summer shut-off.
- **Outdoor** — **too mild** means it was not colder than your limit.
- **Window shut** — **False** means the window was open or its sensor could not be read.
- **Cancelled** — a date means the window was opened during a run that day, so it will not run again until tomorrow.

## The log says "The drying run is held off because..."

The plugin cannot be sure the En Suite window is shut — its sensor is missing, disabled, offline, owned by a stopped plugin, or has never reported. Until it can read the sensor, it will not hold the radiator warm. Check the window sensor in Indigo.

## An overheating alert did not reach my phone

- Check the Pushover plugin is installed and enabled. If it is not, the Event Log says **Pushover plugin not available**.
- Alerts go to the **Pushover user key** in the settings, or to the user set up in the Pushover plugin when that is blank. Check the key is the one on your Pushover account page.
- No alert is sent when it is above 12 degrees outside, or when the warmth is from the sun.

## The hourly room table is not in the Event Log

That is how it starts. Tick **Show the hourly weather and room table in the Indigo Event Log** in the settings, or choose **Show Full Weather Log** to see the weather report once. The table is always in the plugin's own daily log.

## The outdoor records say "no record yet" or the log has errors updating them

The four record variables are missing. [Getting started](getting-started.md) lists their names. A Highest or Lowest variable that is empty, or holds something other than a number, counts as having no record yet, and the next outdoor reading fills it.

## Still stuck?

Choose **Plugins → EvoHome Heating Controller → Show Plugin Info**, copy the lines it writes to the Event Log, and post them on the [Indigo forum](https://forums.indigodomo.com) with a description of what you see. You can also [raise an issue on GitHub](https://github.com/Highsteads/EvoHomeControl/issues).
