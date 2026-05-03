#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    weather.py
# Description: WeatherData class — Ecowitt primary / OWM fallback outdoor temperature
# Author:      CliveS & Claude Sonnet 4.6
# Date:        30-04-2026
# Version:     1.3

import os
import json
import datetime
import time

import indigo  # noqa — available in plugin context

# OWM weather condition codes that indicate snow or freezing precipitation
# 600-622: all snow variants  |  511: freezing rain
_SNOW_CODES = frozenset(range(600, 623)) | {511}


class WeatherData:
    """
    Outdoor temperature with Ecowitt as primary source, OWM as fallback.

    Priority when bypass=False (normal operation):
      1. Ecowitt outdoor sensor device state (ecowitt_dev_id)
      2. OWM One Call API 3.0 (cached, 15-min TTL, ~96 calls/day)
      3. bypass_temp (last-resort configured value)

    When bypass=True (Ecowitt unavailable):
      1. OWM cached/fetched temperature
      2. bypass_temp
    """

    def __init__(self, api_key, cache_path, lat=54.882, lon=-1.818,
                 bypass=False, bypass_temp=6.0, cache_ttl_secs=900,
                 ecowitt_dev_id=None):
        self.api_key        = api_key
        self.cache_path     = cache_path
        self.api_url        = (
            f"https://api.openweathermap.org/data/3.0/onecall"
            f"?lat={lat}&lon={lon}&appid={api_key}"
            f"&units=metric&exclude=alerts"
        )
        self.bypass         = bypass
        self.bypass_temp    = bypass_temp
        self.ttl            = cache_ttl_secs
        self.ecowitt_dev_id = ecowitt_dev_id

        self.current      = {}
        self.minutely     = []
        self.hourly       = []
        self.daily        = []
        self.last_update  = None

        # Ecowitt warning rate-limit: only log once per failure type per
        # _ECOWITT_WARN_INTERVAL seconds, so a missing/offline sensor does
        # not flood the event log every cycle.
        self._ecowitt_last_warn = {}   # {reason: timestamp}
        self._ECOWITT_WARN_INTERVAL = 1800  # 30 minutes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self):
        """
        Refresh weather data, using cache if still fresh.
        Returns True on success (cache hit or fresh fetch), False on failure.
        """
        now_ts = time.time()

        # --- Try cache first ---
        try:
            if os.path.exists(self.cache_path):
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                age_secs = now_ts - cached.get('fetched_at', 0)
                if age_secs < self.ttl:
                    data = cached.get('data', {})
                    if isinstance(data.get('current'), dict):
                        self.current     = data['current']
                        self.minutely    = data.get('minutely', [])
                        self.hourly      = data.get('hourly', [])
                        self.daily       = data.get('daily', [])
                        self.last_update = datetime.datetime.now()
                        return True  # cache hit — no log to avoid file write noise
        except (OSError, ValueError, KeyError) as e:
            indigo.server.log(
                f"[Weather] Cache read error (will fetch fresh): {e}",
                level="WARNING"
            )

        # --- Cache miss or stale: fetch from OWM ---
        if not self.api_key:
            indigo.server.log(
                "[Weather] No OWM API key configured — cannot fetch weather",
                level="WARNING"
            )
            return False

        try:
            import requests
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not isinstance(data.get('current'), dict):
                indigo.server.log(
                    "[Weather] Missing 'current' in OWM response",
                    level="ERROR"
                )
                return False

            self.current     = data['current']
            self.minutely    = data.get('minutely', [])
            self.hourly      = data.get('hourly', [])
            self.daily       = data.get('daily', [])
            self.last_update = datetime.datetime.now()

            # Write cache
            try:
                cache_dir = os.path.dirname(self.cache_path)
                if cache_dir:
                    os.makedirs(cache_dir, exist_ok=True)
                with open(self.cache_path, 'w', encoding='utf-8') as f:
                    json.dump({'fetched_at': now_ts, 'data': data}, f)
            except OSError as e:
                indigo.server.log(
                    f"[Weather] Cache write error (data still usable): {e}",
                    level="WARNING"
                )

            return True

        except Exception as e:
            indigo.server.log(
                f"[Weather] Error fetching from OWM: {e}",
                level="ERROR"
            )
            return False

    def get_current(self, key, default=None):
        """Return a value from the current conditions dict."""
        return self.current.get(key, default) if self.current else default

    def get_outdoor_temp(self):
        """
        Return best available outdoor temperature as float, or bypass_temp.

        Priority when bypass=False (Ecowitt active):
          1. Ecowitt outdoor sensor device state
          2. OWM cached/fetched temperature
          3. bypass_temp (last-resort configured value)

        When bypass=True (Ecowitt unavailable):
          1. OWM cached/fetched temperature
          2. bypass_temp
        """
        # --- Primary: Ecowitt (when bypass=False and device configured) ---
        if not self.bypass and self.ecowitt_dev_id:
            try:
                dev = indigo.devices[self.ecowitt_dev_id]
                online = dev.states.get("deviceOnline", True)
                temp   = dev.states.get("temperature")
                if online and temp is not None:
                    return float(temp)
                # Distinguish the two failure modes so the log is meaningful
                if not online:
                    self._warn_ecowitt(
                        "offline",
                        "Ecowitt device offline — falling back to OWM"
                    )
                else:
                    self._warn_ecowitt(
                        "no_temp",
                        "Ecowitt online but temperature state missing — falling back to OWM"
                    )
            except (KeyError, ValueError, TypeError) as e:
                self._warn_ecowitt(
                    "read_error",
                    f"Ecowitt read error ({e}) — falling back to OWM"
                )

        # --- Secondary: OWM ---
        owm_temp = self.get_current('temp')
        if owm_temp is not None:
            try:
                return float(owm_temp)
            except (ValueError, TypeError):
                pass

        # --- Last resort ---
        return self.bypass_temp

    def get_precipitation_forecast(self, minutes=60):
        """Return precipitation forecast for next N minutes."""
        return list(self.minutely[:minutes]) if self.minutely else []

    def get_hourly_forecast(self, hours=48):
        """Return hourly forecast for next N hours."""
        return list(self.hourly[:hours]) if self.hourly else []

    def get_daily_forecast(self, days=7):
        """Return daily forecast for next N days."""
        return list(self.daily[:days]) if self.daily else []

    def _warn_ecowitt(self, reason, message):
        """Rate-limited warning for Ecowitt issues (one per reason per 30 min)."""
        now_ts   = time.time()
        last_ts  = self._ecowitt_last_warn.get(reason, 0)
        if now_ts - last_ts >= self._ECOWITT_WARN_INTERVAL:
            indigo.server.log(f"[Weather] {message}", level="WARNING")
            self._ecowitt_last_warn[reason] = now_ts

    def get_snow_forecast(self, hours=12):
        """
        Scan hourly forecast for snow or freezing precipitation in next N hours.

        Returns a list of dicts (one per affected hour):
            hour_offset  — hours from now (0 = this hour)
            time_str     — formatted as HH:MM
            mm           — expected accumulation in mm (may be 0.0 if OWM omits it)
            description  — e.g. "Light Snow", "Heavy Snow"

        Empty list means no snow expected within the window.
        """
        results = []
        for i, entry in enumerate(self.hourly[:hours]):
            code = ((entry.get("weather") or [{}])[0]).get("id", 0)
            if code in _SNOW_CODES:
                mm   = float((entry.get("snow") or {}).get("1h", 0.0))
                desc = ((entry.get("weather") or [{}])[0]).get("description", "snow").title()
                try:
                    time_str = datetime.datetime.fromtimestamp(
                        int(entry.get("dt", 0))
                    ).strftime("%H:%M")
                except Exception:
                    time_str = "??"
                results.append({
                    "hour_offset": i,
                    "time_str":    time_str,
                    "mm":          mm,
                    "description": desc,
                })
        return results
