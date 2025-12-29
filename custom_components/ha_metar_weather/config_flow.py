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

from .api_client import MetarApiClient, MetarApiClientError, validate_station
from .const import (
    DOMAIN,
    CONF_ICAO,
    CONF_TERMS_ACCEPTED,
    CONF_STATIONS,
    ICAO_REGEX,
    CONF_TEMP_UNIT,
    CONF_WIND_SPEED_UNIT,
    CONF_VISIBILITY_UNIT,
    CONF_PRESSURE_UNIT,
    CONF_ALTITUDE_UNIT,
    AVAILABLE_TEMP_UNITS,
    AVAILABLE_WIND_SPEED_UNITS,
    AVAILABLE_VISIBILITY_UNITS,
    AVAILABLE_PRESSURE_UNITS,
    AVAILABLE_ALTITUDE_UNITS,
    DEFAULT_TEMP_UNIT,
    DEFAULT_WIND_SPEED_UNIT,
    DEFAULT_VISIBILITY_UNIT,
    DEFAULT_PRESSURE_UNIT,
    DEFAULT_ALTITUDE_UNIT,
    UNIT_AUTO,
    UNIT_FORMATS,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidStation(HomeAssistantError):
    """Error to indicate invalid station code."""


def _build_unit_options(units: list[str], include_auto: bool = True) -> dict:
    """Build unit selector options with display names."""
    options = {}
    if include_auto:
        options[UNIT_AUTO] = "Auto (Home Assistant)"
    for unit in units:
        display = UNIT_FORMATS.get(unit, unit)
        options[unit] = display
    return options


class HaMetarWeatherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HA METAR Weather."""

    VERSION = 2  # Bumped for unit config

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: Dict[str, Any] = {}

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
        """Validate METAR station connection.

        Uses multi-source validation (AWC API + AVWX fallback).
        """
        try:
            is_valid = await validate_station(self.hass, icao)
            if not is_valid:
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

                    # Store user input and proceed to units configuration
                    self._user_input = user_input
                    self._user_input[CONF_STATIONS] = [user_input[CONF_ICAO]]
                    return await self.async_step_units()

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

    async def async_step_units(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """
        Handle units configuration step.

        Args:
            user_input: User provided unit preferences

        Returns:
            FlowResult: Configuration result
        """
        if user_input is not None:
            # Merge unit settings with stored user input
            self._user_input.update(user_input)

            await self.async_set_unique_id(self._user_input[CONF_ICAO])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"METAR {self._user_input[CONF_ICAO]}",
                data=self._user_input,
            )

        # Build unit selection schema
        temp_options = _build_unit_options(AVAILABLE_TEMP_UNITS)
        wind_options = _build_unit_options(AVAILABLE_WIND_SPEED_UNITS)
        visibility_options = _build_unit_options(AVAILABLE_VISIBILITY_UNITS)
        pressure_options = _build_unit_options(AVAILABLE_PRESSURE_UNITS)
        altitude_options = _build_unit_options(AVAILABLE_ALTITUDE_UNITS)

        return self.async_show_form(
            step_id="units",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_TEMP_UNIT,
                    default=UNIT_AUTO
                ): vol.In(temp_options),
                vol.Required(
                    CONF_WIND_SPEED_UNIT,
                    default=DEFAULT_WIND_SPEED_UNIT
                ): vol.In(wind_options),
                vol.Required(
                    CONF_VISIBILITY_UNIT,
                    default=UNIT_AUTO
                ): vol.In(visibility_options),
                vol.Required(
                    CONF_PRESSURE_UNIT,
                    default=UNIT_AUTO
                ): vol.In(pressure_options),
                vol.Required(
                    CONF_ALTITUDE_UNIT,
                    default=DEFAULT_ALTITUDE_UNIT
                ): vol.In(altitude_options),
            }),
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
        Manage the options - main menu.

        Args:
            user_input: User provided options

        Returns:
            FlowResult: Options flow result
        """
        return self.async_show_menu(
            step_id="init",
            menu_options=["units", "stations"],
        )

    async def async_step_units(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """
        Configure unit preferences.

        Args:
            user_input: User provided unit preferences

        Returns:
            FlowResult: Options flow result
        """
        if user_input is not None:
            # Update the config entry with new unit settings
            new_data = dict(self._entry.data)
            new_data.update(user_input)

            self.hass.config_entries.async_update_entry(
                self._entry, data=new_data
            )

            return self.async_create_entry(title="", data={})

        # Get current unit settings
        current_temp = self._entry.data.get(CONF_TEMP_UNIT, UNIT_AUTO)
        current_wind = self._entry.data.get(CONF_WIND_SPEED_UNIT, DEFAULT_WIND_SPEED_UNIT)
        current_vis = self._entry.data.get(CONF_VISIBILITY_UNIT, UNIT_AUTO)
        current_press = self._entry.data.get(CONF_PRESSURE_UNIT, UNIT_AUTO)
        current_alt = self._entry.data.get(CONF_ALTITUDE_UNIT, DEFAULT_ALTITUDE_UNIT)

        # Build unit selection schema
        temp_options = _build_unit_options(AVAILABLE_TEMP_UNITS)
        wind_options = _build_unit_options(AVAILABLE_WIND_SPEED_UNITS)
        visibility_options = _build_unit_options(AVAILABLE_VISIBILITY_UNITS)
        pressure_options = _build_unit_options(AVAILABLE_PRESSURE_UNITS)
        altitude_options = _build_unit_options(AVAILABLE_ALTITUDE_UNITS)

        return self.async_show_form(
            step_id="units",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_TEMP_UNIT,
                    default=current_temp
                ): vol.In(temp_options),
                vol.Required(
                    CONF_WIND_SPEED_UNIT,
                    default=current_wind
                ): vol.In(wind_options),
                vol.Required(
                    CONF_VISIBILITY_UNIT,
                    default=current_vis
                ): vol.In(visibility_options),
                vol.Required(
                    CONF_PRESSURE_UNIT,
                    default=current_press
                ): vol.In(pressure_options),
                vol.Required(
                    CONF_ALTITUDE_UNIT,
                    default=current_alt
                ): vol.In(altitude_options),
            }),
        )

    async def async_step_stations(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """
        Manage stations - show current and offer to add.

        Args:
            user_input: User provided options

        Returns:
            FlowResult: Options flow result
        """
        if user_input is not None:
            return await self.async_step_station_add()

        stations_str = "\n".join(f"• {station}" for station in self._stations) or "No stations"

        return self.async_show_form(
            step_id="stations",
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
                    is_valid = await validate_station(self.hass, station)
                    if not is_valid:
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
