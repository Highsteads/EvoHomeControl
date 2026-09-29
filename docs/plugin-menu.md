---
title: The plugin menu
nav_order: 10
---

# The plugin menu

These are under **Plugins → EvoHome Heating Controller**, in this order.

| Menu item | What it does |
|---|---|
| **Start Timed Boost (1 hour)** | Adds two degrees to the Dining Room, Hall Kitchen, Living Room Door and Living Room Front for an hour. Refused during the summer shut-off. |
| **Start Timed Boost (2 hours)** | The same, for two hours. |
| **Cancel Timed Boost** | Ends a timed boost now, and lists in the Event Log the temperature each room goes back to. |
| **Start En Suite Drying Run (30 minute test)** | Starts a half-hour drying run now, whatever the time, the season or the weather, so you can see it work. |
| **Stop En Suite Drying Run** | Ends a drying run now, and logs how the humidity changed if you have a humidity sensor set. |
| **Show En Suite Drying Run Status** | Writes to the Event Log whether the drying run is switched on, whether the season allows it, its hours and temperature, the outdoor limit against the temperature now, whether a run is going, whether the window reads shut, and the humidity. |
| **Force Heating On (24 hours)** | Brings back normal heating for 24 hours during the summer shut-off. |
| **Cancel Forced Heating** | Ends the 24 hours early and puts the summer shut-off back. |
| **Show Summer Shut-off Status** | Writes to the Event Log whether the shut-off is on, its dates, and how long a 24-hour override has left. |
| **Run Heating Cycle Now** | Runs a heating check within 30 seconds rather than waiting for the next one. |
| **Show Heating Status** | Writes to the Event Log which modes are on — away, both out, boost, timed boost and the En Suite morning — the summer shut-off, and each room that is overheating with its temperature and target. |
| **Show Full Weather Log** | Writes the full weather report to the Event Log now: the outdoor temperature and where it came from, OpenWeatherMap's conditions, wind and sunrise, any snow forecast, the weather adjustment, the outdoor temperature records, and which modes are on. |
| **Check Evohome Timetable Against the Plans** | Compares the timetable stored on the Evohome controller with this plugin's plans for every room, and writes the result to the Event Log. The plugin also does this every morning at 4am. Needs RAMSES ESP 1.13.0 or later. |
| **Show Overheat Monitor Status** | Lists each room that is above its target, for how long, whether the warmth is from the radiator or the sun, and whether an alert was sent. |
| **Show Timed Boost Status** | Says whether a timed boost is running, and if so when it ends and which rooms it covers. |
| **Toggle Debug Logging** | Turns on or off the extra line the plugin writes to the Event Log at the end of every heating check. It is the same as the **Enable debug logging** setting. |
| **Toggle Timestamps in Log (on/off)** | Switches the time on or off at the start of every line this plugin writes to the Event Log. The plugin's own daily log keeps the times either way. It stays as you leave it. |
| **Show Plugin Info** | Writes the plugin's version and details of your Mac and Indigo to the Event Log, followed by the heating status. Useful to include if you ask for help on the Indigo forum. |
