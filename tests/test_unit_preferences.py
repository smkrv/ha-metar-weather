"""Tests for issue #7: configured unit preferences must reach Home Assistant.

HA core reads ``suggested_unit_of_measurement`` only BEFORE ``async_added_to_hass``
(during ``add_to_platform_start`` and registry-entry creation), and for entities
already present in the entity registry the value is pinned in
``options["sensor.private"]`` forever. So the integration must (a) set the
suggestion in ``__init__`` and (b) sync the registry options on every setup for
entities that already exist - without touching a manual user override stored in
``options["sensor"]["unit_of_measurement"]``.
"""

from unittest.mock import MagicMock

import pytest

from homeassistant.components.sensor import SensorDeviceClass

from custom_components.ha_metar_weather.sensor import (
    SENSOR_TYPES,
    MetarSensor,
    resolve_display_unit,
    sync_registry_suggested_unit,
)
from custom_components.ha_metar_weather.const import DOMAIN


DESCRIPTIONS = {d.key: d for d in SENSOR_TYPES}


# --- resolve_display_unit: config entry data -> desired display unit ---------


def test_resolve_auto_returns_none():
    """Auto means "let HA decide" - no explicit suggestion."""
    assert resolve_display_unit({}, "visibility") is None
    assert resolve_display_unit({"visibility_unit": "auto"}, "visibility") is None


def test_resolve_native_metar_units():
    assert resolve_display_unit({"visibility_unit": "native"}, "visibility") == "mi"
    assert resolve_display_unit({"wind_speed_unit": "native"}, "wind_speed") == "kn"
    assert resolve_display_unit({"pressure_unit": "native"}, "pressure") == "hPa"
    assert (
        resolve_display_unit({"altitude_unit": "native"}, "cloud_coverage_height")
        == "ft"
    )


def test_resolve_explicit_unit_passthrough():
    assert resolve_display_unit({"temperature_unit": "°F"}, "temperature") == "°F"
    assert resolve_display_unit({"temperature_unit": "°F"}, "dew_point") == "°F"
    assert resolve_display_unit({"wind_speed_unit": "m/s"}, "wind_gust") == "m/s"


def test_resolve_non_unit_sensors_return_none():
    """Fixed-unit and textual sensors have no configurable display unit."""
    for key in ("wind_direction", "humidity", "weather", "raw_metar"):
        assert resolve_display_unit({"temperature_unit": "°F"}, key) is None


def test_pressure_sensor_is_atmospheric_pressure():
    """QNH is atmospheric pressure; device_class PRESSURE would make HA's
    "auto" pick psi on US installs instead of inHg."""
    assert (
        DESCRIPTIONS["pressure"].device_class
        == SensorDeviceClass.ATMOSPHERIC_PRESSURE
    )


# --- MetarSensor.__init__: suggestion must exist before platform add ---------


def _make_sensor(suggested_unit):
    coordinator = MagicMock()
    config_entry = MagicMock()
    config_entry.data = {}
    return MetarSensor(
        coordinator=coordinator,
        station="LFLC",
        description=DESCRIPTIONS["visibility"],
        config_entry=config_entry,
        suggested_unit=suggested_unit,
    )


def test_init_sets_suggested_unit():
    sensor = _make_sensor("mi")
    assert sensor.suggested_unit_of_measurement == "mi"


def test_init_without_preference_leaves_suggestion_unset():
    sensor = _make_sensor(None)
    assert sensor.suggested_unit_of_measurement is None


# --- registry sync for already-registered entities ----------------------------


def _registry_with(options):
    ent_reg = MagicMock()
    entity_id = "sensor.metar_lflc_visibility"
    ent_reg.async_get_entity_id.return_value = entity_id
    entry = MagicMock()
    entry.options = options
    ent_reg.entities = {entity_id: entry}
    return ent_reg, entity_id


def _hass_with_system_unit(unit):
    hass = MagicMock()
    hass.config.units.get_converted_unit.return_value = unit
    return hass


