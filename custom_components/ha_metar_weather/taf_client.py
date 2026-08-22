"""
Aviation Weather Center (AWC) TAF API client.

Minimal client for the AWC Data API's TAF endpoint (sibling of the METAR
endpoint already used in awc_client.py). Currently only extracts the raw
TAF string plus issue time - the taf sensor is the only TAF sensor this
integration exposes right now, so nothing beyond that is parsed. AWC's
JSON response does carry a fully-decoded per-period forecast (``fcsts``)
if a "decoded" sensor is added later; see TAF_SENSOR_TYPES in sensor.py.

API Documentation: https://aviationweather.gov/data/api/

@license: MIT
@github: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

from .awc_client import AWCApiClient
from .const import AWC_API_TAF_BASE_URL, AWC_API_TAF_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class AWCTafApiError(HomeAssistantError):
    """Exception for AWC TAF API errors."""


def parse_issue_time(raw: Any) -> Optional[datetime]:
    """Parse AWC's issueTime into an aware UTC datetime.

    Delegates to AWCApiClient._parse_time_value, which absorbs every wire
    format AWC has used for its time fields: ISO 8601 with a trailing Z,
    legacy "YYYY-MM-DD HH:MM:SS", and epoch seconds (validTimeFrom/To are
    already epoch ints in the same TAF response today, and obsTime flipped
    from ISO to epoch in 2026-03, so issueTime flipping too is a matter of
    time). Returns None when the value can't be parsed - callers treat
    that as "no issue time", never as an error.
    """
    epoch = AWCApiClient._parse_time_value(raw)
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


class AWCTafApiClient:
    """Client for the AWC TAF endpoint (aviationweather.gov/api/data/taf)."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the AWC TAF API client.

        Args:
            hass: Home Assistant instance
        """
        self.hass = hass
        self.session = async_get_clientsession(hass)

    async def fetch_taf(self, icao: str) -> Optional[Dict[str, Any]]:
        """Fetch the current TAF for a station.

        Args:
            icao: ICAO airport code

        Returns:
            ``{"raw_taf": str, "station_name": str | None,
            "issue_time": datetime | None}`` or None if the station has no
            current TAF (not every station with METAR reports also issues
            TAFs - AWC answers 204 or an empty list for those).

        Raises:
            AWCTafApiError: on HTTP errors, timeouts, or invalid JSON.
        """
        params = {"ids": icao.upper(), "format": "json"}

        try:
            _LOGGER.debug("Fetching TAF from AWC API for: %s", icao)

            async with self.session.get(
                AWC_API_TAF_BASE_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=AWC_API_TAF_TIMEOUT),
            ) as response:
                if response.status == 204:
                    _LOGGER.debug("No TAF available for station %s", icao)
                    return None

                if response.status != 200:
                    text = await response.text()
                    _LOGGER.error(
                        "AWC TAF API error for %s: status=%s, response=%s",
                        icao, response.status, text,
                    )
                    raise AWCTafApiError(f"API error: {response.status}")

                data = await response.json()

        except aiohttp.ClientError as err:
            _LOGGER.error("AWC TAF API connection error for %s: %s", icao, err)
            raise AWCTafApiError(f"Connection error: {err}") from err
        except json.JSONDecodeError as err:
            _LOGGER.error("AWC TAF API returned invalid JSON for %s: %s", icao, err)
            raise AWCTafApiError(f"Invalid JSON response: {err}") from err
        except (TimeoutError, asyncio.TimeoutError) as err:
            _LOGGER.error("AWC TAF API timeout for %s", icao)
            raise AWCTafApiError("Request timeout") from err

        if not data:
            _LOGGER.debug("AWC returned no TAF data for %s", icao)
            return None
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return None

        candidates = [item for item in data if item and isinstance(item, dict)]
        if not candidates:
            return None

        # AWC can return more than one bulletin for a station (e.g. the
        # scheduled TAF plus a just-issued AMD); "mostRecent" flags the
        # current one. Ties fall back to the newest issueTime, compared as
        # parsed datetimes so mixed wire formats (ISO vs epoch) rank
        # correctly instead of raising on a str/int comparison.
        def _bulletin_rank(item: Dict[str, Any]) -> tuple:
            try:
                most_recent = int(item.get("mostRecent") or 0)
            except (TypeError, ValueError):
                most_recent = 0
            issued = parse_issue_time(item.get("issueTime"))
            return (
                most_recent,
                issued or datetime.min.replace(tzinfo=timezone.utc),
            )

        report = max(candidates, key=_bulletin_rank)

        raw_taf = report.get("rawTAF")
        if not raw_taf:
            _LOGGER.warning(
                "AWC TAF response for %s has no rawTAF field", icao
            )
            return None

        return {
            "raw_taf": raw_taf,
            "station_name": report.get("name"),
            "issue_time": parse_issue_time(report.get("issueTime")),
        }
