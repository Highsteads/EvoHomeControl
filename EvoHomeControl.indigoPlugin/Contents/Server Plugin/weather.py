#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    weather.py
# Description: WeatherData class — Ecowitt primary / OWM fallback outdoor temperature
# Author:      CliveS & Claude Sonnet 4.6
# Date:        30-04-2026
# Version:     1.4

import os
import json
import tempfile
import logging
import datetime
import time

import indigo  # noqa — available in plugin context

from log_stamp import stamp as _stamp

# _slog()'s level= wants a Python logging int; a STRING is silently
# ignored and the line logs as Info. Translate string levels at the choke point.
_LOG_LEVELS = {
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "ERROR":    logging.ERROR,
    "DEBUG":    logging.DEBUG,
    "CRITICAL": logging.CRITICAL,
}


def _slog(message, level="INFO"):
    """indigo.server.log with string-level translation (string levels are otherwise
    silently downgraded to Info by Indigo)."""
    lvl = _LOG_LEVELS.get(level.upper(), logging.INFO) if isinstance(level, str) else level
    indigo.server.log(_stamp(message), level=lvl)


# OWM weather condition codes that indicate snow or freezing precipitation
# 600-622: all snow variants  |  511: freezing rain
_SNOW_CODES = frozenset(range(600, 623)) | {511}


