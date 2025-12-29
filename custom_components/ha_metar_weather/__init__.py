"""
The HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import asyncio
import sys

from datetime import timedelta
from typing import Dict

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
    except Exception as err:
        _LOGGER.error("Failed to initialize storage: %s", err)
        return False

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

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            data = await self.client.fetch_data()
            if not data:
                raise UpdateFailed(f"No data received for station {self.station}")

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

            _LOGGER.debug("Updated data for %s: %s", self.station, data)
            return data
        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error updating data for %s: %s", self.station, err)
            raise UpdateFailed(f"Error fetching data: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA METAR Weather from a config entry."""
    coordinators: Dict[str, MetarDataUpdateCoordinator] = {}

    for station in entry.data[CONF_STATIONS]:
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

    # Register services
    async def async_update_station(call: ServiceCall) -> None:
        """Handle forced update service call."""
        station = call.data["station"].upper()
        if station in coordinators:
            await coordinators[station].async_request_refresh()
            _LOGGER.debug("Forced update for station %s completed", station)
        else:
            _LOGGER.error("Station %s not found", station)

    async def async_clear_history(call: ServiceCall) -> None:
        """Handle clear history service call."""
        station = call.data["station"].upper()
        storage: MetarHistoryStorage = hass.data[DOMAIN]["storage"]

        # Check if station is configured (case-insensitive)
        stations_upper = [s.upper() for s in entry.data[CONF_STATIONS]]
        if station in stations_upper:
            try:
                async with async_timeout(10):
                    await storage.async_clear_station(station)
                    _LOGGER.info("Cleared history for station %s", station)
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout clearing history for %s", station)
            except Exception as err:
                _LOGGER.error("Error clearing history for %s: %s", station, err)
        else:
            _LOGGER.error("Station %s is not configured", station)

    hass.services.async_register(
        DOMAIN,
        "update_station",
        async_update_station,
        schema=vol.Schema({
            vol.Required("station"): str,
        })
    )

    hass.services.async_register(
        DOMAIN,
        "clear_history",
        async_clear_history,
        schema=vol.Schema({
            vol.Required("station"): str,
        })
    )

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await async_reload_entry(hass, entry)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    try:
        await async_unload_entry(hass, entry)
        await async_setup_entry(hass, entry)
        _LOGGER.debug("Reloaded entry for %s", entry.entry_id)
    except Exception as err:
        _LOGGER.error("Error reloading entry: %s", err)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove services if this is the last entry
        remaining_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining_entries:
            hass.services.async_remove(DOMAIN, "update_station")
            hass.services.async_remove(DOMAIN, "clear_history")

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
