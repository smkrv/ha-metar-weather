"""METAR data API client using AVWX."""
from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import avwx
from avwx.exceptions import BadStation, SourceError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError
from .const import (
    RETRY_INTERVALS,
    VALUE_RANGES,
    NUMERIC_PRECISION,
)

from .metar_parser import MetarParser

_LOGGER = logging.getLogger(__name__)

class MetarApiClientError(HomeAssistantError):
    """Exception for API client errors."""

class MetarApiClient:
    def __init__(self, hass: HomeAssistant, icao: str) -> None:
        """Initialize the API client."""
        self.hass = hass
        self.icao = icao
        self.metar = None
        # Use existing Home Assistant session
        self.session = async_get_clientsession(hass)
        self._retry_count = 0

    def _convert_units(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert units based on system preferences."""
        try:
            for key, value in data.items():
                if key in VALUE_RANGES and value is not None:
                    min_val, max_val = VALUE_RANGES[key]
                    if not min_val <= float(value) <= max_val:
                        _LOGGER.warning(
                            "Value %s for %s is outside valid range (%s-%s)",
                            value,
                            key,
                            min_val,
                            max_val
                        )
                        data[key] = None
                    elif key in NUMERIC_PRECISION:
                        data[key] = round(float(value), NUMERIC_PRECISION[key])
            return data
        except Exception as err:
            _LOGGER.error("Error converting units: %s", err)
            return data

    async def async_initialize(self) -> None:
        """Initialize the METAR client asynchronously."""
        def _setup_metar():
            try:
                metar = avwx.Metar(self.icao)
                # Use Home Assistant session
                if hasattr(metar, '_http'):
                    metar._http.session = self.session
                return metar
            except Exception as err:
                _LOGGER.error("Error creating Metar instance for %s: %s", self.icao, err)
                raise MetarApiClientError(f"Failed to create Metar instance: {err}")

        self.metar = await self.hass.async_add_executor_job(_setup_metar)
        _LOGGER.info("METAR client initialized for station %s", self.icao)

    async def fetch_data(self) -> Optional[Dict[str, Any]]:
        """Fetch METAR data using AVWX."""
        if self.metar is None:
            await self.async_initialize()

        try:
            await self.hass.async_add_executor_job(self.metar.update)
            _LOGGER.debug("Raw METAR data received for %s: %s", self.icao, self.metar.raw)

            if not self.metar.data:
                _LOGGER.error("No data received for station %s", self.icao)
                raise MetarApiClientError("No data received")

            parsed_data = await self._parse_metar_data()
            if parsed_data:
                self._retry_count = 0
                return parsed_data

            _LOGGER.error("Failed to parse METAR data for station %s", self.icao)
            raise MetarApiClientError("Failed to parse METAR data")

        except BadStation as err:
            _LOGGER.error("Invalid station code %s: %s", self.icao, err)
            return None
        except SourceError as err:
            _LOGGER.error("Source error for station %s: %s", self.icao, err)
            await self._handle_error()
            return None
        except Exception as err:
            _LOGGER.error("Error fetching METAR data for %s: %s", self.icao, err)
            await self._handle_error()
            return None

    async def _parse_metar_data(self) -> Dict[str, Any]:
        """Parse METAR data from AVWX response."""
        try:
            parser = MetarParser(self.metar.data)
            parsed_data = parser.get_parsed_data()

            # Add observation time
            time_data = getattr(self.metar.data, 'time', None)
            if isinstance(time_data, datetime):
                observation_time = time_data
            else:
                observation_time = datetime.now(timezone.utc)

            parsed_data["observation_time"] = observation_time.replace(tzinfo=timezone.utc).isoformat()

            # Convert units based on system preferences
            parsed_data = self._convert_units(parsed_data)

            _LOGGER.debug("Parsed and converted METAR data for %s: %s", self.icao, parsed_data)
            return parsed_data

        except Exception as err:
            _LOGGER.error("Error parsing METAR data for %s: %s", self.icao, err)
            raise MetarApiClientError(f"Failed to parse METAR data: {err}")

    async def _handle_error(self) -> None:
        """Handle error with exponential backoff."""
        if self._retry_count < len(RETRY_INTERVALS):
            wait_time = RETRY_INTERVALS[self._retry_count]
            self._retry_count += 1
            _LOGGER.warning(
                "Will retry fetching METAR data for %s in %d minutes (attempt %d/%d)",
                self.icao,
                wait_time,
                self._retry_count,
                len(RETRY_INTERVALS)
            )
            await asyncio.sleep(wait_time * 60)
        else:
            _LOGGER.error(
                "Maximum retry attempts reached for %s. Will try again in 1 hour",
                self.icao
            )
            await asyncio.sleep(3600)
            self._retry_count = 0
