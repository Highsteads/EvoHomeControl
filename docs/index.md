---
title: Home
nav_order: 1
---

# EvoHome Heating Controller for Indigo

This plugin lets [Indigo](https://www.indigodomo.com) run the heating in a house fitted with **Honeywell Evohome** radiator controls, one room at a time, around the clock. It reaches the radiators through my [RAMSES ESP](https://github.com/Highsteads/RAMSES_ESP) plugin, which talks to them over their own radio from a small USB stick, so nothing goes through Honeywell's servers.

Every five minutes it works out the right temperature for each of the twelve rooms — from that room's plan for the hour, the weather outside, whether a window or door is open, and whether anyone is home — and sets each radiator to match.

## Before you go further

I wrote this plugin for my own house, and it shows. The twelve rooms, the window and door sensors in each one, and the temperature each room wants at each hour of the day are written into the plugin itself, using the Indigo device numbers from my house. On another house it will not work until those are changed to match yours, and that means editing two of the plugin's files. The [Getting started](getting-started.md) page says exactly which.

## What it does for you

- **Heats each room to its own plan,** with a temperature for every hour of the day, and a separate plan for the guest rooms when you have visitors.
- **Turns the heating down as it gets milder outside,** by one degree above 8 degrees and by two above 9, and turns radiators down to 8 degrees altogether above 14.
- **Adds a little heat when snow is forecast,** from the OpenWeatherMap forecast.
- **Turns a radiator down when its window or door is open,** and back up when it shuts.
- **Stops rooms overheating.** If a room is getting too warm, its radiator is turned down before it overshoots, and a Pushover message and an email go out if one gets well above where it should be.
- **Boosts the living areas** — the dining room, the living room and the hall kitchen — by two degrees for one or two hours from a menu item or a control page button, then puts them back.
- **Knows when you are away or out,** from Indigo variables, and holds the house at a safe, cheaper temperature.
- **Shuts the heating off for summer** between dates you choose, with a one-click way to have it back for 24 hours.
- **Looks after the En Suite** — a warm room from 6am on winter mornings with the underfloor heating on, and a morning drying run in summer to deal with wet towels.

## Where to go next

| If you want to... | Read |
|---|---|
| Install the plugin and fit it to your house | [Getting started](getting-started.md) |
| Understand how each room's temperature is decided | [How it works](how-it-works.md) |
| Use away, both out, guest, boost and snow | [Modes and boosts](modes-and-boosts.md) |
| Turn the heating off for summer | [The summer shut-off](summer-shut-off.md) |
| Understand the En Suite's morning schedule and drying run | [The En Suite](en-suite.md) |
| See the heating's state on a control page | [The Heating Controller device](devices.md) |
| Start a boost from a schedule, or react to an alert | [Actions and triggers](actions-and-triggers.md) |
| Know what every setting does | [Settings](settings.md) |
| Know what each item in the Plugins menu does | [The plugin menu](plugin-menu.md) |
| Sort out a problem | [When something goes wrong](troubleshooting.md) |
| See what changed in each version | [Version history](changelog.md) |

## Download

The latest version is always on the [Releases page](https://github.com/Highsteads/EvoHomeControl/releases/latest).
