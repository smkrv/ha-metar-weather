"""
METAR data API client with multi-source support.

Primary source: Aviation Weather Center (AWC) REST API
Fallback source: AVWX library (NOAA FTP)

Both sources use NOAA data, ensuring consistency and reliability.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import asyncio
import logging
from asyncio import timeout as async_timeout
from copy import deepcopy
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
    VALUE_RANGES,
    NUMERIC_PRECISION,
    AVWX_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class DataSource(Enum):
    """Enumeration of available data sources."""
    AWC = "awc"  # Aviation Weather Center REST API
    AVWX = "avwx"  # AVWX library (NOAA FTP)


class MetarApiClientError(HomeAssistantError):
    """Exception for API client errors."""


class InvalidStationError(MetarApiClientError):
    """Exception for invalid station code."""


class ConnectionFailedError(MetarApiClientError):
    """Exception for connection failures."""


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
        self._last_source: Optional[DataSource] = None

        # Initialize clients
        self._awc_client = AWCApiClient(hass)
        self._avwx_metar: Optional[avwx.Metar] = None
        self._avwx_init_lock = asyncio.Lock()

    @property
    def last_source(self) -> Optional[str]:
        """Return the last used data source name."""
        return self._last_source.value if self._last_source else None

    async def _init_avwx(self) -> None:
        """Initialize AVWX client (fallback source)."""
        # Use lock to prevent race condition on parallel calls
        async with self._avwx_init_lock:
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
                self._last_source = DataSource.AWC
                _LOGGER.debug("Successfully fetched data from AWC API for %s", self.icao)
                return data
        except AWCApiError as err:
            _LOGGER.warning(
                "AWC API failed for %s: %s, falling back to AVWX",
                self.icao,
                err
            )
        except asyncio.CancelledError:
            raise  # Don't suppress cancellation
        except Exception as err:
            _LOGGER.warning(
                "Unexpected AWC error for %s: %s, falling back to AVWX",
                self.icao,
                err
            )

        # Fallback to AVWX (NOAA FTP)
        try:
            data = await self._fetch_from_avwx()
            if data:
                self._last_source = DataSource.AVWX
                _LOGGER.debug("Successfully fetched data from AVWX for %s", self.icao)
                return data
        except (MetarApiClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("AVWX failed for %s: %s", self.icao, err)
        except asyncio.CancelledError:
            raise  # Don't suppress cancellation
        except Exception as err:
            _LOGGER.error("Unexpected AVWX error for %s: %s", self.icao, err)

        # Both sources failed - let coordinator handle retry via its update interval
        _LOGGER.error("All data sources failed for %s", self.icao)
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
            # Add timeout to prevent hanging on slow NOAA FTP
            async with async_timeout(AVWX_TIMEOUT):
                await self.hass.async_add_executor_job(self._avwx_metar.update)
            _LOGGER.debug(
                "Raw METAR from AVWX for %s: %s",
                self.icao,
                self._avwx_metar.raw
            )

            if not self._avwx_metar.data:
                raise MetarApiClientError("No data received from AVWX")

            # Also verify raw METAR exists (needed for proper parsing)
            if not self._avwx_metar.raw:
                raise MetarApiClientError("No raw METAR string from AVWX")

            # Parse using our MetarParser
            parser = MetarParser(self._avwx_metar.data)
            parsed_data = parser.get_parsed_data()

            # Add observation time
            # AVWX returns Timestamp object with .dt attribute, not datetime directly
            time_data = getattr(self._avwx_metar.data, 'time', None)
            if time_data is not None and hasattr(time_data, 'dt') and time_data.dt:
                observation_time = time_data.dt
            elif isinstance(time_data, datetime):
                observation_time = time_data
            else:
                observation_time = datetime.now(timezone.utc)

            # Ensure proper timezone conversion (not just replacement)
            if observation_time.tzinfo is None:
                # Naive datetime - assume UTC
                observation_time = observation_time.replace(tzinfo=timezone.utc)
            else:
                # Aware datetime - convert to UTC
                observation_time = observation_time.astimezone(timezone.utc)

            parsed_data["observation_time"] = observation_time.isoformat()

            return self._validate_and_round(parsed_data)

        except BadStation as err:
            _LOGGER.error("Invalid station code %s: %s", self.icao, err)
            raise InvalidStationError(f"Invalid station: {err}") from err

        except SourceError as err:
            _LOGGER.error("AVWX source error for %s: %s", self.icao, err)
            raise MetarApiClientError(f"Source error: {err}") from err

        except asyncio.TimeoutError as err:
            _LOGGER.error("AVWX update timed out for %s (%ds)", self.icao, AVWX_TIMEOUT)
            raise MetarApiClientError("AVWX timeout") from err

    def _validate_and_round(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate ranges and round numeric values.

        Args:
            data: Parsed METAR data

        Returns:
            Validated and rounded data (new dict, input not mutated)
        """
        try:
            # Create a deep copy to avoid mutating input (including nested objects)
            result = deepcopy(data)
            for key, value in result.items():
                if key in VALUE_RANGES and value is not None:
                    min_val, max_val = VALUE_RANGES[key]
                    try:
                        float_val = float(value)
                        if not min_val <= float_val <= max_val:
                            _LOGGER.warning(
                                "Value %s for %s outside range (%s-%s)",
                                value, key, min_val, max_val
                            )
                            result[key] = None
                        elif key in NUMERIC_PRECISION:
                            result[key] = round(float_val, NUMERIC_PRECISION[key])
                    except (ValueError, TypeError):
                        pass
            return result
        except Exception as err:
            _LOGGER.error("Error validating data: %s", err)
            return deepcopy(data)



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
