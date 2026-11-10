# EvoHome Heating Controller for Indigo

**Runs a Honeywell Evohome house room by room from Indigo, around the clock, with no cloud involved.**

**Version:** 1.27.0 | **Author:** CliveS & Claude | **Needs:** Indigo 2025.2 or later and my RAMSES ESP plugin

**[Read the full guide](https://highsteads.github.io/EvoHomeControl/)** — setting up, how each room's temperature is decided, and what to do when something goes wrong.

---

## What it does

This plugin lets [Indigo](https://www.indigodomo.com) run the heating in a house with **Honeywell Evohome** radiator controls. It reaches the radiators through my [RAMSES ESP](https://github.com/Highsteads/RAMSES_ESP) plugin, which talks to them over their own radio, so nothing goes through Honeywell's servers. Every five minutes it works out the right temperature for each room and sets each radiator to match.

- **Heats each room to its own plan,** with a temperature for every hour of the day, and guest plans for when you have visitors.
- **Follows the weather,** taking a degree or two off as it gets milder outside, turning radiators down above 14 degrees, and adding a little heat when snow is forecast. It reads an Ecowitt weather station if you have one, and OpenWeatherMap if not.
- **Turns a radiator down when its window or door is open,** and back up when it shuts.
- **Stops rooms overheating,** turning a radiator down before the room overshoots, and can send a Pushover message and an email if a room stays well above where it should be. Those messages are switched off unless you turn them on.
- **Boosts the living areas** by two degrees for one or two hours, then puts them back.
- **Away and both out modes,** switched by Indigo variables, hold the house at a safe, cheaper temperature.
- **Shuts the heating off for summer** between dates you choose, with a menu item to have it back for 24 hours.
- **Looks after the En Suite** — a warm room from 6am on winter mornings with the underfloor heating on, and a morning drying run on cold summer mornings to deal with wet towels.

## Which houses it works with

I wrote this plugin for my own house. The twelve rooms, the window and door sensors in each one, and each room's temperature for every hour are written into the plugin, using the Indigo device numbers from my house. To use it on another house, those have to be changed in two of the plugin's files, which the guide explains. If editing a Python file is not for you, this plugin is not ready for your house yet.

It needs:

- Honeywell Evohome radiator controls, with my [RAMSES ESP](https://github.com/Highsteads/RAMSES_ESP) plugin working.
- A window or door sensor in Indigo for each window and door you want the heating to watch.
- An OpenWeatherMap API key, for the weather and the snow forecast.
- Optional: an Ecowitt weather station, the Pushover plugin and email set up in Indigo, for the outdoor temperature and the overheating alerts.

## Installing

1. Go to the [Releases page](https://github.com/Highsteads/EvoHomeControl/releases/latest) and download `EvoHomeControl.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `EvoHomeControl.indigoPlugin`
3. Double-click `EvoHomeControl.indigoPlugin` — Indigo will install it automatically

## Setting it up

1. Put your own device and variable numbers into the plugin, and your own hour-by-hour temperatures, as the guide's [Getting started](https://highsteads.github.io/EvoHomeControl/getting-started.html) page explains, then choose **Plugins → EvoHome Heating Controller → Reload**.
2. Open **Plugins → EvoHome Heating Controller → Configure**, fill in your OpenWeatherMap key, your location, your Ecowitt outdoor sensor and the address for alerts, and check the summer shut-off dates — it is on from 1 June to 30 September to start with. Click **Save**.
3. Check the Event Log has no lines about missing devices or variables, and choose **Show Full Weather Log** to see the outdoor temperature the plugin is using.

The [full guide](https://highsteads.github.io/EvoHomeControl/) goes through each step, explains every setting, and covers what to do if something does not work.

## What's new

**v1.27.0** - A room is not judged as overheating for the first 90 minutes after its target steps down, such as at the evening set-back, because it is still at the temperature it was heated to. A new setting changes the wait. The overheating alerts, which are still switched off, now say how long the radiator has really been turned down.

**v1.26.0** - During a timed boost the plugin records, after each heating check, what each boosted room was asked for and why a room got less. Dashboards 3.70.0 shows this on its Heating page.

**v1.25.10** - Boost now starts within a second or two instead of waiting up to five minutes for the next heating check. A boosted room that is still below 22 degrees is no longer held back by the coasting from its normal plan. A room that is genuinely too warm, has a window open or is in away mode is still not boosted.

**v1.25.9** - A room that is too warm with its radiator already turned down no longer sends a Pushover message, an email or an all-clear. It is logged and still shows in the overheat status.

**v1.25.8** - The warning about settings that could not be sent timed now names the right RAMSES ESP version: 1.15.0 for the summer hold and the hold after Cancel Timed Boost.

**v1.25.7** - The three remaining half-minute checks (the En Suite window, the timetable check, and windows and doors) now report a lasting fault once instead of every 30 seconds.

**v1.25.6** - A temperature set by hand is now held for the right length of time on the nights the clocks change.

**v1.25.5** - A damaged setpoint cache file is no longer ignored without a word. The plugin says so once, keeps a copy of the file, and starts afresh.

**v1.25.4** - A fault in one of the half-minute checks (the En Suite morning or drying run, a boost or force-on running out) no longer stops the heating. It is logged once, the heating carries on, and the plugin says when the check works again.

**v1.25.3** - If RAMSES ESP cannot take the summer hold or the hold after Cancel Timed Boost, the plugin now says so once rather than for every radiator every five minutes, and tries again every 15 minutes.

**v1.25.2** - With the RAMSES ESP plugin stopped, radiator settings are no longer logged as sent when nothing could send them; the plugin says once that they are not reaching Evohome and tries again each cycle.

**v1.25.1** - One failed radiator command (RAMSES ESP restarting, say) no longer leaves every room on permanent settings until a restart; timed settings are tried again every 15 minutes, and a second failure is reported too.

**v1.25.0** - Fixes from a joint review with RAMSES ESP. A setting the gateway could not send is no longer counted as sent, an overheating radiator stays turned down for at least 45 minutes, a room still too warm after being turned down now sends an alert (a stuck valve looks the same as sun), the alert quotes the right numbers, the clocks going back no longer confuse it, and the morning timetable check names what it could not check and tries again.

**v1.24.0** - Timed boost and the Boost variable now set the boosted rooms to 22 degrees, not a set number of degrees above the schedule. That covers the Dining Room, Hall Kitchen, Living Room Door and Living Room Front, and the Conservatory too. The Conservatory is boosted only while its sliding door is open. With the door shut it is held at 12 degrees, as before. An open garden window or garden door still stops its boost. The Conservatory now takes the timed boost as well as the global Boost.

**v1.23.0** - Cancel Timed Boost now sets all twelve radiators to 12 degrees, holding each room until its next scheduled temperature change. The holds survive a plugin restart. Starting a new timed boost clears them. Open-window protection still takes priority, and a boost that expires naturally returns to the normal schedule.

**v1.22.1** — Morning targets are one degree lower for the Bathroom, Bedroom 2, Hall Bedroom and both Living Room radiators from 5am to noon, and the Dining Room from 6am to noon. The En Suite, guest plans and the rest of the day stay as before.

**v1.22.0** — An open window or outside door now turns its room's radiator down within about half a minute, whatever else is going on, including a temperature set by hand. The Bathroom's window is watched again.

**v1.21.0** — The En Suite underfloor heating is now turned on and off through its thermostat. The switch that powers the thermostat stays on, so the thermostat can always be reached.

**v1.20.0** — The En Suite is warmed to 20 degrees from 6am to 10am every day for the morning shower, whatever the weather. It used to be 22, and was skipped altogether when it was 10 degrees or more outside.

**v1.19.0** — A room you turn up or down through Indigo, the Home app or a dashboard is now left alone until its plan next changes, the same as a change made at the Evohome controller, a valve or the app. Until now the plugin put it back within five minutes.

**v1.18.1** — An open En Suite window switches the underfloor heating off within 30 seconds, even when the radiator is being left alone, and the clocks going back no longer confuse how old a room's reading is (best with RAMSES ESP 1.17.0).

**v1.18.0** — Fixes from an independent review: a room whose temperature has stopped updating is left alone (needs RAMSES ESP 1.16.0), an overheating alert that does not get through is tried again, and a missed 10am, an old snow forecast and the 1 hour setting no longer cause trouble.

**v1.17.0** — The En Suite drying run now looks at the room as well as the weather: it starts when the room is below 19 degrees, or when it is cold outside, and never when the room is already warm.

**v1.16.1** — On a morning too warm for the En Suite drying run, the Event Log now says so once, with the outdoor temperature.

**v1.16.0** — A room somebody changes by hand, at the Evohome controller, on a valve or in the app, is left alone until its plan next changes. The summer hold now ends by itself on the day heating is due back, even if Indigo is not running. Needs RAMSES ESP 1.15.0.

**v1.15.0** — Every morning the plugin checks the timetable on the Evohome controller against its own plans, and tells you if a room differs. Needs RAMSES ESP 1.13.0.

**v1.14.0** — Timed boosts and Force Heating On last the right time across a clock change. Away mode no longer adds up with Boost or Both out, and an open window closes the radiator while away. The Boost variable is no longer cancelled by overheat checking. Also a guest-plan fix, and old settings removed.

**v1.13.0** — If Indigo stops, the house goes back to the Evohome timetable: each radiator's temperature is sent for two hours at a time and renewed about hourly, instead of being held indefinitely. The summer hold stays permanent. Needs RAMSES ESP 1.12.0.

**v1.12.0** — Fixes made before the heating came back on. Last spring's overheating record is cleared rather than reloaded, a stopped Ecowitt station or a quiet radiator zone is noticed instead of trusted, and the En Suite underfloor heating is no longer left on by away mode, an open window or the plugin being stopped at 10am.

**v1.11.0** — A boost no longer heats a room with a window or outside door open. The room keeps its open-window setting, so the Dining Room stays at 16 degrees with the garden door open instead of going to 18, and picks the boost up again once everything is shut.

**v1.10.0** — The Dining Room now really does stay at 16 degrees with a garden window or door open, instead of dropping to 8. Overheating alerts go to the Pushover user key you set, away mode stops the En Suite drying run, and the drying run no longer starts on a morning it cannot tell is cold.

**v1.9.2** — The En Suite drying run only starts when it is colder outside than a limit you choose, 12 degrees to start with, or **No limit**. A morning that only turns cold at 7am still gets a run, and **Show En Suite Drying Run Status** shows the limit against the temperature now.

Every version is listed in the [version history](https://highsteads.github.io/EvoHomeControl/changelog.html).

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
