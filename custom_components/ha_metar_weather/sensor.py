"""
Sensor platform for METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Callable, Union
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
from homeassistant.helpers import entity_registry as er
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
    UNIT_NATIVE,
    NATIVE_METAR_UNITS,
    TrendState,
    MAX_HISTORY_DISPLAY,
    CLOUD_COVERAGE_OPTIONS,
    CLOUD_TYPE_OPTIONS,
    RUNWAY_SURFACE_OPTIONS,
    REPORT_TYPE_OPTIONS,
    CAVOK_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


# Sensor key -> config entry key holding the unit preference for it.
_UNIT_CONF_KEYS: dict[str, str] = {
    "temperature": CONF_TEMP_UNIT,
    "dew_point": CONF_TEMP_UNIT,
    "wind_speed": CONF_WIND_SPEED_UNIT,
    "wind_gust": CONF_WIND_SPEED_UNIT,
    "visibility": CONF_VISIBILITY_UNIT,
    "pressure": CONF_PRESSURE_UNIT,
    "cloud_coverage_height": CONF_ALTITUDE_UNIT,
}

# Config entry key -> NATIVE_METAR_UNITS key.
_NATIVE_UNIT_KEYS: dict[str, str] = {
    CONF_TEMP_UNIT: "temperature",
    CONF_WIND_SPEED_UNIT: "wind_speed",
    CONF_VISIBILITY_UNIT: "visibility",
    CONF_PRESSURE_UNIT: "pressure",
    CONF_ALTITUDE_UNIT: "altitude",
}


def resolve_display_unit(entry_data: Mapping[str, Any], sensor_key: str) -> Optional[str]:
    """Resolve the configured display unit for a sensor.

    Returns None for "auto" (HA's own unit-system default) and for sensors
    without a configurable unit.
    """
    conf_key = _UNIT_CONF_KEYS.get(sensor_key)
    if conf_key is None or sensor_key in FIXED_UNITS:
        return None

    configured = entry_data.get(conf_key, UNIT_AUTO)
    if configured == UNIT_AUTO:
        return None
    if configured == UNIT_NATIVE:
        return NATIVE_METAR_UNITS[_NATIVE_UNIT_KEYS[conf_key]]
    return configured


def sync_registry_suggested_unit(
    ent_reg: er.EntityRegistry,
    hass: HomeAssistant,
    station: str,
    description: SensorEntityDescription,
    resolved_unit: Optional[str],
) -> None:
    """Push the configured unit into an already-registered entity.

    HA core reads ``suggested_unit_of_measurement`` only when an entity is
    first registered and pins it in ``options["sensor.private"]`` forever
    (issue #7); changing the suggestion later has no effect. So on every
    setup we rewrite the stored value ourselves. A unit the user picked
    manually in the HA UI (``options["sensor"]["unit_of_measurement"]``)
    always wins and is never touched.
    """
    if description.key not in _UNIT_CONF_KEYS:
        return

    unique_id = f"{DOMAIN}_{station}_{description.key}"
    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    if entity_id is None:
        return  # new entity: __init__ provides the suggestion

    entry = ent_reg.entities[entity_id]
    if (entry.options.get("sensor") or {}).get("unit_of_measurement"):
        return

    # For "auto", mirror what core itself would store at first registration:
    # the unit system's converted unit, or nothing when the native unit
    # already matches the system.
    wanted = resolved_unit or hass.config.units.get_converted_unit(
        description.device_class, description.native_unit_of_measurement
    )
    stored = (entry.options.get("sensor.private") or {}).get(
        "suggested_unit_of_measurement"
    )
    if stored == wanted:
        return

    _LOGGER.debug(
        "Updating display unit for %s: %s -> %s", entity_id, stored, wanted
    )
    ent_reg.async_update_entity_options(
        entity_id,
        "sensor.private",
        {"suggested_unit_of_measurement": wanted} if wanted else {},
    )


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
        # QNH is atmospheric pressure; plain PRESSURE would make HA's unit
        # system pick psi instead of inHg on US installs.
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
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
        # Compositional, so not an ENUM. translation_key lets the frontend
        # localize known slugs; unknown combinations render the raw slug.
        translation_key="weather",
        value_fn=lambda data: data.get("weather", "clear"),
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
        device_class=SensorDeviceClass.ENUM,
        options=CLOUD_COVERAGE_OPTIONS,
        translation_key="cloud_coverage_state",
        value_fn=lambda data: data.get("cloud_coverage_state", "clear"),
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
        device_class=SensorDeviceClass.ENUM,
        options=CLOUD_TYPE_OPTIONS,
        translation_key="cloud_coverage_type",
        value_fn=lambda data: data.get("cloud_coverage_type", "none"),
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
        device_class=SensorDeviceClass.ENUM,
        options=REPORT_TYPE_OPTIONS,
        translation_key="report_type",
        value_fn=lambda data: "auto" if data.get("auto") else "manual",
        icon="mdi:robot",
        has_history=False,
    ),
    MetarSensorEntityDescription(
        key="cavok",
        name="CAVOK",
        device_class=SensorDeviceClass.ENUM,
        options=CAVOK_OPTIONS,
        translation_key="cavok",
        value_fn=lambda data: "yes" if data.get("cavok") else "no",
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
        # Free-form forecast group (NOSIG / TEMPO ... / BECMG ...) kept verbatim
        # from the raw METAR; language-neutral, so not translated. None -> unknown.
        value_fn=lambda data: data.get("trend"),
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
        suggested_unit: Optional[str] = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._station = station
        self._config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{station}_{description.key}"
        self._attr_name = f"METAR {station} {description.name}"
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        # Must be set before the entity is added: HA core reads the suggested
        # unit during registration, never after (issue #7). None = "auto",
        # core falls back to the unit system's preferred unit.
        if suggested_unit is not None:
            self._attr_suggested_unit_of_measurement = suggested_unit

        # Add device_info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, station)},
            "name": f"METAR {station}",
            "manufacturer": "NOAA / AWC",
            "model": "METAR Weather Station",
            "sw_version": VERSION,
            "entry_type": DeviceEntryType.SERVICE,
        }

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

            key = self.entity_description.key

            # Weather sensor: expose the structured slug breakdown for advanced use.
            if key == "weather":
                groups = self.coordinator.data.get("weather_groups")
                if groups is not None:
                    attrs["weather_groups"] = groups

            # Per-runway sensor (state = surface slug): expose the rest as attrs.
            if key.startswith("runway_") and key != "runway_states":
                runway_id = key[len("runway_"):]
                rstate = (self.coordinator.data.get("runway_states") or {}).get(runway_id)
                if rstate:
                    attrs["coverage"] = rstate.get("coverage")
                    attrs["depth"] = rstate.get("depth")
                    attrs["friction"] = rstate.get("friction")

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
    ent_reg = er.async_get(hass)
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
            resolved_unit = resolve_display_unit(config_entry.data, description.key)
            sync_registry_suggested_unit(
                ent_reg, hass, station_upper, description, resolved_unit
            )
            entities.append(MetarSensor(
                coordinator=coordinator,
                station=station_upper,
                description=description,
                config_entry=config_entry,
                suggested_unit=resolved_unit,
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
                                device_class=SensorDeviceClass.ENUM,
                                options=RUNWAY_SURFACE_OPTIONS,
                                translation_key="runway_state",
                                # State = surface slug (localized); coverage / depth /
                                # friction are exposed via extra_state_attributes.
                                value_fn=lambda data, r=runway: (
                                    data.get("runway_states", {}).get(r) or {}
                                ).get("surface"),
                                icon="mdi:runway",
                                has_history=False,
                            ),
                            config_entry=config_entry,
                        )
                    )

    async_add_entities(entities)
