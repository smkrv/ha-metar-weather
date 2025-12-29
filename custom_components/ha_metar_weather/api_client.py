"""
METAR data API client with multi-source support.

Primary source: Aviation Weather Center (AWC) REST API
Fallback source: AVWX library (NOAA FTP)

Both sources use NOAA data, ensuring consistency and reliability.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum

import avwx
from avwx.exceptions import BadStation, SourceError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

from .awc_client import AWCApiClient, AWCApiError
from .metar_parser import MetarParser
from .const import (
    RETRY_INTERVALS,
    VALUE_RANGES,
    NUMERIC_PRECISION,
)

_LOGGER = logging.getLogger(__name__)


class DataSource(Enum):
    """Enumeration of available data sources."""
    AWC = "awc"  # Aviation Weather Center REST API
    AVWX = "avwx"  # AVWX library (NOAA FTP)


class MetarApiClientError(HomeAssistantError):
    """Exception for API client errors."""


class MetarApiClient:
    """METAR API client with multi-source support.

    Uses AWC REST API as primary source with AVWX as fallback.
    Both sources retrieve data from NOAA.
    """

    def __init__(self, hass: HomeAssistant, icao: str) -> None:
        """Initialize the API client.

        Args:
            hass: Home Assistant instance
            icao: ICAO airport code
        """
        self.hass = hass
        self.icao = icao.upper()
        self.session = async_get_clientsession(hass)
        self._retry_count = 0
        self._last_source: Optional[DataSource] = None

        # Initialize clients
        self._awc_client = AWCApiClient(hass)
        self._avwx_metar: Optional[avwx.Metar] = None

    @property
    def last_source(self) -> Optional[str]:
        """Return the last used data source name."""
        return self._last_source.value if self._last_source else None

    async def _init_avwx(self) -> None:
        """Initialize AVWX client (fallback source)."""
        if self._avwx_metar is not None:
            return

        def _setup():
            try:
                metar = avwx.Metar(self.icao)
                return metar
            except Exception as err:
                _LOGGER.error("Error creating AVWX instance for %s: %s", self.icao, err)
                raise MetarApiClientError(f"Failed to create AVWX instance: {err}")

        self._avwx_metar = await self.hass.async_add_executor_job(_setup)
        _LOGGER.debug("AVWX client initialized for station %s", self.icao)

    async def fetch_data(self) -> Optional[Dict[str, Any]]:
        """Fetch METAR data using multi-source strategy.

        Tries AWC API first, falls back to AVWX if needed.

        Returns:
            Parsed METAR data dictionary or None on error
        """
        # Try AWC API first (primary source)
        try:
            data = await self._fetch_from_awc()
            if data:
                self._retry_count = 0
                self._last_source = DataSource.AWC
                _LOGGER.debug("Successfully fetched data from AWC API for %s", self.icao)
                return data
        except AWCApiError as err:
            _LOGGER.warning(
                "AWC API failed for %s: %s, falling back to AVWX",
                self.icao,
                err
            )

        # Fallback to AVWX (NOAA FTP)
        try:
            data = await self._fetch_from_avwx()
            if data:
                self._retry_count = 0
                self._last_source = DataSource.AVWX
                _LOGGER.debug("Successfully fetched data from AVWX for %s", self.icao)
                return data
        except Exception as err:
            _LOGGER.error("AVWX also failed for %s: %s", self.icao, err)

        # Both sources failed
        await self._handle_error()
        return None

    async def _fetch_from_awc(self) -> Optional[Dict[str, Any]]:
        """Fetch and parse data from AWC API.

        Returns:
            Parsed METAR data or None
        """
        raw_data = await self._awc_client.fetch_single_metar(self.icao)
        if not raw_data:
            return None

        parsed = self._awc_client.parse_awc_response(raw_data)
        return self._validate_and_round(parsed)

    async def _fetch_from_avwx(self) -> Optional[Dict[str, Any]]:
        """Fetch and parse data from AVWX (NOAA FTP).

        Returns:
            Parsed METAR data or None
        """
        await self._init_avwx()

        try:
            await self.hass.async_add_executor_job(self._avwx_metar.update)
            _LOGGER.debug(
                "Raw METAR from AVWX for %s: %s",
                self.icao,
                self._avwx_metar.raw
            )

            if not self._avwx_metar.data:
                raise MetarApiClientError("No data received from AVWX")

            # Parse using our MetarParser
            parser = MetarParser(self._avwx_metar.data)
            parsed_data = parser.get_parsed_data()

            # Add observation time
            time_data = getattr(self._avwx_metar.data, 'time', None)
            if isinstance(time_data, datetime):
                observation_time = time_data
            else:
                observation_time = datetime.now(timezone.utc)

            parsed_data["observation_time"] = observation_time.replace(
                tzinfo=timezone.utc
            ).isoformat()

            return self._validate_and_round(parsed_data)

        except BadStation as err:
            _LOGGER.error("Invalid station code %s: %s", self.icao, err)
            raise MetarApiClientError(f"Invalid station: {err}") from err

        except SourceError as err:
            _LOGGER.error("AVWX source error for %s: %s", self.icao, err)
            raise MetarApiClientError(f"Source error: {err}") from err

    def _validate_and_round(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate ranges and round numeric values.

        Args:
            data: Parsed METAR data

        Returns:
            Validated and rounded data
        """
        try:
            for key, value in data.items():
                if key in VALUE_RANGES and value is not None:
                    min_val, max_val = VALUE_RANGES[key]
                    try:
                        float_val = float(value)
                        if not min_val <= float_val <= max_val:
                            _LOGGER.warning(
                                "Value %s for %s outside range (%s-%s)",
                                value, key, min_val, max_val
                            )
                            data[key] = None
                        elif key in NUMERIC_PRECISION:
                            data[key] = round(float_val, NUMERIC_PRECISION[key])
                    except (ValueError, TypeError):
                        pass
            return data
        except Exception as err:
            _LOGGER.error("Error validating data: %s", err)
            return data

    async def _handle_error(self) -> None:
        """Handle error with exponential backoff."""
        if self._retry_count < len(RETRY_INTERVALS):
            wait_time = RETRY_INTERVALS[self._retry_count]
            self._retry_count += 1
            _LOGGER.warning(
                "Will retry fetching METAR for %s in %d minutes (attempt %d/%d)",
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


async def validate_station(hass: HomeAssistant, icao: str) -> bool:
    """Validate station exists using available sources.

    Args:
        hass: Home Assistant instance
        icao: ICAO airport code

    Returns:
        True if station is valid
    """
    client = MetarApiClient(hass, icao)
    try:
        result = await client.fetch_data()
        return result is not None
    except MetarApiClientError:
        return False
