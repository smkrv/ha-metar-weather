"""
METAR data API client.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
import logging
import aiohttp
import async_timeout
import time
from datetime import datetime
from typing import Optional, Dict, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

class MetarApiClient:
    """METAR API client."""

    def __init__(self, hass: HomeAssistant, icao: str) -> None:
        """Initialize the API client."""
        self.hass = hass
        self.icao = icao.upper()
        self._session = async_get_clientsession(hass)
        self._last_modified = None
        self._last_data = None
        self._base_url = "https://tgftp.nws.noaa.gov/data/observations/metar/stations"
        self._retry_count = 0

    async def fetch_data(self) -> Optional[Dict[str, Any]]:
        """Fetch METAR data from the server."""
        url = f"{self._base_url}/{self.icao}.TXT"

        try:
            with async_timeout.timeout(10):
                headers = {}
                if self._last_modified:
                    headers['If-Modified-Since'] = self._last_modified

                async with self._session.get(url, headers=headers) as response:
                    if response.status == 304:
                        _LOGGER.debug("Data not modified since last fetch")
                        return self._last_data

                    if response.status != 200:
                        raise HomeAssistantError(
                            f"Error fetching METAR data: {response.status}"
                        )

                    self._last_modified = response.headers.get('Last-Modified')
                    content = await response.text()

                    parsed_data = self._parse_metar(content)
                    self._last_data = parsed_data
                    self._retry_count = 0
                    return parsed_data

        except Exception as err:
            _LOGGER.error("Error fetching METAR data: %s", err)
            await self._handle_error()
            return None

    async def _handle_error(self) -> None:
        """Handle error with exponential backoff."""
        from .const import RETRY_INTERVALS

        if self._retry_count < len(RETRY_INTERVALS):
            wait_time = RETRY_INTERVALS[self._retry_count]
            self._retry_count += 1
            _LOGGER.warning(
                "Will retry fetching METAR data in %d minutes", wait_time
            )
        else:
            _LOGGER.error(
                "Maximum retry attempts reached. Will try again in 1 hour"
            )

    def _parse_metar(self, raw_metar: str) -> Dict[str, Any]:
        """Parse raw METAR data into structured format."""
        from metar import Metar

        try:
            # First line contains the time, second line contains the METAR
            lines = raw_metar.strip().split('\n')
            observation_time = datetime.strptime(
                lines[0].strip(),
                "%Y/%m/%d %H:%M"
            )
            metar_data = Metar.Metar(lines[1].strip())

            data = {
                "raw_metar": lines[1].strip(),
                "observation_time": observation_time.isoformat(),
                "temperature": self._celsius_to_system(
                    metar_data.temp.value() if metar_data.temp else None
                ),
                "dew_point": self._celsius_to_system(
                    metar_data.dewpt.value() if metar_data.dewpt else None
                ),
                "wind_speed": metar_data.wind_speed.value() if metar_data.wind_speed else None,
                "wind_direction": metar_data.wind_dir.value() if metar_data.wind_dir else None,
                "visibility": metar_data.vis.value() if metar_data.vis else None,
                "pressure": metar_data.press.value() if metar_data.press else None,
                "weather": str(metar_data.present_weather()) if metar_data.present_weather() else None,
                "cloud_coverage": self._get_cloud_coverage(metar_data),
                "station_name": metar_data.station_id,
            }

            return data

        except Exception as err:
            _LOGGER.error("Error parsing METAR data: %s", err)
            return None

    def _celsius_to_system(self, temp: Optional[float]) -> Optional[float]:
        """Convert temperature based on system settings."""
        if temp is None:
            return None

        if self.hass.config.units.temperature_unit == "°F":
            return round((temp * 9/5) + 32, 1)
        return round(temp, 1)

    def _get_cloud_coverage(self, metar_data: 'Metar.Metar') -> Optional[str]:
        """Get cloud coverage information."""
        if not metar_data.sky:
            return None

        coverage = []
        for sky in metar_data.sky:
            if sky[0] and sky[1]:
                coverage.append(f"{sky[0]} at {sky[1]} feet")
        return ", ".join(coverage) if coverage else None
