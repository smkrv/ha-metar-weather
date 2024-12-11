"""
Config flow for HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
import logging
import re
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ICAO,
    CONF_TERMS_ACCEPTED,
    CONF_STATIONS,
    DOMAIN,
    ICAO_REGEX,
)

_LOGGER = logging.getLogger(__name__)

class HaMetarWeatherConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HA METAR Weather."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "HaMetarWeatherOptionsFlow":
        """Get the options flow for this handler."""
        return HaMetarWeatherOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            if not user_input.get(CONF_TERMS_ACCEPTED, False):
                errors["base"] = "terms_not_accepted"
            elif not re.match(ICAO_REGEX, user_input[CONF_ICAO]):
                errors[CONF_ICAO] = "invalid_icao"
            else:
                # Initialize with primary station
                user_input[CONF_STATIONS] = [user_input[CONF_ICAO]]
                return self.async_create_entry(
                    title=f"METAR {user_input[CONF_ICAO]}",
                    data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ICAO): str,
                vol.Required(CONF_TERMS_ACCEPTED): bool,
            }),
            errors=errors,
        )


class HaMetarWeatherOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for HA METAR Weather integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.stations = config_entry.data.get(CONF_STATIONS, [])
        self.new_stations = list(self.stations)

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage stations."""
        errors = {}

        if user_input is not None:
            return await self.async_step_station_add()

        stations_str = "\n".join(f"- {station}" for station in self.stations)

        return self.async_show_form(
            step_id="init",
            description_placeholders={
                "stations": stations_str or "No stations configured"
            },
            data_schema=vol.Schema({}),
        )

    async def async_step_station_add(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle adding a station."""
        errors = {}

        if user_input is not None:
            station = user_input[CONF_ICAO].upper()
            if not re.match(ICAO_REGEX, station):
                errors[CONF_ICAO] = "invalid_icao"
            elif station in self.new_stations:
                errors[CONF_ICAO] = "station_exists"
            else:
                self.new_stations.append(station)
                return await self.async_step_station_configure()

        return self.async_show_form(
            step_id="station_add",
            data_schema=vol.Schema({
                vol.Required(CONF_ICAO): str,
            }),
            errors=errors,
        )

    async def async_step_station_configure(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle station configuration."""
        if user_input is not None:
            if user_input.get("add_another", False):
                return await self.async_step_station_add()

            # Update config entry with new stations
            new_data = {
                **self.config_entry.data,
                CONF_STATIONS: self.new_stations,
            }

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
            )

            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="station_configure",
            data_schema=vol.Schema({
                vol.Optional("add_another", default=False): bool,
            }),
        )

    @callback
    def async_remove_station(self, station: str) -> None:
        """Remove a station from the list."""
        if station in self.new_stations and len(self.new_stations) > 1:
            self.new_stations.remove(station)