# A reading older than these is not used. MEASURED 28-09-2026: the Ecowitt outdoor
# sensor's lastUpdate state moves about every 15 seconds, and its longest gap in 30
# days was 4 minutes. The Ecowitt plugin never sets deviceOnline to False, so the
# age is the only sign that the station has stopped. OWM is fetched every 15
# minutes while heating; three hours old means the fetches are failing.
ECOWITT_MAX_AGE_SECS = 1800
OWM_MAX_AGE_SECS     = 3 * 3600


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

    def __init__(self, api_key, cache_path, lat=0.0, lon=0.0,
                 bypass=False, bypass_temp=6.0, cache_ttl_secs=900,
                 ecowitt_dev_id=None):
        # NOTE: lat/lon default to 0.0/0.0 (Null Island) on purpose — callers
        # are expected to pass real coordinates resolved from IndigoSecrets
        # or PluginConfig. The plugin's startup path always does so; the
        # defensive default just avoids leaking the developer's home
        # coordinates if anyone instantiates this class directly.
        self.api_key        = api_key
        self.cache_path     = cache_path
        self.lat            = lat
        self.lon            = lon
        self._rebuild_url()
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

    def _rebuild_url(self):
        """(Re)build the OWM One Call URL from the current key + coordinates."""
        self.api_url = (
            f"https://api.openweathermap.org/data/3.0/onecall"
            f"?lat={self.lat}&lon={self.lon}&appid={self.api_key}"
            f"&units=metric&exclude=alerts"
        )

    def set_credentials(self, api_key, lat, lon):
        """Update key + coordinates and rebuild the request URL. Used by
        closedPrefsConfigUi so a changed API key or location takes effect
        immediately rather than only after a plugin restart."""
        self.api_key = api_key
        self.lat     = lat
        self.lon     = lon
        self._rebuild_url()

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
            _slog(
                f"[Weather] Cache read error (will fetch fresh): {e}",
                level="WARNING"
            )

        # --- Cache miss or stale: fetch from OWM ---
        if not self.api_key:
            _slog(
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
                _slog(
                    "[Weather] Missing 'current' in OWM response",
                    level="ERROR"
                )
                return False

            self.current     = data['current']
            self.minutely    = data.get('minutely', [])
            self.hourly      = data.get('hourly', [])
            self.daily       = data.get('daily', [])
            self.last_update = datetime.datetime.now()

            # Write cache atomically (temp file + os.replace) so a crash mid-write
            # cannot leave a truncated cache that the reader then trusts.
            try:
                cache_dir = os.path.dirname(self.cache_path)
                if cache_dir:
                    os.makedirs(cache_dir, exist_ok=True)
                # A temporary file of its own, so two writers can never share one.
                fd, tmp = tempfile.mkstemp(prefix=os.path.basename(self.cache_path) + ".",
                                           suffix=".tmp", dir=os.path.dirname(self.cache_path) or ".")
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump({'fetched_at': now_ts, 'data': data}, f)
                    f.flush()
                    os.fsync(f.fileno())
                # mkstemp makes the file private (0600); keep the mode the old file had.
                try:
                    os.chmod(tmp, os.stat(self.cache_path).st_mode & 0o777)
                except OSError:
                    os.chmod(tmp, 0o644)
                os.replace(tmp, self.cache_path)
            except OSError as e:
                _slog(
                    f"[Weather] Cache write error (data still usable): {e}",
                    level="WARNING"
                )

            return True

        except Exception as e:
            # requests exception text can echo the full request URL, which carries
            # the OWM API key as ?appid=<key> — redact it before it reaches the log.
            msg = str(e)
            if self.api_key:
                msg = msg.replace(self.api_key, "***")
            _slog(
                f"[Weather] Error fetching from OWM: {msg}",
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

        Never returns None, so it is right for the heating cycle, which must always
        have a number to work with. A rule that must know whether it is REALLY cold
        uses get_measured_outdoor_temp() instead.
        """
        # --- Primary: Ecowitt (when bypass=False and device configured) ---
        ecowitt = self._ecowitt_temp()
        if ecowitt is not None:
            return ecowitt

        # --- Secondary: OWM, if it is recent. self.current is never cleared, so a
        # run of failed fetches would otherwise hand back the last reading for ever.
        owm_temp = self.get_current('temp') if self._owm_age_secs() <= OWM_MAX_AGE_SECS else None
        if owm_temp is not None:
            try:
                return float(owm_temp)
            except (ValueError, TypeError):
                pass

        # --- Last resort ---
        return self.bypass_temp

    def _owm_age_secs(self):
        """Seconds since the OWM data in memory was loaded, or infinity if never."""
        if self.last_update is None:
            return float("inf")
        return (datetime.datetime.now() - self.last_update).total_seconds()

    def get_measured_outdoor_temp(self, max_owm_age_secs=3600):
        """
        A real outdoor reading, or None. Never the configured fallback temperature.

        Ecowitt first, then OpenWeatherMap - but only OWM data loaded within the
        last max_owm_age_secs, because self.current is never cleared: after the
        summer shut-off stops the hourly fetches it would otherwise hand back a
        reading from days ago as if it were now.
        """
        ecowitt = self._ecowitt_temp()
        if ecowitt is not None:
            return ecowitt
        if self.last_update is None:
            return None
        age = (datetime.datetime.now() - self.last_update).total_seconds()
        if age > max_owm_age_secs:
            return None
        owm_temp = self.get_current('temp')
        if owm_temp is None:
            return None
        try:
            return float(owm_temp)
        except (ValueError, TypeError):
            return None

    def _ecowitt_temp(self):
        """The Ecowitt outdoor reading as a float, or None when bypassed, not
        configured, offline or unreadable (each failure warns, rate-limited)."""
        if self.bypass or not self.ecowitt_dev_id:
            return None
        try:
            dev = indigo.devices[self.ecowitt_dev_id]
            online = dev.states.get("deviceOnline", True)
            temp   = dev.states.get("temperature")
            age    = self._ecowitt_age_secs(dev)
            if online and temp is not None and age is not None and age > ECOWITT_MAX_AGE_SECS:
                self._warn_ecowitt(
                    "stale",
                    f"Ecowitt outdoor reading has not changed for {age / 60:.0f} minutes"
                    f" — falling back to OWM"
                )
                return None
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
        return None

    @staticmethod
    def _ecowitt_age_secs(dev):
        """Seconds since the Ecowitt plugin last wrote this sensor: its lastUpdate
        state, else the device's lastChanged. None when neither can be read."""
        now = datetime.datetime.now()
        raw = dev.states.get("lastUpdate")
        if raw:
            try:
                seen = datetime.datetime.strptime(str(raw)[:19], "%Y-%m-%d %H:%M:%S")
                return (now - seen).total_seconds()
            except (ValueError, TypeError):
                pass
        changed = getattr(dev, "lastChanged", None)
        if isinstance(changed, datetime.datetime):
            return (now - changed).total_seconds()
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

    def _warn_ecowitt(self, reason, message):
        """Rate-limited warning for Ecowitt issues (one per reason per 30 min)."""
        now_ts   = time.time()
        last_ts  = self._ecowitt_last_warn.get(reason, 0)
        if now_ts - last_ts >= self._ECOWITT_WARN_INTERVAL:
            _slog(f"[Weather] {message}", level="WARNING")
            self._ecowitt_last_warn[reason] = now_ts

    def get_snow_forecast(self, hours=12, now_ts=None):
        """
        Scan hourly forecast for snow or freezing precipitation in next N hours.

        Returns a list of dicts (one per affected hour):
            hour_offset  — hours from now (0 = this hour)
            time_str     — formatted as HH:MM
            mm           — expected accumulation in mm (may be 0.0 if OWM omits it)
            description  — e.g. "Light Snow", "Heavy Snow"

        Empty list means no snow expected within the window.

        Hours are chosen by their own forecast time, not by position in the list:
        self.hourly is never cleared, so after failed fetches its first entries are
        hours that have already passed, and their snow would keep the heating boost
        on. A forecast older than OWM_MAX_AGE_SECS (the limit the outdoor reading
        uses) is not trusted at all, and an hour with no time is skipped.
        """
        if self._owm_age_secs() > OWM_MAX_AGE_SECS:
            return []
        now_ts  = time.time() if now_ts is None else now_ts
        horizon = now_ts + hours * 3600
        results = []
        for entry in self.hourly or []:
            try:
                hour_ts = int(entry.get("dt", 0))
            except (TypeError, ValueError):
                continue
            # OWM stamps each hour with its START, so the current hour is the one
            # whose start is less than an hour ago.
            if hour_ts <= 0 or hour_ts + 3600 <= now_ts or hour_ts >= horizon:
                continue
            code = ((entry.get("weather") or [{}])[0]).get("id", 0)
            if code in _SNOW_CODES:
                mm   = float((entry.get("snow") or {}).get("1h", 0.0))
                desc = ((entry.get("weather") or [{}])[0]).get("description", "snow").title()
                try:
                    time_str = datetime.datetime.fromtimestamp(hour_ts).strftime("%H:%M")
                except Exception:
                    time_str = "??"
                results.append({
                    "hour_offset": max(0, int((hour_ts - now_ts) // 3600)),
                    "time_str":    time_str,
                    "mm":          mm,
                    "description": desc,
                })
        return results
