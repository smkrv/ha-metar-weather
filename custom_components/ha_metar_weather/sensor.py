"""
Sensor platform for HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

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
    DEGREE,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_STATIONS,
    ATTR_LAST_UPDATE,
    ATTR_STATION_NAME,
    ATTR_RAW_METAR,
    ATTR_HISTORICAL_DATA,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class MetarSensorEntityDescription(SensorEntityDescription):
    """Class describing METAR sensor entities."""
    value_fn: Callable[[dict], StateType] = None
    has_history: bool = True


SENSOR_TYPES: tuple[MetarSensorEntityDescription, ...] = (
    MetarSensorEntityDescription(
        key="temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("temperature"),
        icon="mdi:thermometer",
    ),
    MetarSensorEntityDescription(
        key="dew_point",
        name="Dew Point",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("dew_point"),
        icon="mdi:water-percent",
    ),
    MetarSensorEntityDescription(
        key="wind_speed",
        name="Wind Speed",
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("wind_speed"),
        icon="mdi:weather-windy",
    ),
    MetarSensorEntityDescription(
        key="wind_direction",
        name="Wind Direction",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("wind_direction"),
        icon="mdi:compass",
    ),
    MetarSensorEntityDescription(
        key="visibility",
        name="Visibility",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("visibility"),
        icon="mdi:eye",
    ),
    MetarSensorEntityDescription(
        key="pressure",
        name="Pressure",
        native_unit_of_measurement=UnitOfPressure.HPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("pressure"),
        icon="mdi:gauge",
    ),
    MetarSensorEntityDescription(
        key="humidity",
        name="Relative Humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("humidity"),
        icon="mdi:water-percent",
    ),
    MetarSensorEntityDescription(
        key="weather",
        name="Weather Condition",
        icon="mdi:weather-partly-cloudy",
        value_fn=lambda data: data.get("weather"),
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="cloud_coverage",
        name="Cloud Coverage",
        icon="mdi:cloud",
        value_fn=lambda data: data.get("cloud_coverage"),
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="raw_metar",
        name="Raw METAR",
        icon="mdi:text",
        value_fn=lambda data: data.get("raw_metar"),
        has_history=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the METAR sensors."""
    coordinators = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[MetarSensor] = []

    # Create sensors for each station
    for station in config_entry.data[CONF_STATIONS]:
        coordinator = coordinators[station]
        for description in SENSOR_TYPES:
            entities.append(
                MetarSensor(
                    coordinator=coordinator,
                    station=station,
                    description=description,
                )
            )

    async_add_entities(entities)


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

        # Device info to group all sensors for this station
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station)},
            "name": f"METAR {station}",
            "manufacturer": "NOAA",
            "model": "METAR Weather Station",
            "sw_version": "2.0.9",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except Exception as err:
            _LOGGER.error(
                "Error getting value for %s: %s",
                self.entity_description.key,
                err
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {}

        if self.coordinator.data:
            attrs[ATTR_LAST_UPDATE] = self.coordinator.data.get("observation_time")
            attrs["station"] = self._station

            # Add raw METAR data as attribute for all sensors except raw_metar itself
            if self.entity_description.key != "raw_metar":
                attrs[ATTR_RAW_METAR] = self.coordinator.data.get("raw_metar")

            # Add historical data if supported by this sensor type
            if self.entity_description.has_history:
                storage = self.hass.data[DOMAIN]["storage"]
                history = storage.get_station_history(self._station)

                historical_values = []
                for record in history:
                    value = self.entity_description.value_fn(record)
                    if value is not None:
                        historical_values.append({
                            "timestamp": record["timestamp"],
                            "value": value
                        })

                if historical_values:
                    # Keep only last 24 records
                    attrs[ATTR_HISTORICAL_DATA] = historical_values[-24:]

                    # Calculate statistics
                    values = [item["value"] for item in historical_values]
                    if values:
                        attrs["min_24h"] = min(values)
                        attrs["max_24h"] = max(values)
                        attrs["average_24h"] = round(sum(values) / len(values), 2)

                        # Add trend calculation
                        if len(values) >= 2:
                            trend = values[-1] - values[-2]
                            attrs["trend"] = "stable" if abs(trend) < 0.1 else (
                                "rising" if trend > 0 else "falling"
                            )

            # Add station metadata
            if "station_name" in self.coordinator.data:
                attrs[ATTR_STATION_NAME] = self.coordinator.data["station_name"]

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None and
            self.native_value is not None
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()
