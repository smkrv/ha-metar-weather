"""Statistics attributes follow the sensor's display unit.

Issue #17: the state honoured the configured unit (°F) but historical_data /
min_24h / max_24h / average_24h stayed in the internal base units (°C, km/h,
km, hPa), so anything consuming the attributes on a non-metric setup read
values wrong by a whole unit conversion. The attributes must be converted to
the same unit HA converts the state to - including a manual per-entity
override made in the HA UI.
"""

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_metar_weather.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
AWC_URL = "https://aviationweather.gov/api/data/metar"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components/."""
    return


async def _setup_lflc(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    **units: str,
) -> MockConfigEntry:
    aioclient_mock.get(
        AWC_URL, json=json.loads((FIXTURES / "awc_LFLC.json").read_text())
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="LFLC",
        title="METAR LFLC",
        data={
            "icao": "LFLC",
            "stations": ["LFLC"],
            "terms_accepted": True,
            "temperature_unit": units.get("temperature", "auto"),
            "wind_speed_unit": units.get("wind", "auto"),
            "visibility_unit": units.get("visibility", "auto"),
            "pressure_unit": units.get("pressure", "auto"),
            "altitude_unit": units.get("altitude", "auto"),
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _teardown(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, key: str):
    state = hass.states.get(f"sensor.metar_lflc_{key}")
    assert state is not None, f"sensor.metar_lflc_{key} missing"
    return state


async def test_statistics_attributes_follow_display_unit(
    hass, aioclient_mock
):
    """Issue #17: attributes must be in the same unit as the state."""
    entry = await _setup_lflc(
        hass,
        aioclient_mock,
        temperature="°F",
        wind="kn",
        visibility="mi",
        pressure="inHg",
    )

    # Temperature 14 °C -> 57.2 °F.
    temp = _state(hass, "temperature")
    assert temp.attributes["unit_of_measurement"] == "°F"
    assert float(temp.state) == pytest.approx(57.2)
    assert temp.attributes["historical_data"] == [pytest.approx(57.2)]
    assert temp.attributes["min_24h"] == pytest.approx(57.2)
    assert temp.attributes["max_24h"] == pytest.approx(57.2)
    assert temp.attributes["average_24h"] == pytest.approx(57.2)

    # Dew point rides the same temperature preference: 8 °C -> 46.4 °F.
    dew = _state(hass, "dew_point")
    assert dew.attributes["min_24h"] == pytest.approx(46.4)

    # Wind 3 kt stored as 5.556 km/h -> exactly 3 kn again.
    wind = _state(hass, "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "kn"
    assert wind.attributes["historical_data"] == [pytest.approx(3.0)]
    assert wind.attributes["min_24h"] == pytest.approx(3.0)
    assert wind.attributes["max_24h"] == pytest.approx(3.0)
    assert wind.attributes["average_24h"] == pytest.approx(3.0)

    # Visibility 9999 = 10 km -> 6.21 mi.
    vis = _state(hass, "visibility")
    assert vis.attributes["unit_of_measurement"] == "mi"
    assert vis.attributes["historical_data"] == [pytest.approx(6.21)]
    assert vis.attributes["max_24h"] == pytest.approx(6.21)

    # Pressure Q1020 -> 30.12 inHg.
    pressure = _state(hass, "pressure")
    assert pressure.attributes["unit_of_measurement"] == "inHg"
    assert pressure.attributes["historical_data"] == [pytest.approx(30.12)]
    assert pressure.attributes["max_24h"] == pytest.approx(30.12)

    # Trend thresholds keep working on the unconverted series.
    assert temp.attributes["trend"] == "stable"

    await _teardown(hass, entry)


async def test_statistics_attributes_follow_manual_ui_override(
    hass, aioclient_mock
):
    """A unit picked manually in the HA UI converts the attributes too."""
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_LFLC_wind_speed",
        suggested_object_id="metar_lflc_wind_speed",
    )
    ent_reg.async_update_entity_options(
        "sensor.metar_lflc_wind_speed",
        "sensor",
        {"unit_of_measurement": "mph"},
    )

    entry = await _setup_lflc(hass, aioclient_mock, wind="native")

    wind = _state(hass, "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "mph"
    # 3 kt = 5.556 km/h = 3.45 mph.
    assert wind.attributes["historical_data"] == [pytest.approx(3.45)]
    assert wind.attributes["max_24h"] == pytest.approx(3.45)

    await _teardown(hass, entry)


async def test_metric_auto_attributes_unchanged(hass, aioclient_mock):
    """Display unit == internal unit: values stay exactly as stored."""
    entry = await _setup_lflc(hass, aioclient_mock)

    wind = _state(hass, "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "km/h"
    assert wind.attributes["historical_data"] == [pytest.approx(5.56)]
    assert wind.attributes["min_24h"] == pytest.approx(5.56)

    await _teardown(hass, entry)
