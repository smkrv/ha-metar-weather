"""
Aviation Weather Center (AWC) TAF API client.

Minimal client for the AWC Data API's TAF endpoint (sibling of the METAR
endpoint already used in awc_client.py). Currently only extracts the raw
TAF string - the raw_taf sensor is the only TAF sensor this integration
exposes right now, so nothing beyond that is parsed. AWC's JSON response
does carry a fully-decoded per-period forecast (``fcsts``) if a "decoded"
sensor is added later; see the "raw_taf" sensor description in sensor.py.

API Documentation: https://aviationweather.gov/data/api/

@license: MIT
@github: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

from .const import AWC_API_TAF_BASE_URL, AWC_API_TAF_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class AWCTafApiError(HomeAssistantError):
    """Exception for AWC TAF API errors."""


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
            "issue_time": str | None}`` or None if the station has no
            current TAF (not every station with METAR reports also issues
            TAFs) or on error.
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
                    _LOGGER.info("No TAF available for station %s", icao)
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
            _LOGGER.info("AWC returned no TAF data for %s", icao)
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
        # current one. Fall back to the newest issueTime if that flag is
        # absent from an older API response.
        report = max(
            candidates,
            key=lambda item: (
                int(item.get("mostRecent") or 0),
                item.get("issueTime") or "",
            ),
        )

        raw_taf = report.get("rawTAF")
        if not raw_taf:
            _LOGGER.warning(
                "AWC TAF response for %s has no rawTAF field", icao
            )
            return None

        return {
            "raw_taf": raw_taf,
            "station_name": report.get("name"),
            "issue_time": report.get("issueTime"),
        }


class TafApiClient:
    """Thin wrapper giving the TAF coordinator the same shape as
    api_client.MetarApiClient (fetch_data() + last_source), so
    TafDataUpdateCoordinator in __init__.py mirrors
    MetarDataUpdateCoordinator.

    Currently AWC-only, no AVWX fallback (unlike the METAR path in
    api_client.py) - a follow-up if AWC's TAF endpoint proves less
    reliable than its METAR endpoint in practice.
    """

    def __init__(self, hass: HomeAssistant, icao: str) -> None:
        self.hass = hass
        self.icao = icao.upper()
        self._awc_client = AWCTafApiClient(hass)
        self._last_source: Optional[str] = None

    @property
    def last_source(self) -> Optional[str]:
        """Return the last used data source name."""
        return self._last_source

    async def fetch_data(self) -> Optional[Dict[str, Any]]:
        """Fetch the current TAF for this station.

        Returns:
            ``{"raw_taf": ..., "station_name": ..., "issue_time": ...}``
            or None if the station has no current TAF / the fetch failed.
        """
        data = await self._awc_client.fetch_taf(self.icao)
        if data:
            self._last_source = "awc"
        return data


async def validate_station_has_taf(hass: HomeAssistant, icao: str) -> bool:
    """Check whether a station currently publishes a TAF.

    Not every station that reports METAR also issues a TAF (smaller
    airports typically don't), so this is informational, not a hard
    requirement for config_flow validation.

    Args:
        hass: Home Assistant instance
        icao: ICAO airport code

    Returns:
        True if the station has a current TAF
    """
    client = AWCTafApiClient(hass)
    try:
        result = await client.fetch_taf(icao)
        return result is not None
    except AWCTafApiError:
        return False
