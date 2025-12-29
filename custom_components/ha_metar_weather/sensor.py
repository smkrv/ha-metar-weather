"""
Sensor platform for HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Callable, Union
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    CONF_STATIONS,
    CONF_TEMP_UNIT,
    CONF_WIND_SPEED_UNIT,
    CONF_VISIBILITY_UNIT,
    CONF_PRESSURE_UNIT,
    CONF_ALTITUDE_UNIT,
    ATTR_LAST_UPDATE,
    ATTR_STATION_NAME,
    ATTR_RAW_METAR,
    ATTR_HISTORICAL_DATA,
    ATTR_TREND,
    VALUE_RANGES,
    NUMERIC_PRECISION,
    DEGREE,
    PERCENTAGE,
    VERSION,
    FIXED_UNITS,
    UNIT_AUTO,
    DEFAULT_TEMP_UNIT,
    DEFAULT_WIND_SPEED_UNIT,
    DEFAULT_VISIBILITY_UNIT,
    DEFAULT_PRESSURE_UNIT,
    DEFAULT_ALTITUDE_UNIT,
    TrendState,
    MAX_HISTORY_DISPLAY,
)

_LOGGER = logging.getLogger(__name__)


def _format_runway_state(state: Optional[dict]) -> Optional[str]:
    """Format runway state dictionary into a human-readable string."""
    if not state or not isinstance(state, dict):
        return None

    parts = []

    # Surface type (key is "surface" in RunwayState dataclass)
    surface = state.get("surface")
    if surface:
        parts.append(surface)

    # Coverage
    coverage = state.get("coverage")
    if coverage:
        parts.append(f"coverage: {coverage}")

    # Depth (can be 0 for dry runway, so use "is not None")
    depth = state.get("depth")
    if depth is not None:
        parts.append(f"depth: {depth}")

    # Friction
    friction = state.get("friction")
    if friction is not None:
        parts.append(f"friction: {friction}")

    return ", ".join(parts) if parts else "Clear"


@dataclass
class MetarSensorEntityDescription(SensorEntityDescription):
    """Class describing METAR sensor entities."""
    value_fn: Callable[[dict], Optional[Union[str, float, int]]] = lambda d: None
    has_history: bool = True
    trend_threshold: float = 0.1

SENSOR_TYPES: tuple[MetarSensorEntityDescription, ...] = (
    MetarSensorEntityDescription(
        key="temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("temperature"),
        icon="mdi:thermometer",
        trend_threshold=0.5,
    ),
    MetarSensorEntityDescription(
        key="dew_point",
        name="Dew Point",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("dew_point"),
        icon="mdi:water-percent",
        trend_threshold=0.5,
    ),
    MetarSensorEntityDescription(
        key="wind_speed",
        name="Wind Speed",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("wind_speed"),
        icon="mdi:weather-windy",
        trend_threshold=1.0,
    ),
    MetarSensorEntityDescription(
        key="wind_gust",
        name="Wind Gust",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("wind_gust"),
        icon="mdi:weather-windy-variant",
        trend_threshold=2.0,  # 2 km/h threshold for gusts (more sensitive than wind_speed)
    ),
    MetarSensorEntityDescription(
        key="wind_variable_direction",
        name="Wind Variable Direction",
        value_fn=lambda data: data.get("wind_variable_direction"),
        icon="mdi:compass-outline",
    ),
    MetarSensorEntityDescription(
        key="wind_direction",
        name="Wind Direction",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        # For VRB wind, return None (sensor will be unavailable)
        # The separate wind_variable_direction sensor shows "VRB" status
        value_fn=lambda data: data.get("wind_direction"),
        icon="mdi:compass",
        trend_threshold=45,
    ),
    MetarSensorEntityDescription(
        key="visibility",
        name="Visibility",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("visibility"),
        icon="mdi:eye",
        trend_threshold=1.0,
    ),
    MetarSensorEntityDescription(
        key="pressure",
        name="Pressure",
        native_unit_of_measurement=UnitOfPressure.HPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("pressure"),
        icon="mdi:gauge",
        trend_threshold=1.0,
    ),
    MetarSensorEntityDescription(
        key="humidity",
        name="Relative Humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("humidity"),
        icon="mdi:water-percent",
        trend_threshold=5,  # 5% absolute change threshold
    ),
    MetarSensorEntityDescription(
        key="weather",
        name="Weather Condition",
        value_fn=lambda data: data.get("weather", "Clear"),
        icon="mdi:weather-partly-cloudy",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="cloud_layers",
        name="Cloud Layers",
        value_fn=lambda data: ", ".join(
            f"{layer.get('coverage', '')} {layer.get('height', 'N/A')}ft"
            for layer in (data.get("cloud_layers") or [])
            if isinstance(layer, dict) and layer.get('coverage')
        ) or "Clear",
        icon="mdi:cloud",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="cloud_coverage_state",
        name="Cloud Coverage State",
        value_fn=lambda data: data.get("cloud_coverage_state", "Clear"),
        icon="mdi:cloud",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="cloud_coverage_height",
        name="Cloud Coverage Height",
        native_unit_of_measurement=UnitOfLength.FEET,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("cloud_coverage_height"),
        icon="mdi:cloud-outline",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="cloud_coverage_type",
        name="Cloud Coverage Type",
        value_fn=lambda data: data.get("cloud_coverage_type", "N/A"),
        icon="mdi:cloud",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="raw_metar",
        name="Raw METAR",
        value_fn=lambda data: data.get("raw_metar"),
        icon="mdi:text",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="auto_indicator",
        name="Auto Indicator",
        value_fn=lambda data: "Auto Report" if data.get("auto") else "Manual Report",
        icon="mdi:robot",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="cavok",
        name="CAVOK",
        value_fn=lambda data: str(data.get("cavok", False)),
        icon="mdi:weather-sunny",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="runway_states",
        name="All Runways State",
        value_fn=lambda data: "\n".join(
            f"Runway {rwy}: {details.get('surface', 'N/A')}, "
            f"Coverage: {details.get('coverage', 'N/A')}, "
            f"Depth: {details.get('depth', 'N/A')}, "
            f"Friction: {details.get('friction', 'N/A')}"
            for rwy, details in data.get("runway_states", {}).items()
        ) or "No Runway Data",
        icon="mdi:runway",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="trend",
        name="Trend",
        value_fn=lambda data: data.get("trend", "No trend information"),
        icon="mdi:trending-up",
        has_history=False,
    ),
)


class MetarSensor(CoordinatorEntity, SensorEntity):
    """Implementation of a METAR sensor."""
    entity_description: MetarSensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        station: str,
        description: MetarSensorEntityDescription,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._station = station
        self._config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{station}_{description.key}"
        self._attr_name = f"METAR {station} {description.name}"
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement

        # Add device_info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station)},
            "name": f"METAR {station}",
            "manufacturer": "NOAA / AWC",
            "model": "METAR Weather Station",
            "sw_version": VERSION,
            "entry_type": DeviceEntryType.SERVICE,
        }

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._update_units()

    def _get_configured_unit(self, unit_key: str, default: str) -> str:
        """Get configured unit from config entry or return default.

        Args:
            unit_key: Configuration key for the unit
            default: Default unit value

        Returns:
            The configured unit or resolved auto unit
        """
        configured = self._config_entry.data.get(unit_key, UNIT_AUTO)

        if configured == UNIT_AUTO:
            # Use Home Assistant system settings
            is_metric = self.hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS

            if unit_key == CONF_TEMP_UNIT:
                return UnitOfTemperature.CELSIUS if is_metric else UnitOfTemperature.FAHRENHEIT
            elif unit_key == CONF_WIND_SPEED_UNIT:
                return UnitOfSpeed.KILOMETERS_PER_HOUR if is_metric else UnitOfSpeed.MILES_PER_HOUR
            elif unit_key == CONF_VISIBILITY_UNIT:
                return UnitOfLength.KILOMETERS if is_metric else UnitOfLength.MILES
            elif unit_key == CONF_PRESSURE_UNIT:
                return UnitOfPressure.HPA if is_metric else UnitOfPressure.INHG
            elif unit_key == CONF_ALTITUDE_UNIT:
                return UnitOfLength.METERS if is_metric else UnitOfLength.FEET

            return default

        return configured

    def _update_units(self) -> None:
        """Update suggested display units based on configuration preferences.

        Note: native_unit_of_measurement stays as defined in SENSOR_TYPES
        (the actual unit of stored data). suggested_unit_of_measurement
        tells Home Assistant what unit to convert to for display.
        """
        key = self.entity_description.key

        # Skip update for sensors with fixed units
        if key in FIXED_UNITS:
            return

        # Map sensor keys to unit configuration keys
        unit_key_mapping = {
            "temperature": CONF_TEMP_UNIT,
            "dew_point": CONF_TEMP_UNIT,
            "wind_speed": CONF_WIND_SPEED_UNIT,
            "wind_gust": CONF_WIND_SPEED_UNIT,
            "visibility": CONF_VISIBILITY_UNIT,
            "pressure": CONF_PRESSURE_UNIT,
            "cloud_coverage_height": CONF_ALTITUDE_UNIT,
        }

        default_mapping = {
            "temperature": DEFAULT_TEMP_UNIT,
            "dew_point": DEFAULT_TEMP_UNIT,
            "wind_speed": DEFAULT_WIND_SPEED_UNIT,
            "wind_gust": DEFAULT_WIND_SPEED_UNIT,
            "visibility": DEFAULT_VISIBILITY_UNIT,
            "pressure": DEFAULT_PRESSURE_UNIT,
            "cloud_coverage_height": DEFAULT_ALTITUDE_UNIT,
        }

        if key in unit_key_mapping:
            unit_key = unit_key_mapping[key]
            default = default_mapping[key]
            suggested_unit = self._get_configured_unit(unit_key, default)
            # Only set suggested unit if it differs from native unit
            # Home Assistant will handle the conversion automatically
            if suggested_unit != self.entity_description.native_unit_of_measurement:
                self._attr_suggested_unit_of_measurement = suggested_unit

    @property
    def native_value(self) -> Optional[Union[str, float, int]]:
        """Return the state of the sensor."""
        try:
            if not self.coordinator.data:
                return None

            value = self.entity_description.value_fn(self.coordinator.data)

            # Special handling for numeric values
            if isinstance(value, (float, int)):
                if self.entity_description.key in VALUE_RANGES:
                    min_val, max_val = VALUE_RANGES[self.entity_description.key]
                    if not min_val <= float(value) <= max_val:
                        _LOGGER.warning(
                            "Value %s for %s is outside valid range (%s-%s)",
                            value,
                            self.entity_description.key,
                            min_val,
                            max_val
                        )
                        return None

                if self.entity_description.key in NUMERIC_PRECISION:
                    return round(float(value), NUMERIC_PRECISION[self.entity_description.key])

            return value

        except Exception as err:
            _LOGGER.error(
                "Error getting value for %s_%s: %s",
                self._station,
                self.entity_description.key,
                err,
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {}

        if self.coordinator.data:
            attrs[ATTR_LAST_UPDATE] = self.coordinator.data.get("observation_time")
            attrs["station"] = self._station

            # Add data source info if available
            if hasattr(self.coordinator, 'client') and hasattr(self.coordinator.client, 'last_source'):
                attrs["data_source"] = self.coordinator.client.last_source

            station_name = self.coordinator.data.get("station_name")
            if station_name is not None:
                attrs[ATTR_STATION_NAME] = station_name

            if self.entity_description.key != "raw_metar":
                attrs[ATTR_RAW_METAR] = self.coordinator.data.get("raw_metar")

            if self.entity_description.has_history and self.hass.data.get(DOMAIN, {}).get("storage"):
                storage = self.hass.data[DOMAIN]["storage"]
                history = storage.get_station_history(self._station, self.entity_description.key)
                if history:
                    attrs[ATTR_HISTORICAL_DATA] = history[-MAX_HISTORY_DISPLAY:]

                    if self.entity_description.state_class == SensorStateClass.MEASUREMENT:
                        try:
                            # history is a list of values, not dicts
                            values = []
                            for item in history[-MAX_HISTORY_DISPLAY:]:
                                if isinstance(item, (int, float)):
                                    values.append(float(item))
                                elif isinstance(item, str):
                                    # Try to parse string as number
                                    try:
                                        values.append(float(item))
                                    except ValueError:
                                        continue  # Skip non-numeric strings

                            if values:
                                attrs["min_24h"] = min(values)
                                attrs["max_24h"] = max(values)
                                attrs["average_24h"] = round(sum(values) / len(values), 2)
                                attrs[ATTR_TREND] = self._calculate_trend(values)

                        except (ValueError, TypeError) as err:
                            _LOGGER.debug(
                                "Error calculating statistics for %s: %s",
                                self.entity_description.key,
                                err
                            )

        return attrs

    def _calculate_trend(self, values: list[float]) -> str:
        """Calculate trend based on historical values.

        For wind direction, uses circular difference (359° → 1° = 2° change).
        For other values, uses absolute change.

        Returns:
            TrendState value as string
        """
        if len(values) < 2:
            return TrendState.STABLE

        try:
            last_value = float(values[-1])
            prev_value = float(values[-2])
            threshold = self.entity_description.trend_threshold

            # Special handling for wind direction (circular)
            if self.entity_description.key == "wind_direction":
                # Calculate circular difference
                diff = last_value - prev_value
                # Normalize to -180 to 180
                if diff > 180:
                    diff -= 360
                elif diff < -180:
                    diff += 360

                if abs(diff) < threshold:
                    return TrendState.STABLE
                # For wind direction: positive = clockwise (veering), negative = counter-clockwise (backing)
                return TrendState.VEERING if diff > 0 else TrendState.BACKING

            # Absolute change (for temp, pressure, humidity, visibility, wind_speed, etc.)
            change = last_value - prev_value
            if abs(change) < threshold:
                return TrendState.STABLE
            return TrendState.RISING if change > 0 else TrendState.FALLING

        except (ValueError, TypeError, ZeroDivisionError):
            return TrendState.STABLE


    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return False

        key = self.entity_description.key

        # wind_direction: available only if we have a numeric direction
        # For VRB wind, direction is None - sensor will be unavailable
        # The separate wind_variable_direction sensor shows "VRB" status
        if key == "wind_direction":
            return self.coordinator.data.get("wind_direction") is not None

        # wind_gust: only available if there's actually a gust value
        if key == "wind_gust":
            return self.coordinator.data.get("wind_gust") is not None

        # wind_variable_direction: only available if there's variable direction
        if key == "wind_variable_direction":
            return self.coordinator.data.get("wind_variable_direction") is not None

        return self.native_value is not None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the METAR sensors."""
    coordinators = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[MetarSensor] = []

    for station in config_entry.data[CONF_STATIONS]:
        # Normalize station to uppercase to match coordinator keys
        station_upper = station.upper()
        coordinator = coordinators.get(station_upper)

        if not coordinator:
            _LOGGER.warning("Coordinator not found for station %s", station)
            continue

        # Create sensors even without initial data - they will be "unavailable"
        # until data arrives, rather than never being created
        if coordinator.data is None:
            _LOGGER.info(
                "No initial data for station %s, sensors will be unavailable until data arrives",
                station_upper
            )

        _LOGGER.debug("Setting up sensors for station %s", station_upper)

        for description in SENSOR_TYPES:
            entities.append(MetarSensor(
                coordinator=coordinator,
                station=station_upper,
                description=description,
                config_entry=config_entry,
            ))

        # Setup individual runway sensors (only if we have data with runways)
        if coordinator.data:
            runway_states = coordinator.data.get("runway_states", {})
            if runway_states:
                for runway in runway_states:
                    _LOGGER.debug("Creating runway sensor for runway %s at station %s", runway, station_upper)
                    entities.append(
                        MetarSensor(
                            coordinator=coordinator,
                            station=station_upper,
                            description=MetarSensorEntityDescription(
                                key=f"runway_{runway}",
                                name=f"Runway {runway} State",
                                value_fn=lambda data, r=runway: _format_runway_state(
                                    data.get("runway_states", {}).get(r)
                                ),
                                icon="mdi:runway",
                                has_history=False,
                            ),
                            config_entry=config_entry,
                        )
                    )

    async_add_entities(entities)
