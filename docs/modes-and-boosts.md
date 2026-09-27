---
title: Modes and boosts
nav_order: 4
---

# Modes and boosts

Most of the modes are Indigo variables, so anything in Indigo can switch them — a schedule, a trigger, a control page button, or a presence sensor. The plugin reads them at every heating check. None of them has any effect during the [summer shut-off](summer-shut-off.md), when the heating check does not run.

## Away

For when the house is empty for days at a time.

Set the **Away** variable to `true`, or use the **Set Away Mode** action, and every room is held at 14 degrees, or 16 degrees when it is below 3 degrees outside, to keep the house safe from frost. A room that is overheating is still turned down. Set it back to `false`, or run **Set Away Mode** with **Inactive (resume schedule)**, and the rooms go back to their plans.

The **Set Away Mode** action runs a heating check straight away, so the change happens within 30 seconds rather than at the next check.

## Both out

For a few hours out, when the house will need to be warm again soon.

Set the **Both out** variable to `yes` and every room's target drops by four degrees. Set it to `no` to go back to normal.

## Guests

- Set the **Bedroom 2 guest** variable to `true` and Bedroom 2 follows its guest plan, a degree or two warmer, and may go up to 18 degrees rather than 16.
- Set the **Bedroom 3 guest** variable to `true` and Bedroom 3 follows its guest plan.
- Either one also puts the Bathroom on its guest plan, which is warmer from 5am to 10am and cooler the rest of the day.

## Boost

Set the **Boost** variable to `yes` and the living areas get extra heat until you set it back to `no`:

| Room | Extra |
|---|---|
| Conservatory | 3 degrees |
| Dining Room | 2 degrees |
| Hall Kitchen | 2 degrees |
| Living Room Door | 2 degrees |
| Living Room Front | 2 degrees |

The bedrooms, Bathroom, En Suite, Hall Bedroom and Utility Room are not boosted.

## Timed boost

A timed boost adds two degrees to the **Dining Room**, **Hall Kitchen**, **Living Room Door** and **Living Room Front** for one hour or two, then ends by itself. Start it from **Plugins → EvoHome Heating Controller → Start Timed Boost (1 hour)** or **(2 hours)**, or from the actions of the same names, which you can put on a control page button.

- **Cancel Timed Boost** ends it early.
- When it ends, the Event Log lists the temperature each room goes back to.
- A timed boost carries on after the plugin or Indigo restarts, as long as its time has not run out.
- It does not start during the summer shut-off. Use **Force Heating On (24 hours)** first if you need the heat.

A room that is overheating is not boosted, and the boost does not stack on top of the Boost variable.

## Snow boost

When OpenWeatherMap forecasts snow or freezing rain in the next 12 hours, one degree is added to every room, and the Event Log says so. You can change the extra, the number of hours ahead it looks, or switch it off, in the [settings](settings.md). The **Snow Forecast Detected** trigger runs when snow first appears in the forecast.

This needs an OpenWeatherMap key, because an Ecowitt station does not forecast.
