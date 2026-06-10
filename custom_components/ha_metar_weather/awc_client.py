"""
Aviation Weather Center (AWC) API client.

Direct REST API client for NOAA's Aviation Weather Center.
This is the primary data source for METAR data.

API Documentation: https://aviationweather.gov/data/api/

@license: MIT
@github: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

from .const import (
    KNOTS_TO_KMH,
    MILES_TO_KM,
    INHG_TO_HPA,
    AWC_API_BASE_URL,
    AWC_API_TIMEOUT,
    DEFAULT_EXCELLENT_VISIBILITY_KM,
)
from .utils import calculate_humidity

_LOGGER = logging.getLogger(__name__)


class AWCApiError(HomeAssistantError):
    """Exception for AWC API errors."""


class AWCApiClient:
    """Client for Aviation Weather Center REST API."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the AWC API client.

        Args:
            hass: Home Assistant instance
        """
        self.hass = hass
        self.session = async_get_clientsession(hass)

    async def fetch_metar(
        self,
        station_ids: str | List[str],
        hours_before: float = 2.0
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch METAR data from AWC API.

        Args:
            station_ids: Single ICAO code or list of ICAO codes
            hours_before: Hours of data to retrieve (default 2)

        Returns:
            List of METAR data dictionaries or None on error
        """
        # Normalize station IDs
        if isinstance(station_ids, list):
            ids = ",".join(s.upper() for s in station_ids)
        else:
            ids = station_ids.upper()

        params = {
            "ids": ids,
            "format": "json",
            "hours": hours_before,
        }

        try:
            _LOGGER.debug("Fetching METAR from AWC API for: %s", ids)

            async with self.session.get(
                AWC_API_BASE_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=AWC_API_TIMEOUT)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug("AWC API response: %s", data)

                    # Handle null, empty, or invalid responses
                    if data is None:
                        _LOGGER.warning("AWC API returned null for station(s): %s", ids)
                        return None

                    if isinstance(data, list):
                        # Filter out None and empty dicts from list
                        valid_data = [
                            item for item in data
                            if item and isinstance(item, dict)
                        ]
                        return valid_data if valid_data else None

                    if isinstance(data, dict) and data:
                        return [data]

                    _LOGGER.warning("AWC API returned empty/invalid data for station(s): %s", ids)
                    return None

                elif response.status == 204:
                    _LOGGER.warning("No METAR data available for station(s): %s", ids)
                    return None

                elif response.status == 400:
                    text = await response.text()
                    _LOGGER.error("AWC API bad request: %s", text)
                    raise AWCApiError(f"Invalid request: {text}")

                elif response.status == 429:
                    # TODO: Implement exponential backoff or token bucket for rate limiting
                    _LOGGER.warning("AWC API rate limit exceeded")
                    raise AWCApiError("Rate limit exceeded")

                else:
                    text = await response.text()
                    _LOGGER.error(
                        "AWC API error: status=%s, response=%s",
                        response.status,
                        text
                    )
                    raise AWCApiError(f"API error: {response.status}")

        except aiohttp.ClientError as err:
            _LOGGER.error("AWC API connection error: %s", err)
            raise AWCApiError(f"Connection error: {err}") from err

        except json.JSONDecodeError as err:
            _LOGGER.error("AWC API returned invalid JSON: %s", err)
            raise AWCApiError(f"Invalid JSON response: {err}") from err

        except (TimeoutError, asyncio.TimeoutError) as err:
            _LOGGER.error("AWC API timeout")
            raise AWCApiError("Request timeout") from err

    async def fetch_single_metar(self, icao: str) -> Optional[Dict[str, Any]]:
        """Fetch METAR data for a single station.

        Args:
            icao: ICAO airport code

        Returns:
            METAR data dictionary or None
        """
        result = await self.fetch_metar(icao)
        if result and len(result) > 0:
            return result[0]
        return None

    @staticmethod
    def parse_awc_response(data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract AWC's authoritative numerics and metadata.

        Returns numeric fields plus raw_metar, station_name and observation_time
        only. Textual fields (weather, clouds, trend, runway states, cavok/auto)
        are intentionally NOT produced here: they are derived from raw_metar by
        the shared MetarParser so the AWC and AVWX paths agree (issue #3).

        The AWC API returns JSON. Key fields (as of 2026):
        - obsTime: int (epoch seconds) — previously was ISO string
        - temp/dewp: int (°C) — previously float
        - altim: int (hPa) — previously float (inHg)
        - visib: str (statute miles, e.g. "6+", "10")
        - wspd/wgst: int (knots)
        - rawOb: str (raw METAR)
        - name: str (station name)

        Args:
            data: AWC API response data

        Returns:
            Numerics/metadata dictionary (no textual weather fields)
        """
        try:
            # Parse wind data
            wind_direction = data.get("wdir")
            wind_speed = data.get("wspd")
            wind_gust = data.get("wgst")
            wind_variable = None

            # Handle variable wind direction
            if wind_direction == "VRB" or wind_direction is None:
                wind_variable = "VRB" if wind_direction == "VRB" else None
                wind_direction = None
            elif wind_direction == 0 and not data.get("wspd"):
                # Calm wind (00000KT): AWC sends wdir=0/wspd=0, but direction
                # has no meaning - mirror the parser, which yields None.
                wind_direction = None
            else:
                # Not None here; plain float() keeps a valid 0 (north) intact
                wind_direction = float(wind_direction)

            # Convert wind speed from knots to km/h
            if wind_speed is not None:
                wind_speed = round(float(wind_speed) * KNOTS_TO_KMH, 6)
            if wind_gust is not None:
                wind_gust = round(float(wind_gust) * KNOTS_TO_KMH, 6)

            # Parse visibility (AWC returns in statute miles)
            visibility = None
            visib = data.get("visib")
            if visib is not None:
                if isinstance(visib, str):
                    # Handle "6+", "10+", etc. - means excellent visibility (10+ SM = 16+ km)
                    if "+" in visib:
                        try:
                            base_value = float(visib.replace("+", ""))
                            visibility = round(base_value * MILES_TO_KM, 6)
                        except ValueError:
                            visibility = DEFAULT_EXCELLENT_VISIBILITY_KM
                    # Handle mixed fractions like "1 1/2" (1.5 SM)
                    elif " " in visib and "/" in visib:
                        try:
                            space_parts = visib.split(" ")
                            if len(space_parts) == 2:
                                whole = float(space_parts[0])
                                frac_parts = space_parts[1].split("/")
                                if len(frac_parts) == 2:
                                    frac = float(frac_parts[0]) / float(frac_parts[1])
                                    visibility = round((whole + frac) * MILES_TO_KM, 6)
                        except (ValueError, ZeroDivisionError):
                            visibility = None
                    # Handle simple fractions like "1/2", "1/4", "3/4"
                    elif "/" in visib:
                        try:
                            parts = visib.split("/")
                            if len(parts) == 2:
                                numerator = float(parts[0])
                                denominator = float(parts[1])
                                visibility = round((numerator / denominator) * MILES_TO_KM, 6)
                        except (ValueError, ZeroDivisionError):
                            visibility = None
                    else:
                        try:
                            # Convert statute miles to kilometers
                            visibility = round(float(visib) * MILES_TO_KM, 6)
                        except ValueError:
                            visibility = None
                else:
                    # Numeric value in statute miles
                    visibility = round(float(visib) * MILES_TO_KM, 6)

            # Parse pressure
            # AWC API now returns altim in hPa (e.g. 1021).
            # Older responses used inHg (e.g. 30.12). Auto-detect by value range.
            pressure = None
            altim = data.get("altim")
            if altim is not None:
                try:
                    altim_f = float(altim)
                    if altim_f < 100:
                        # Value in inHg (e.g. 30.12) — convert to hPa
                        pressure = round(altim_f * INHG_TO_HPA, 6)
                    else:
                        pressure = round(altim_f, 1)
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Failed to parse altimeter '%s' for %s",
                        altim, data.get("icaoId", "unknown"),
                    )

            # Calculate humidity using shared utility function
            temp = data.get("temp")
            dewp = data.get("dewp")
            humidity = calculate_humidity(temp, dewp)

            # Parse observation time
            # AWC API returns obsTime as epoch int (since ~2026) or ISO string
            obs_time = data.get("obsTime")
            if obs_time is not None:
                try:
                    if isinstance(obs_time, (int, float)):
                        if obs_time < 0:
                            raise ValueError(f"Negative epoch value: {obs_time}")
                        observation_time = datetime.fromtimestamp(obs_time, tz=timezone.utc)
                    elif isinstance(obs_time, str):
                        if obs_time.endswith("Z"):
                            obs_time_parsed = obs_time[:-1] + "+00:00"
                        else:
                            obs_time_parsed = obs_time
                        observation_time = datetime.fromisoformat(obs_time_parsed)
                    else:
                        _LOGGER.warning(
                            "Unexpected obsTime type %s for %s, using current time",
                            type(obs_time).__name__,
                            data.get("icaoId", "unknown"),
                        )
                        observation_time = datetime.now(timezone.utc)
                except (ValueError, OSError, OverflowError) as err:
                    _LOGGER.warning(
                        "Failed to parse observation time '%s': %s. Using current time.",
                        obs_time, err
                    )
                    observation_time = datetime.now(timezone.utc)
            else:
                _LOGGER.warning(
                    "No observation time (obsTime) in AWC response for %s, using current time",
                    data.get("icaoId", "unknown")
                )
                observation_time = datetime.now(timezone.utc)

            raw_metar = data.get("rawOb", "")

            # CAVOK implies visibility of at least 10 km. The textual CAVOK flag
            # itself is produced by the shared parser; here we only backfill the
            # numeric so AWC's authoritative visibility stays correct.
            if visibility is None and "CAVOK" in raw_metar:
                visibility = 10.0

            # Numerics and metadata only. All textual fields (weather, clouds,
            # trend, runway states, cavok/auto) are derived by the shared
            # MetarParser from raw_metar so both data sources agree (issue #3).
            parsed = {
                "raw_metar": raw_metar,
                "station_name": data.get("name"),
                "observation_time": observation_time.isoformat(),
                "temperature": temp,
                "dew_point": dewp,
                "humidity": humidity,
                "wind_speed": wind_speed,
                "wind_direction": wind_direction,
                "wind_gust": wind_gust,
                "wind_variable_direction": wind_variable,
                "visibility": visibility,
                "pressure": pressure,
            }

            _LOGGER.debug("Parsed AWC numerics for %s: %s", data.get("icaoId"), parsed)
            return parsed

        except Exception as err:
            _LOGGER.error("Error parsing AWC response: %s", err)
            raise AWCApiError(f"Failed to parse response: {err}") from err


async def validate_station_awc(hass: HomeAssistant, icao: str) -> bool:
    """Validate station exists using AWC API.

    Args:
        hass: Home Assistant instance
        icao: ICAO airport code

    Returns:
        True if station is valid and has data
    """
    client = AWCApiClient(hass)
    try:
        result = await client.fetch_single_metar(icao)
        return result is not None
    except AWCApiError:
        return False

