"""
The HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import asyncio
import re
import sys

from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
)
from homeassistant.const import Platform
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.exceptions import ServiceValidationError

from .api_client import MetarApiClient
from .storage import MetarHistoryStorage
from .const import (
    DOMAIN,
    CONF_STATIONS,
    CONF_TEMP_UNIT,
    CONF_WIND_SPEED_UNIT,
    CONF_VISIBILITY_UNIT,
    CONF_PRESSURE_UNIT,
    CONF_ALTITUDE_UNIT,
    UNIT_AUTO,
    DEFAULT_WIND_SPEED_UNIT,
    DEFAULT_ALTITUDE_UNIT,
    DEFAULT_SCAN_INTERVAL,
    RETRY_INTERVALS,
    ICAO_REGEX,
)

# Compatibility for Python < 3.11
if sys.version_info >= (3, 11):
    from asyncio import timeout as async_timeout
else:
    from async_timeout import timeout as async_timeout

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the HA METAR Weather component."""
    hass.data.setdefault(DOMAIN, {})

    try:
        async with async_timeout(30):
            storage = MetarHistoryStorage(hass)
            await storage.async_load()
            hass.data[DOMAIN]["storage"] = storage
            _LOGGER.debug("Storage initialized successfully.")
    except asyncio.CancelledError:
        raise  # Don't suppress task cancellation
    except Exception as err:
        _LOGGER.error("Failed to initialize storage: %s", err)
        return False

    # Register services once during component setup (not per entry)
    async def async_update_station(call: ServiceCall) -> None:
        """Handle forced update service call."""
        station = call.data["station"].upper()

        # Validate ICAO format
        if not re.match(ICAO_REGEX, station):
            raise ServiceValidationError(
                f"Invalid ICAO code format: {station}",
                translation_domain=DOMAIN,
                translation_key="invalid_icao_format",
            )

        # Search for the station across all config entries
        # Use list() to prevent RuntimeError if dict changes during iteration
        for entry_id, entry_data in list(hass.data[DOMAIN].items()):
            if entry_id == "storage":
                continue
            if isinstance(entry_data, dict):
                coordinator = entry_data.get(station)
                if coordinator:
                    await coordinator.async_request_refresh()
                    _LOGGER.info("Forced update for station %s completed", station)
                    return

        raise ServiceValidationError(
            f"Station {station} not found in any config entry",
            translation_domain=DOMAIN,
            translation_key="station_not_found",
        )

    async def async_clear_history(call: ServiceCall) -> None:
        """Handle clear history service call."""
        station = call.data["station"].upper()

        # Validate ICAO format
        if not re.match(ICAO_REGEX, station):
            raise ServiceValidationError(
                f"Invalid ICAO code format: {station}",
                translation_domain=DOMAIN,
                translation_key="invalid_icao_format",
            )

        storage: MetarHistoryStorage = hass.data[DOMAIN].get("storage")

        if not storage:
            raise ServiceValidationError(
                "Storage not initialized",
                translation_domain=DOMAIN,
                translation_key="storage_not_initialized",
            )

        # Check if station exists in any config entry
        # Use list() to prevent RuntimeError if dict changes during iteration
        station_found = False
        for entry_id, entry_data in list(hass.data[DOMAIN].items()):
            if entry_id == "storage":
                continue
            if isinstance(entry_data, dict) and station in entry_data:
                station_found = True
                break

        if station_found:
            try:
                async with async_timeout(10):
                    await storage.async_clear_station(station)
                    _LOGGER.info("Cleared history for station %s", station)
            except asyncio.CancelledError:
                raise  # Don't suppress task cancellation
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout clearing history for %s", station)
            except Exception as err:
                _LOGGER.error("Error clearing history for %s: %s", station, err)
        else:
            raise ServiceValidationError(
                f"Station {station} is not configured",
                translation_domain=DOMAIN,
                translation_key="station_not_configured",
            )

    # Only register services if not already registered
    if not hass.services.has_service(DOMAIN, "update_station"):
        hass.services.async_register(
            DOMAIN,
            "update_station",
            async_update_station,
            schema=vol.Schema({
                vol.Required("station"): str,
            })
        )

    if not hass.services.has_service(DOMAIN, "clear_history"):
        hass.services.async_register(
            DOMAIN,
            "clear_history",
            async_clear_history,
            schema=vol.Schema({
                vol.Required("station"): str,
            })
        )

    return True


class MetarDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching METAR data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MetarApiClient,
        station: str,
        update_interval: timedelta,
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{station}",
            update_interval=update_interval,
        )
        self.client = client
        self.station = station
        self._retry_count = 0
        self._consecutive_failures = 0

    async def _async_update_data(self):
        """Fetch data from API with retry logic."""
        last_error = None

        # Try fetching with exponential backoff
        for attempt, delay in enumerate(RETRY_INTERVALS):
            try:
                data = await self.client.fetch_data()
                if data:
                    # Reset failure counter on success
                    self._consecutive_failures = 0
                    self._retry_count = 0

                    # Save to storage for historical data
                    storage = self.hass.data[DOMAIN].get("storage")
                    if storage:
                        try:
                            await storage.async_add_record(self.station, data)
                        except Exception as storage_err:
                            _LOGGER.warning(
                                "Failed to save history for %s: %s",
                                self.station,
                                storage_err
                            )
                    else:
                        _LOGGER.warning(
                            "Storage not initialized, historical data for %s will not be saved",
                            self.station
                        )

                    _LOGGER.debug("Updated data for %s: %s", self.station, data)
                    return data

                # No data but no error - API works but station has no data
                # Retrying won't help, so break early
                last_error = Exception(f"No data received for station {self.station}")
                break

            except Exception as err:
                last_error = err
                self._retry_count = attempt + 1
                _LOGGER.warning(
                    "Attempt %d/%d failed for %s: %s. Retrying in %ds...",
                    attempt + 1,
                    len(RETRY_INTERVALS),
                    self.station,
                    err,
                    delay
                )

                # Wait before retry (except on last attempt)
                if attempt < len(RETRY_INTERVALS) - 1:
                    await asyncio.sleep(delay)

        # All retries exhausted
        self._consecutive_failures += 1
        _LOGGER.error(
            "All %d retry attempts failed for %s. Consecutive failures: %d",
            len(RETRY_INTERVALS),
            self.station,
            self._consecutive_failures
        )
        raise UpdateFailed(f"Error fetching data after {len(RETRY_INTERVALS)} attempts: {last_error}") from last_error


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA METAR Weather from a config entry."""
    # Ensure storage is initialized (handles reload case where async_setup isn't called again)
    if "storage" not in hass.data.get(DOMAIN, {}):
        _LOGGER.debug("Storage not found, initializing (possible reload scenario)")
        hass.data.setdefault(DOMAIN, {})
        try:
            async with async_timeout(30):
                storage = MetarHistoryStorage(hass)
                await storage.async_load()
                hass.data[DOMAIN]["storage"] = storage
                _LOGGER.debug("Storage initialized in async_setup_entry")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.error("Failed to initialize storage in setup_entry: %s", err)
            # Continue without storage - sensors will work but no history

    # Validate stations list exists and is not empty
    stations = entry.data.get(CONF_STATIONS, [])
    if not stations:
        _LOGGER.error("No stations configured for entry %s", entry.entry_id)
        return False

    coordinators: dict[str, MetarDataUpdateCoordinator] = {}

    for station in stations:
        station_upper = station.upper()
        try:
            client = MetarApiClient(hass, station_upper)

            coordinator = MetarDataUpdateCoordinator(
                hass,
                client,
                station_upper,
                DEFAULT_SCAN_INTERVAL,
            )

            # This will fetch data once during setup
            await coordinator.async_config_entry_first_refresh()

            if not coordinator.data:
                _LOGGER.error("No initial data received for station %s", station_upper)
                continue

            coordinators[station_upper] = coordinator
            _LOGGER.debug(
                "Coordinator setup complete for %s with data: %s",
                station_upper,
                coordinator.data,
            )

        except Exception as err:
            _LOGGER.error("Error setting up station %s: %s", station_upper, err)
            continue

    if not coordinators:
        return False

    hass.data[DOMAIN][entry.entry_id] = coordinators

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Uses Home Assistant's built-in reload mechanism for proper state management.
    """
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Check if this was the last config entry (only "storage" key remains)
        remaining_entries = [
            key for key in hass.data[DOMAIN].keys()
            if key != "storage"
        ]

        if not remaining_entries:
            # Last entry unloaded - cleanup storage and unregister services
            _LOGGER.debug("Last config entry unloaded, cleaning up services and storage")

            # Unregister services
            if hass.services.has_service(DOMAIN, "update_station"):
                hass.services.async_remove(DOMAIN, "update_station")
            if hass.services.has_service(DOMAIN, "clear_history"):
                hass.services.async_remove(DOMAIN, "clear_history")

            # Cleanup storage (cancel pending debouncer) before removing
            storage = hass.data[DOMAIN].get("storage")
            if storage:
                await storage.async_cleanup()

            # Remove storage reference (storage object will be garbage collected)
            hass.data[DOMAIN].pop("storage", None)

            # Clear domain data entirely if empty
            if not hass.data[DOMAIN]:
                hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        new_data = {**config_entry.data}

        # Add default unit settings for v1 -> v2 migration
        new_data.setdefault(CONF_TEMP_UNIT, UNIT_AUTO)
        new_data.setdefault(CONF_WIND_SPEED_UNIT, DEFAULT_WIND_SPEED_UNIT)
        new_data.setdefault(CONF_VISIBILITY_UNIT, UNIT_AUTO)
        new_data.setdefault(CONF_PRESSURE_UNIT, UNIT_AUTO)
        new_data.setdefault(CONF_ALTITUDE_UNIT, DEFAULT_ALTITUDE_UNIT)

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=2
        )
        _LOGGER.info("Migration to version 2 successful")

    return True
