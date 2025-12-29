"""
The HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import async_timeout
import asyncio

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
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the HA METAR Weather component."""
    hass.data.setdefault(DOMAIN, {})

    try:
        async with async_timeout.timeout(30):
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
            _LOGGER.debug("Updated data for %s: %s", self.station, data)
            return data
        except Exception as err:
            _LOGGER.error("Error updating data for %s: %s", self.station, err)
            raise UpdateFailed(f"Error fetching data: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA METAR Weather from a config entry."""
    coordinators: Dict[str, MetarDataUpdateCoordinator] = {}

    for station in entry.data[CONF_STATIONS]:
        station = station.upper()
        try:
            client = MetarApiClient(hass, station)

            # Get initial data
            initial_data = await client.fetch_data()
            if not initial_data:
                _LOGGER.error("No initial data received for station %s", station)
                continue

            coordinator = MetarDataUpdateCoordinator(
                hass,
                client,
                station,
                DEFAULT_SCAN_INTERVAL,
            )

            coordinator.data = initial_data

            await coordinator.async_config_entry_first_refresh()

            coordinators[station] = coordinator
            _LOGGER.debug(
                "Coordinator setup complete for %s with data: %s",
                station,
                coordinator.data,
            )

        except Exception as err:
            _LOGGER.error("Error setting up station %s: %s", station, err)
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

        if station in entry.data[CONF_STATIONS]:
            try:
                async with async_timeout.timeout(10):
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
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
