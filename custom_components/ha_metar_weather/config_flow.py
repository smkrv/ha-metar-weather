"""
Config flow for HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .api_client import MetarApiClient, MetarApiClientError
from .const import (
    DOMAIN,
    CONF_ICAO,
    CONF_TERMS_ACCEPTED,
    CONF_STATIONS,
    ICAO_REGEX,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidStation(HomeAssistantError):
    """Error to indicate invalid station code."""


class HaMetarWeatherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HA METAR Weather."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HaMetarWeatherOptionsFlow:
        """
        Get the options flow for this handler.

        Args:
            config_entry: Current config entry

        Returns:
            HaMetarWeatherOptionsFlow: Options flow handler
        """
        return HaMetarWeatherOptionsFlow(config_entry)

    async def _validate_station(self, icao: str) -> bool:
        """Validate METAR station connection."""
        try:
            client = MetarApiClient(hass=self.hass, icao=icao)
            await client.async_initialize()
            result = await client.fetch_data()
            if not result:
                raise CannotConnect
            return True
        except MetarApiClientError as err:
            if "invalid station" in str(err).lower():
                raise InvalidStation from err
            raise CannotConnect from err

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """
        Handle the initial step.

        Args:
            user_input: User provided configuration

        Returns:
            FlowResult: Configuration result
        """
        errors: Dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_TERMS_ACCEPTED, False):
                errors["base"] = "terms_not_accepted"
            elif not re.match(ICAO_REGEX, user_input[CONF_ICAO].upper()):
                errors[CONF_ICAO] = "invalid_icao"
            else:
                user_input[CONF_ICAO] = user_input[CONF_ICAO].upper()

                try:
                    await self._validate_station(user_input[CONF_ICAO])

                    # Initialize with station
                    user_input[CONF_STATIONS] = [user_input[CONF_ICAO]]

                    await self.async_set_unique_id(user_input[CONF_ICAO])
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"METAR {user_input[CONF_ICAO]}",
                        data=user_input,
                    )

                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except InvalidStation:
                    errors[CONF_ICAO] = "invalid_icao"
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception: %s", err)
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ICAO): str,
                vol.Required(CONF_TERMS_ACCEPTED, default=False): bool,
            }),
            errors=errors,
        )


class HaMetarWeatherOptionsFlow(OptionsFlow):
    """Handle options flow for HA METAR Weather integration."""

    def __init__(self, entry: ConfigEntry) -> None:
        """
        Initialize options flow.

        Args:
            entry: Current config entry
        """
        self._entry = entry
        self._stations = list(entry.data.get(CONF_STATIONS, []))
        self._new_stations = list(self._stations)

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """
        Manage the options.

        Args:
            user_input: User provided options

        Returns:
            FlowResult: Options flow result
        """
        if user_input is not None:
            return await self.async_step_station_add()

        stations_str = "\n".join(f"- {station}" for station in self._stations) or "No stations configured"

        return self.async_show_form(
            step_id="init",
            description_placeholders={
                "stations": stations_str
            },
        )

    async def async_step_station_add(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """
        Handle adding a new station.

        Args:
            user_input: User provided station data

        Returns:
            FlowResult: Flow result for station addition
        """
        errors: Dict[str, str] = {}

        if user_input is not None:
            station = user_input[CONF_ICAO].upper()
            if not re.match(ICAO_REGEX, station):
                errors[CONF_ICAO] = "invalid_icao"
            elif station in self._new_stations:
                errors[CONF_ICAO] = "station_exists"
            else:
                try:
                    client = MetarApiClient(hass=self.hass, icao=station)
                    result = await client.fetch_data()
                    if not result:
                        raise CannotConnect

                    self._new_stations.append(station)
                    return await self.async_step_station_configure()

                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception: %s", err)
                    errors["base"] = "unknown"

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
        """
        Configure station settings.

        Args:
            user_input: User provided configuration

        Returns:
            FlowResult: Flow result for station configuration
        """
        if user_input is not None:
            if user_input.get("add_another", False):
                return await self.async_step_station_add()

            new_data = dict(self._entry.data)
            new_data[CONF_STATIONS] = self._new_stations

            self.hass.config_entries.async_update_entry(
                self._entry, data=new_data
            )

            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="station_configure",
            data_schema=vol.Schema({
                vol.Optional("add_another", default=False): bool,
            }),
        )
