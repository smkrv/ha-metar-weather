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
    CONF_UNIT_SYSTEM_METRIC as HA_CONF_UNIT_SYSTEM_METRIC,
    CONF_UNIT_SYSTEM_IMPERIAL as HA_CONF_UNIT_SYSTEM_IMPERIAL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    CONF_STATIONS,
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
    UNIT_MAPPINGS,
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class MetarSensorEntityDescription(SensorEntityDescription):
    """Class describing METAR sensor entities."""
    value_fn: Callable[[dict], Optional[Union[str, float, int]]] = None
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
        trend_threshold=5,
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
        value_fn=lambda data: ", ".join(str(layer) for layer in data.get("cloud_layers", [])) or "Clear",
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
            f"Runway {rwy}: {details['surface']}, "
            f"Coverage: {details['coverage']}, "
            f"Depth: {details['depth']}, "
            f"Friction: {details['friction']}"
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
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._station = station
        self._attr_unique_id = f"{DOMAIN}_{station}_{description.key}"
        self._attr_name = f"METAR {station} {description.name}"
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement

        # Add device_info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station)},
            "name": f"METAR {station}",
            "manufacturer": "AVWX / Community",
            "model": "METAR Weather Station",
            "sw_version": VERSION,
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._update_units()

    def _update_units(self) -> None:
        """Update units based on system preferences."""
        key = self.entity_description.key

        # Skip update for sensors with fixed units
        if key in FIXED_UNITS:
            self._attr_native_unit_of_measurement = FIXED_UNITS[key]
            return

        if key in UNIT_MAPPINGS:
            system = (
                HA_CONF_UNIT_SYSTEM_METRIC
                if self.hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS
                else HA_CONF_UNIT_SYSTEM_IMPERIAL
            )
            self._attr_native_unit_of_measurement = UNIT_MAPPINGS[key][system]

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

            if "station_name" in self.coordinator.data:
                attrs[ATTR_STATION_NAME] = self.coordinator.data["station_name"]

            if self.entity_description.key != "raw_metar":
                attrs[ATTR_RAW_METAR] = self.coordinator.data.get("raw_metar")

            if self.entity_description.has_history and "storage" in self.hass.data[DOMAIN]:
                storage = self.hass.data[DOMAIN]["storage"]
                history = storage.get_station_history(self._station, self.entity_description.key)
                if history:
                    attrs[ATTR_HISTORICAL_DATA] = history[-24:]  # last 24 records

                    if self.entity_description.state_class == SensorStateClass.MEASUREMENT:
                        try:
                            # history is a list of values, not dicts
                            values = []
                            for item in history[-24:]:
                                if isinstance(item, (int, float)):
                                    values.append(float(item))
                                elif isinstance(item, str):
                                    # Try to parse string as number
                                    cleaned = item.replace(".", "", 1).replace("-", "", 1)
                                    if cleaned.isdigit():
                                        values.append(float(item))

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
        """Calculate trend based on historical values."""
        if len(values) < 2:
            return "stable"

        try:
            last_value = float(values[-1])
            prev_value = float(values[-2])

            if abs(last_value) < 0.0001 or abs(prev_value) < 0.0001:
                return "stable"

            change = ((last_value - prev_value) / abs(prev_value)) * 100
            threshold = self.entity_description.trend_threshold

            if abs(change) < threshold:
                return "stable"
            return "rising" if change > 0 else "falling"

        except (ValueError, TypeError, ZeroDivisionError):
            return "stable"


    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # For wind_direction, None is a valid value when wind is VRB (variable)
        # So we need to check if the key exists in data, not if the value is not None
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return False

        key = self.entity_description.key

        # For sensors where None is a valid state (like wind_direction with VRB wind)
        # check if the key exists in data rather than checking value
        if key in ("wind_direction", "wind_gust", "wind_variable_direction"):
            # These sensors are available if coordinator has data
            # wind_direction can be None for VRB, wind_gust can be None if no gusts
            return True

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
        coordinator = coordinators[station]

        if coordinator.data is None:
            _LOGGER.warning("No data available for station %s", station)
            continue

        _LOGGER.debug("Setting up sensors for station %s", station)

        for description in SENSOR_TYPES:
            entities.append(MetarSensor(
                coordinator=coordinator,
                station=station,
                description=description,
            ))

        # Setup individual runway sensors
        runway_states = coordinator.data.get("runway_states", {})
        if runway_states:
            for runway in runway_states:
                _LOGGER.debug("Creating runway sensor for runway %s at station %s", runway, station)
                entities.append(
                    MetarSensor(
                        coordinator=coordinator,
                        station=station,
                        description=MetarSensorEntityDescription(
                            key=f"runway_{runway}",
                            name=f"Runway {runway} State",
                            value_fn=lambda data, r=runway: data.get("runway_states", {}).get(r),
                            icon="mdi:runway",
                            has_history=False,
                        )
                    )
                )

    async_add_entities(entities)
