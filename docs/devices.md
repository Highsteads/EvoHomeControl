---
title: The Heating Controller device
nav_order: 7
---

# The Heating Controller device

The plugin does its work without any device of its own. The radiators are the RAMSES ESP plugin's devices, and the plugin simply sets them.

If you want the state of the heating on a control page, or a trigger when it changes, add one **Heating Controller** device: choose **New Device**, set **Type** to **EvoHome Heating Controller**, pick **Heating Controller**, and click **Save**. It has no settings. It is brought up to date at every heating check. Only one is needed — if you make more, only the first is updated.

The device list shows its **Active Mode**. Its icon turns to the tripped colour while any room is overheating.

## What it shows

| Shown as | What it means |
|---|---|
| **Active Mode** | The one mode that matters most right now: **Forced On (summer)**, **Summer Off**, **Away**, **Both-Out**, **Timed Boost 1h** or **Timed Boost 2h**, **Boost**, **En Suite Morning**, or **Schedule** when none of them is on. It shows **Starting** until the first check after the plugin starts. |
| **Outdoor Temp (degC)** | The outdoor temperature the plugin is using. **N/A** during the summer shut-off, when the plugin does not read it. |
| **Temp Offset (degC)** | How much the weather and any snow boost are adding to or taking off every room, such as **-2.0**. |
| **Away Mode Active** | **True** or **False**. |
| **Both-Out Active** | **True** or **False**. |
| **Global Boost Active** | **True** when the Boost variable is on. |
| **Timed Boost Active** | **True** while a timed boost is running. |
| **Timed Boost Expiry** | The time a running timed boost ends, such as **18:30**. Empty otherwise. |
| **En Suite Morning Active** | **True** while the En Suite morning schedule is running. |
| **Summer Shut-off Status** | A sentence saying whether the summer shut-off is on and when heating returns, how long a 24-hour override has left, or that the heating is in season. |
| **Rooms Overheating** | The rooms whose radiators are turned down because they are too warm, or **None**. |
| **Last Cycle** and **Last Update** | The date and time of the last heating check. |

During the summer shut-off the away, both out and boost states keep the values they had when the shut-off began, because the plugin does not read the mode variables until it ends.
