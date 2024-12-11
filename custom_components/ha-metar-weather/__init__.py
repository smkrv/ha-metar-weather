"""
The HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
import random
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api_client import MetarApiClient
from .storage import MetarHistoryStorage
from .const import (
    DOMAIN,
    CONF_ICAO,
    CONF_STATIONS,
    DEFAULT_SCAN_INTERVAL,
    RANDOM_MINUTES_MIN,
    RANDOM_MINUTES_MAX,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the HA METAR Weather component."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize storage
    storage = MetarHistoryStorage(hass)
    await storage.async_load()
    hass.data[DOMAIN]["storage"] = storage

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA METAR Weather from a config entry."""
    coordinators = {}

    # Create coordinator for each station
    for station in entry.data[CONF_STATIONS]:
        client = MetarApiClient(hass, station)

        # Add random minutes to update interval for each station
        random_minutes = random.randint(RANDOM_MINUTES_MIN, RANDOM_MINUTES_MAX)
        update_interval = DEFAULT_SCAN_INTERVAL + timedelta(minutes=random_minutes)

        async def async_update_data(station=station, client=client):
            """Fetch data from API."""
            data = await client.fetch_data()
            if data:
                await hass.data[DOMAIN]["storage"].async_add_record(station, data)
            return data

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{station}",
            update_method=async_update_data,
            update_interval=update_interval,
        )

        # Fetch initial data
        await coordinator.async_config_entry_first_refresh()

        if not coordinator.last_update_success:
            raise ConfigEntryNotReady(
                f"Failed to fetch initial data for station {station}"
            )

        coordinators[station] = coordinator

    hass.data[DOMAIN][entry.entry_id] = coordinators

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def async_update_station(call: ServiceCall) -> None:
        """Handle forced update service call."""
        station = call.data["station"].upper()
        if station not in entry.data[CONF_STATIONS]:
            _LOGGER.error("Station %s is not configured", station)
            return

        coordinator = hass.data[DOMAIN][entry.entry_id][station]
        await coordinator.async_refresh()
        _LOGGER.debug("Forced update for station %s completed", station)

    async def async_clear_history(call: ServiceCall) -> None:
        """Handle clear history service call."""
        station = call.data["station"].upper()
        storage = hass.data[DOMAIN]["storage"]

        if station in entry.data[CONF_STATIONS]:
            storage._data[station] = []
            await storage.async_save()
            _LOGGER.info("Cleared history for station %s", station)
        else:
            _LOGGER.error("Station %s is not configured", station)

    # Register services with validation schemas
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

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinators = hass.data[DOMAIN].pop(entry.entry_id)

        # Cancel all update tasks
        for coordinator in coordinators.values():
            coordinator.async_shutdown()

    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await async_reload_entry(hass, entry)
