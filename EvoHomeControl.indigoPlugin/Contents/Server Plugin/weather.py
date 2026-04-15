#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    weather.py
# Description: WeatherData class — OpenWeatherMap fetch with local JSON cache
# Author:      CliveS & Claude Sonnet 4.6
# Date:        15-04-2026
# Version:     1.0

import os
import json
import datetime
import time

import indigo  # noqa — available in plugin context


class WeatherData:
    """
    Fetches current conditions from OpenWeatherMap One Call API 3.0.

    Caches responses locally (default 15 min TTL) to avoid exceeding the
    OWM free-tier limit of 1000 calls/day when the plugin polls every 5 min.
    At 5-min intervals with a 15-min cache: ~96 API calls/day.

    When bypass=True (default, Ecowitt not yet configured) the class still
    fetches from OWM for temperature data; the 'bypass' flag controls whether
    the caller uses OWM temp in place of a local sensor reading.
    """

    def __init__(self, api_key, cache_path, lat=54.882, lon=-1.818,
                 bypass=True, bypass_temp=6.0, cache_ttl_secs=900):
        self.api_key      = api_key
        self.cache_path   = cache_path
        self.api_url      = (
            f"https://api.openweathermap.org/data/3.0/onecall"
            f"?lat={lat}&lon={lon}&appid={api_key}"
            f"&units=metric&exclude=alerts"
        )
        self.bypass       = bypass
        self.bypass_temp  = bypass_temp
        self.ttl          = cache_ttl_secs

        self.current      = {}
        self.minutely     = []
        self.hourly       = []
        self.daily        = []
        self.last_update  = None

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
        Return the best available outdoor temperature as a float, or None.

        When bypass=True (Ecowitt not configured): returns OWM temperature.
        When bypass=False: caller is expected to read from local Ecowitt device;
            this method still returns OWM temp as a fallback if local sensor fails.
        Returns None only if OWM is also unavailable.
        """
        owm_temp = self.get_current('temp')
        if owm_temp is not None:
            try:
                return float(owm_temp)
            except (ValueError, TypeError):
                pass

        if self.bypass:
            return self.bypass_temp  # configured fallback

        return None

    def get_precipitation_forecast(self, minutes=60):
        """Return precipitation forecast for next N minutes."""
        return list(self.minutely[:minutes]) if self.minutely else []

    def get_hourly_forecast(self, hours=48):
        """Return hourly forecast for next N hours."""
        return list(self.hourly[:hours]) if self.hourly else []

    def get_daily_forecast(self, days=7):
        """Return daily forecast for next N days."""
        return list(self.daily[:days]) if self.daily else []