def test_sync_updates_stale_registry_unit():
    """v3/v4.0.0 installs have the unit-system fallback pinned in the registry;
    an explicit preference must overwrite it."""
    ent_reg, entity_id = _registry_with(
        {"sensor.private": {"suggested_unit_of_measurement": "km"}}
    )
    sync_registry_suggested_unit(
        ent_reg, _hass_with_system_unit(None), "LFLC", DESCRIPTIONS["visibility"], "mi"
    )
    ent_reg.async_update_entity_options.assert_called_once_with(
        entity_id, "sensor.private", {"suggested_unit_of_measurement": "mi"}
    )


def test_sync_respects_manual_user_override():
    """A unit the user picked in the HA UI always wins; never touch it."""
    ent_reg, _ = _registry_with(
        {
            "sensor": {"unit_of_measurement": "nmi"},
            "sensor.private": {"suggested_unit_of_measurement": "km"},
        }
    )
    sync_registry_suggested_unit(
        ent_reg, _hass_with_system_unit(None), "LFLC", DESCRIPTIONS["visibility"], "mi"
    )
    ent_reg.async_update_entity_options.assert_not_called()


def test_sync_noop_when_registry_already_correct():
    ent_reg, _ = _registry_with(
        {"sensor.private": {"suggested_unit_of_measurement": "mi"}}
    )
    sync_registry_suggested_unit(
        ent_reg, _hass_with_system_unit(None), "LFLC", DESCRIPTIONS["visibility"], "mi"
    )
    ent_reg.async_update_entity_options.assert_not_called()


def test_sync_auto_restores_unit_system_default():
    """Switching back to "auto" must restore what core itself would store:
    the unit system's converted unit (e.g. mi on a US install)."""
    ent_reg, entity_id = _registry_with(
        {"sensor.private": {"suggested_unit_of_measurement": "km"}}
    )
    sync_registry_suggested_unit(
        ent_reg, _hass_with_system_unit("mi"), "LFLC", DESCRIPTIONS["visibility"], None
    )
    ent_reg.async_update_entity_options.assert_called_once_with(
        entity_id, "sensor.private", {"suggested_unit_of_measurement": "mi"}
    )


def test_sync_auto_clears_suggestion_when_native_is_system_default():
    """Auto on a metric install: core stores nothing, so clear the leftovers."""
    ent_reg, entity_id = _registry_with(
        {"sensor.private": {"suggested_unit_of_measurement": "mi"}}
    )
    sync_registry_suggested_unit(
        ent_reg, _hass_with_system_unit(None), "LFLC", DESCRIPTIONS["visibility"], None
    )
    ent_reg.async_update_entity_options.assert_called_once_with(
        entity_id, "sensor.private", {}
    )


def test_sync_skips_unregistered_entity():
    """New entities get the suggestion via __init__; nothing to sync."""
    ent_reg = MagicMock()
    ent_reg.async_get_entity_id.return_value = None
    sync_registry_suggested_unit(
        ent_reg, _hass_with_system_unit(None), "LFLC", DESCRIPTIONS["visibility"], "mi"
    )
    ent_reg.async_update_entity_options.assert_not_called()


def test_sync_skips_non_unit_sensor():
    ent_reg, _ = _registry_with({})
    sync_registry_suggested_unit(
        ent_reg, _hass_with_system_unit(None), "LFLC", DESCRIPTIONS["weather"], None
    )
    ent_reg.async_get_entity_id.assert_not_called()
    ent_reg.async_update_entity_options.assert_not_called()


def test_sync_looks_up_by_stable_unique_id():
    ent_reg, _ = _registry_with({})
    sync_registry_suggested_unit(
        ent_reg, _hass_with_system_unit(None), "LFLC", DESCRIPTIONS["visibility"], "mi"
    )
    ent_reg.async_get_entity_id.assert_called_once_with(
        "sensor", DOMAIN, f"{DOMAIN}_LFLC_visibility"
    )
