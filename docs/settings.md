---
title: Settings
nav_order: 9
---

# Settings

Open these with **Plugins → EvoHome Heating Controller → Configure**. Changes take effect at the next heating check, which the plugin runs within 30 seconds of your clicking Save.

The rooms, their sensors and their hour-by-hour temperatures are not settings. They are written into the plugin, as the [Getting started](getting-started.md) page explains.

## OPENWEATHERMAP

| Setting | What it does |
|---|---|
| **OWM API key** | Your OpenWeatherMap API key, for its One Call 3.0 service. The plugin uses it for the outdoor temperature when there is no Ecowitt reading, and for the snow forecast. |
| **Latitude** and **Longitude** | Where your house is, such as `54.9` and `-1.8`, so the weather is for your area. |

All three can be kept in the shared settings file instead, as described below.

## WEATHER SOURCE

| Setting | What it does |
|---|---|
| **Force OWM temperature** | Tick this to use OpenWeatherMap's temperature even when you have an Ecowitt sensor, if the sensor is out of action. Unticked to start with. |
| **Ecowitt outdoor sensor device ID** | The Indigo number of your Ecowitt outdoor sensor device. Right-click the device and choose **Copy ID** to get it. Leave it blank if you have none. Hidden while **Force OWM temperature** is ticked. |
| **Ecowitt indoor sensor device ID** | The number of an Ecowitt indoor sensor. Optional, and only used to add air pressure, indoor temperature and humidity to the hourly report. |
| **Fallback temperature** | The outdoor temperature the plugin uses when it can read neither the Ecowitt sensor nor OpenWeatherMap. 6 degrees to start with. |

## OVERHEAT ALERTS

| Setting | What it does |
|---|---|
| **Pushover user key** | Not used at present. Alerts go through the Pushover plugin to the user set up in that plugin. The Pushover plugin needs to be installed and enabled. |
| **Overheat alert email** | The address the overheating alerts and all-clears are emailed to, using the email account set up in Indigo. If neither this nor the shared settings file has an address, the plugin logs an error each time it starts. |

## HEATING CYCLE

| Setting | What it does |
|---|---|
| **Heating cycle interval** | How often the plugin works out every room's temperature: every 5 minutes, which is what I recommend, 10 or 15. |

## SNOW FORECAST

| Setting | What it does |
|---|---|
| **Apply heating boost when snow is forecast** | Ticked to start with. Adds heat to every room when OpenWeatherMap forecasts snow or freezing rain. |
| **Look-ahead window for snow detection** | How far ahead to look: 6, 12 or 24 hours. 12 to start with. |
| **Heating boost when snow forecast** | How much to add: half a degree to two degrees. One degree to start with. |

## SUMMER SHUT-OFF

| Setting | What it does |
|---|---|
| **Enable summer shut-off** | Ticked to start with. Holds every radiator at 8 degrees and the En Suite underfloor heating off between the two dates below. |
| **Shut-off starts — month** and **day** | The first day the house goes off. 1 June to start with. |
| **Heating returns — month** and **day** | The day heating comes back on. 30 September to start with, which means off to 29 September and heating from 30 September. |

The [summer shut-off](summer-shut-off.md) page explains it in full.

## EN SUITE DRYING RUN

| Setting | What it does |
|---|---|
| **Dry the En Suite out every morning** | Ticked to start with. Switches the drying run on or off. The settings below are hidden while it is off. |
| **Starts at** and **Finishes at** | The hours of the run, 5am and 10am to start with. The hours can cross midnight. |
| **Hold the radiator at** | The radiator temperature during a run, from 18 to 26 degrees. 22 to start with. |
| **Only run when it is colder than** | A run only starts when it is colder outside than this, from 8 to 18 degrees. 12 to start with. Choose **No limit - run whatever the weather** to leave the weather out of it. |
| **En Suite humidity sensor device ID** | Optional. The number of a humidity sensor in the En Suite, used only to record how damp the room was at the start and the end of each run. |

The [En Suite](en-suite.md) page explains when a run starts and stops.

## LOGGING

| Setting | What it does |
|---|---|
| **Show the hourly weather and room table in the Indigo Event Log** | Unticked to start with. Every hour the plugin writes a weather report and a line for each room, about 40 lines, to its own daily log. Tick this to have them in the Event Log as well. Warnings and errors reach the Event Log either way. |
| **Enable debug logging** | Adds a line to the Event Log at the end of every heating check. Only useful when chasing a problem. |

## Keeping keys and addresses in one file

If you run several of my plugins, you can keep keys and addresses in one shared file instead of typing them into each plugin's settings. The file is called `IndigoSecrets.py` and lives in `/Library/Application Support/Perceptive Automation/`. A blank copy, `IndigoSecrets_example.py`, comes inside the plugin, in `Contents` → `Server Plugin` — copy it to that folder, rename it `IndigoSecrets.py`, and fill in the lines this plugin reads:

| Line in the file | What to put there |
|---|---|
| `OWM_API_KEY` | Your OpenWeatherMap API key |
| `LATITUDE` and `LONGITUDE` | Where your house is |
| `OVERHEAT_ALERT_EMAIL` | The address for the overheating alerts |

When the file has a value, it is used, whatever the Configure box says. Take care with the location: the blank copy has `LATITUDE = 0.0` and `LONGITUDE = 0.0`, and those count as values, so either fill them in or delete those two lines, or the forecast will be for a point in the sea off West Africa.

Changes to the file take effect when the plugin next starts.
