"""
Aviation Weather Center (AWC) API client.

Direct REST API client for NOAA's Aviation Weather Center.
This is the primary data source for METAR data.

API Documentation: https://aviationweather.gov/data/api/

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

# AWC API Configuration
AWC_API_BASE_URL = "https://aviationweather.gov/api/data/metar"
AWC_API_TIMEOUT = 30  # seconds
AWC_API_RATE_LIMIT = 100  # requests per minute


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
        self._last_request_time: Optional[datetime] = None

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
                self._last_request_time = datetime.now(timezone.utc)

                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug("AWC API response: %s", data)
                    return data if isinstance(data, list) else [data]

                elif response.status == 204:
                    _LOGGER.warning("No METAR data available for station(s): %s", ids)
                    return None

                elif response.status == 400:
                    text = await response.text()
                    _LOGGER.error("AWC API bad request: %s", text)
                    raise AWCApiError(f"Invalid request: {text}")

                elif response.status == 429:
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

        except TimeoutError as err:
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

    def parse_awc_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse AWC API response into internal format.

        The AWC API returns JSON with the following structure:
        {
            "icaoId": "KJFK",
            "obsTime": "2024-01-15T12:00:00Z",
            "temp": 5.0,
            "dewp": 2.0,
            "wdir": 270,
            "wspd": 10,
            "wgst": null,
            "visib": "10+",
            "altim": 30.12,
            "slp": 1020.5,
            "qcField": 0,
            "wxString": null,
            "presTend": null,
            "maxT": null,
            "minT": null,
            "maxT24": null,
            "minT24": null,
            "precip": null,
            "pcp3hr": null,
            "pcp6hr": null,
            "pcp24hr": null,
            "snow": null,
            "vertVis": null,
            "metarType": "METAR",
            "rawOb": "KJFK 151200Z 27010KT 10SM FEW250 05/02 A3012",
            "mostRecent": 1,
            "lat": 40.6398,
            "lon": -73.7789,
            "elev": 4,
            "prior": 0,
            "name": "John F Kennedy Intl",
            "clouds": [{"cover": "FEW", "base": 25000}]
        }

        Args:
            data: AWC API response data

        Returns:
            Parsed data in internal format
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
            else:
                wind_direction = float(wind_direction) if wind_direction else None

            # Convert wind speed from knots to km/h
            if wind_speed is not None:
                wind_speed = round(float(wind_speed) * 1.852, 1)
            if wind_gust is not None:
                wind_gust = round(float(wind_gust) * 1.852, 1)

            # Parse visibility (AWC returns in statute miles)
            visibility = None
            visib = data.get("visib")
            if visib is not None:
                if isinstance(visib, str):
                    # Handle "6+", "10+", etc. - means excellent visibility
                    if "+" in visib:
                        visibility = 10.0  # Cap at 10 km
                    else:
                        try:
                            # Convert statute miles to kilometers
                            visibility = round(float(visib) * 1.60934, 1)
                            # Cap at 10 km for consistency
                            if visibility > 10.0:
                                visibility = 10.0
                        except ValueError:
                            visibility = None
                else:
                    # Numeric value in statute miles
                    visibility = round(float(visib) * 1.60934, 1)
                    if visibility > 10.0:
                        visibility = 10.0

            # Parse pressure (AWC API already returns in hPa/millibars)
            pressure = None
            altim = data.get("altim")
            if altim is not None:
                pressure = round(float(altim), 1)

            # Parse clouds
            cloud_layers = []
            clouds = data.get("clouds", [])
            if clouds:
                for cloud in clouds:
                    cover = cloud.get("cover", "")
                    base = cloud.get("base")
                    cloud_layers.append({
                        "coverage": cover,
                        "height": base * 100 if base else None,  # Convert to feet
                        "type": cloud.get("type")
                    })

            # Calculate humidity
            temp = data.get("temp")
            dewp = data.get("dewp")
            humidity = None
            if temp is not None and dewp is not None:
                try:
                    e = 6.11 * 10.0 ** (7.5 * dewp / (237.7 + dewp))
                    es = 6.11 * 10.0 ** (7.5 * temp / (237.7 + temp))
                    humidity = round((e / es) * 100, 1)
                except (ZeroDivisionError, ValueError):
                    humidity = None

            # Parse observation time
            obs_time = data.get("obsTime")
            if obs_time:
                try:
                    observation_time = datetime.fromisoformat(
                        obs_time.replace("Z", "+00:00")
                    )
                except ValueError:
                    observation_time = datetime.now(timezone.utc)
            else:
                observation_time = datetime.now(timezone.utc)

            # Determine CAVOK
            cavok = False
            raw_metar = data.get("rawOb", "")
            if "CAVOK" in raw_metar:
                cavok = True
                visibility = 10.0

            # Parse weather string
            weather = data.get("wxString") or "Clear"

            # Build parsed data
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
                "weather": weather,
                "cloud_layers": cloud_layers,
                "cloud_coverage_state": cloud_layers[0]["coverage"] if cloud_layers else "Clear",
                "cloud_coverage_height": cloud_layers[0]["height"] if cloud_layers else None,
                "cloud_coverage_type": cloud_layers[0].get("type", "N/A") if cloud_layers else "N/A",
                "cavok": cavok,
                "auto": data.get("metarType") == "SPECI",
                "trend": None,
                "runway_states": {},
            }

            _LOGGER.debug("Parsed AWC data for %s: %s", data.get("icaoId"), parsed)
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

