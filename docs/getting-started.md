---
title: Getting started
nav_order: 2
---

# Getting started

## What you need

- Indigo 2025.2 or later.
- Honeywell Evohome radiator controls, and my [RAMSES ESP](https://github.com/Highsteads/RAMSES_ESP) plugin already working, so that each Evohome zone shows in Indigo as a thermostat device with its room temperature.
- A window or door sensor in Indigo for each window and door you want the heating to watch. The plugin reads zigbee2mqtt contact sensors, such as those my Zigbee2MQTT Bridge plugin creates, and any sensor whose state shows as **open** or **closed**.
- An **OpenWeatherMap API key** for its One Call 3.0 service, from [openweathermap.org](https://openweathermap.org). The plugin asks it for the weather at most once every 15 minutes.
- Your **latitude and longitude**, the two numbers that pin your house on a map, such as `54.9` and `-1.8`, so the forecast is for where you live.
- Optional, but I recommend it: an **Ecowitt weather station** with an outdoor sensor, read through my [Ecowitt](https://github.com/Highsteads/Ecowitt) plugin. The temperature at your own house is more use than one for the nearest town.
- Optional: the **Pushover** plugin and an email account set up in Indigo, for the overheating alerts.

## Written for my house

The plugin looks after twelve rooms — Bathroom, Bedroom 1, Bedroom 2, Bedroom 3, En Suite, Conservatory, Dining Room, Hall Bedroom, Hall Kitchen, Living Room Front, Living Room Door and Utility Room — and finds each radiator, window sensor, door sensor and mode variable by its Indigo device or variable number. Those numbers are the ones in my house. In yours, Indigo will have given everything different numbers, so the plugin will report each one missing when it starts, and will not heat anything until they are put right.

Fitting it to your house means editing two files inside the plugin with a plain text editor, and if your rooms are not these twelve, a third. If editing a Python file is not something you are happy doing, this plugin is not ready for your house yet.

## 1. Install the plugin

1. Go to the [Releases page](https://github.com/Highsteads/EvoHomeControl/releases/latest) and download `EvoHomeControl.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `EvoHomeControl.indigoPlugin`
3. Double-click `EvoHomeControl.indigoPlugin` — Indigo will install it automatically

Indigo asks whether to enable the plugin. Say yes. It will log errors about missing devices until the next step is done, and that is expected.

## 2. Fit it to your house

The files are inside the installed plugin. In the Finder, open `/Library/Application Support/Perceptive Automation/`, then the folder named after your Indigo version, such as `Indigo 2025.2`, then `Plugins`. Right-click `EvoHomeControl.indigoPlugin`, choose **Show Package Contents**, and open `Contents`, then `Server Plugin`.

To find the number of any device or variable in Indigo, right-click it and choose **Copy ID**.

### heating_logic.py — which device is which

Near the top is a list of numbers, one line for each window, door and radiator, each named after its room, followed by the numbers of the mode variables. Replace each number with the one from your Indigo. A line looks like this:

```
DEV_BATHROOM_WINDOW_ID     = 123456789
```

The radiators are the thermostat devices the RAMSES ESP plugin made, one per Evohome zone.

The mode variables are six Indigo variables of your own, which the plugin reads at every check:

| Variable for | What the plugin expects in it |
|---|---|
| Away | `true` when the house is empty for days, `false` otherwise |
| Both out | `yes` when everyone is out for a few hours, `no` otherwise |
| Boost | `yes` to boost the living areas and the conservatory, `no` otherwise |
| Bedroom 2 guest | `true` when a guest is in Bedroom 2 |
| Bedroom 3 guest | `true` when a guest is in Bedroom 3 |
| Temperature offset | Nothing — the plugin writes the weather adjustment into it for you to see |

The plugin also keeps a record of the highest and lowest outdoor temperature it has seen, with the date and time of each, in four variables it finds by name. Create them with exactly these names: `Average_Outside_Temp_Highest`, `Average_Outside_Temp_Highest_Time`, `Average_Outside_Temp_Lowest` and `Average_Outside_Temp_Lowest_Time`. Give the Highest one a starting value of `-50` and the Lowest one `50`, so the first reading replaces both. The two Time variables can start empty.

### schedules.py — how warm each room should be

Each room has a line of 24 temperatures in degrees, one for each hour of the day, starting at midnight. Change them to suit your house. The same file sets the highest temperature a bedroom may reach, how much the boost adds to each room, and which rooms the timed boost covers.

### If your rooms are different

The list of twelve rooms, and which sensors belong to which room, is in `plugin.py`. Changing that is more involved, and needs someone comfortable with Python.

### When you have finished

Choose **Plugins → EvoHome Heating Controller → Reload** so the plugin reads your changes.

Keep a copy of the files you edited. Installing a new version of the plugin replaces them with mine.

## 3. Fill in the settings

Open **Plugins → EvoHome Heating Controller → Configure** and fill in:

- **OWM API key**, **Latitude** and **Longitude**, unless you keep them in the shared settings file described on the [Settings](settings.md) page.
- **Ecowitt outdoor sensor device ID** — the number of your Ecowitt outdoor sensor device, if you have one.
- **Overheat alert email** — the address the overheating alerts go to.

**Check the summer shut-off before you click Save.** It is switched on to start with, and runs from 1 June until heating returns on 30 September. Install the plugin in July and every radiator goes down to 8 degrees straight away. Change the dates, or untick **Enable summer shut-off**, if that is not what you want. The [summer shut-off](summer-shut-off.md) page explains it.

Leave everything else as it is to start with, and click **Save**. Every setting is explained on the [Settings](settings.md) page.

## 4. Check it works

The Indigo Event Log should show the plugin starting, a line saying it is ready with how often it checks, and a line about the summer shut-off. There should be no lines saying a required device or variable is missing. If there are, the number for that one in `heating_logic.py` is wrong.

Choose **Plugins → EvoHome Heating Controller → Show Full Weather Log** to see the outdoor temperature the plugin is using and where it came from.

Within five minutes each radiator should have a new target, and your Evohome controller will show each zone on a permanent override rather than following its own timetable. The plugin writes a line for every room to its own daily log, which the [How it works](how-it-works.md) page tells you how to find.

If you would like to see an hourly table of every room in the Event Log, tick **Show the hourly weather and room table in the Indigo Event Log** in the settings.

If something is not right, the [When something goes wrong](troubleshooting.md) page goes through the usual causes.
