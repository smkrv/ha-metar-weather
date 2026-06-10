"""Full-stack tests: real Home Assistant core + entity registry, mocked AWC.

These run the integration exactly as Home Assistant does - config entry setup,
coordinator first refresh over a mocked aiohttp session, sensor platform,
entity registry - and assert what the user actually sees: state values, the
unit of measurement after registry resolution, and the display precision the
frontend will apply. Regression coverage for issues #7/#8 and the follow-up
"1 kt shows as 1.03 kn" report.
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

# Exactly 1 knot of wind (issue #7 follow-up: was displayed as "1.03 kn").
NICKDUINO_PAYLOAD = [
    {
        "icaoId": "LFLC",
        "name": "Clermont-Ferrand/Auvergne Arpt, AR, FR",
        "rawOb": (
            "METAR LFLC 100100Z AUTO 09001KT 9999 FEW066 BKN110 OVC130 "
            "12/08 Q1020 NOSIG"
        ),
        "obsTime": 1781053200,
        "temp": 12,
        "dewp": 8,
        "wdir": 90,
        "wspd": 1,
        "visib": "6+",
        "altim": 1020,
    }
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components/."""
    return


def _load_payload(icao: str) -> list[dict]:
    return json.loads((FIXTURES / f"awc_{icao}.json").read_text())


async def _setup_station(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    icao: str,
    payload: list[dict] | None = None,
    **units: str,
) -> MockConfigEntry:
    aioclient_mock.get(
        AWC_URL, json=payload if payload is not None else _load_payload(icao)
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=icao,
        title=f"METAR {icao}",
        data={
            "icao": icao,
            "stations": [icao],
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
    """Unload so the storage debouncer and coordinator timers are cancelled."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, icao: str, key: str):
    state = hass.states.get(f"sensor.metar_{icao.lower()}_{key}")
    assert state is not None, f"sensor.metar_{icao.lower()}_{key} missing"
    return state


# --- auto mode: HA's own (metric) unit system ---------------------------------


async def test_auto_units_follow_ha_metric_system(hass, aioclient_mock):
    entry = await _setup_station(hass, aioclient_mock, "LFLC")

    wind = _state(hass, "LFLC", "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "km/h"
    assert float(wind.state) == pytest.approx(5.556, abs=1e-9)  # 3 kt exactly

    vis = _state(hass, "LFLC", "visibility")
    assert vis.attributes["unit_of_measurement"] == "km"
    assert float(vis.state) == pytest.approx(10.0, abs=1e-9)  # 9999 = 10 km

    pressure = _state(hass, "LFLC", "pressure")
    assert pressure.attributes["unit_of_measurement"] == "hPa"
    assert float(pressure.state) == pytest.approx(1020.0, abs=1e-9)

    temp = _state(hass, "LFLC", "temperature")
    assert temp.attributes["unit_of_measurement"] == "°C"
    assert float(temp.state) == pytest.approx(14.0, abs=1e-9)

    # History attributes stay in internal base units but are rounded for
    # readability; statistics follow the same contract.
    assert wind.attributes["historical_data"] == [5.56]
    assert wind.attributes["min_24h"] == 5.56
    assert wind.attributes["max_24h"] == 5.56

    await _teardown(hass, entry)


# --- native mode: units of the station's own report ---------------------------


async def test_native_units_icao_station(hass, aioclient_mock):
    entry = await _setup_station(
        hass,
        aioclient_mock,
        "LFLC",
        wind="native",
        visibility="native",
        pressure="native",
    )

    wind = _state(hass, "LFLC", "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "kn"
    assert float(wind.state) == pytest.approx(3.0, abs=1e-9)  # 06003KT

    vis = _state(hass, "LFLC", "visibility")
    assert vis.attributes["unit_of_measurement"] == "m"
    assert float(vis.state) == pytest.approx(10000.0, abs=1e-6)

    pressure = _state(hass, "LFLC", "pressure")
    assert pressure.attributes["unit_of_measurement"] == "hPa"
    assert float(pressure.state) == pytest.approx(1020.0, abs=1e-9)

    await _teardown(hass, entry)


async def test_native_units_us_station(hass, aioclient_mock):
    entry = await _setup_station(
        hass,
        aioclient_mock,
        "KJFK",
        wind="native",
        visibility="native",
        pressure="native",
    )

    wind = _state(hass, "KJFK", "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "kn"
    assert float(wind.state) == pytest.approx(6.0, abs=1e-9)  # 22006KT

    vis = _state(hass, "KJFK", "visibility")
    assert vis.attributes["unit_of_measurement"] == "mi"
    assert float(vis.state) == pytest.approx(10.0, abs=1e-9)  # 10SM

    pressure = _state(hass, "KJFK", "pressure")
    assert pressure.attributes["unit_of_measurement"] == "inHg"
    assert float(pressure.state) == pytest.approx(30.02, abs=1e-6)  # A3002

    # Precision 2 comes from DISPLAY_PRECISION_BY_UNIT keyed by the suggested
    # unit (core ratio-adjusts only on a manual user override), so
    # "30.02 inHg" is shown exactly as reported.
    ent_reg = er.async_get(hass)
    options = ent_reg.async_get("sensor.metar_kjfk_pressure").options
    assert options["sensor"]["suggested_display_precision"] == 2

    # T-group decimals from AWC survive (temp 17.8, not 18 from the main group).
    temp = _state(hass, "KJFK", "temperature")
    assert float(temp.state) == pytest.approx(17.8, abs=1e-9)

    await _teardown(hass, entry)


async def test_native_units_mps_station_with_cavok_and_runways(
    hass, aioclient_mock
):
    entry = await _setup_station(
        hass,
        aioclient_mock,
        "UUEE",
        wind="native",
        visibility="native",
        pressure="native",
    )

    wind = _state(hass, "UUEE", "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "m/s"
    assert float(wind.state) == pytest.approx(3.0, abs=1e-9)  # 28003MPS

    vis = _state(hass, "UUEE", "visibility")
    assert vis.attributes["unit_of_measurement"] == "m"
    assert float(vis.state) == pytest.approx(10000.0, abs=1e-6)  # CAVOK

    assert _state(hass, "UUEE", "cavok").state == "yes"
    assert _state(hass, "UUEE", "runway_24l_state").state == "cleared"

    await _teardown(hass, entry)


# --- the 1.03 kn regression ----------------------------------------------------


async def test_one_knot_wind_displays_as_one_knot(hass, aioclient_mock):
    """09001KT with the kn display unit must be exactly 1, not 1.03."""
    entry = await _setup_station(
        hass, aioclient_mock, "LFLC", payload=NICKDUINO_PAYLOAD, wind="kn"
    )

    wind = _state(hass, "LFLC", "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "kn"
    assert float(wind.state) == pytest.approx(1.0, abs=1e-9)

    # Frontend rounds wind to 1 decimal: "1.0 kn".
    ent_reg = er.async_get(hass)
    options = ent_reg.async_get("sensor.metar_lflc_wind_speed").options
    assert options["sensor"]["suggested_display_precision"] == 1

    await _teardown(hass, entry)


# --- registry behaviour across reconfiguration --------------------------------


async def test_stale_pinned_unit_is_rewritten_on_setup(hass, aioclient_mock):
    """Pre-v4.0.1 installs have HA's fallback pinned in the registry; an
    explicit preference must overwrite it on the next setup."""
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_LFLC_wind_speed",
        suggested_object_id="metar_lflc_wind_speed",
    )
    ent_reg.async_update_entity_options(
        "sensor.metar_lflc_wind_speed",
        "sensor.private",
        {"suggested_unit_of_measurement": "km/h"},
    )

    entry = await _setup_station(hass, aioclient_mock, "LFLC", wind="native")

    options = ent_reg.async_get("sensor.metar_lflc_wind_speed").options
    assert options["sensor.private"]["suggested_unit_of_measurement"] == "kn"

    wind = _state(hass, "LFLC", "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "kn"
    assert float(wind.state) == pytest.approx(3.0, abs=1e-9)

    await _teardown(hass, entry)


async def test_manual_user_override_is_never_touched(hass, aioclient_mock):
    """A unit picked in the HA UI wins over any integration preference."""
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

    entry = await _setup_station(hass, aioclient_mock, "LFLC", wind="native")

    wind = _state(hass, "LFLC", "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "mph"
    # 3 kt = 5.556 km/h = 3.452... mph
    assert float(wind.state) == pytest.approx(3.4524, abs=1e-3)

    options = ent_reg.async_get("sensor.metar_lflc_wind_speed").options
    assert options["sensor"]["unit_of_measurement"] == "mph"

    await _teardown(hass, entry)


async def test_second_setup_is_idempotent(hass, aioclient_mock):
    """A restart (unload + setup) must not flip-flop any registry options."""
    entry = await _setup_station(
        hass,
        aioclient_mock,
        "KJFK",
        wind="native",
        visibility="native",
        pressure="native",
    )
    ent_reg = er.async_get(hass)
    before = {
        e.entity_id: dict(e.options)
        for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    }
    assert before

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    after = {
        e.entity_id: dict(e.options)
        for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    }
    assert after == before

    await _teardown(hass, entry)


async def test_precision_repinned_when_unit_changes(hass, aioclient_mock):
    """Switching visibility native(m) -> mi must repin the display precision
    (0 decimals for meters, 2 for miles), not keep the stale value."""
    entry = await _setup_station(hass, aioclient_mock, "LFLC", visibility="native")
    ent_reg = er.async_get(hass)

    options = ent_reg.async_get("sensor.metar_lflc_visibility").options
    assert options["sensor.private"]["suggested_unit_of_measurement"] == "m"
    assert options["sensor"]["suggested_display_precision"] == 0

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "visibility_unit": "mi"}
    )
    await hass.async_block_till_done()

    options = ent_reg.async_get("sensor.metar_lflc_visibility").options
    assert options["sensor.private"]["suggested_unit_of_measurement"] == "mi"
    assert options["sensor"]["suggested_display_precision"] == 2

    vis = _state(hass, "LFLC", "visibility")
    assert vis.attributes["unit_of_measurement"] == "mi"
    assert float(vis.state) == pytest.approx(6.213712, abs=1e-5)  # 10 km

    await _teardown(hass, entry)


async def test_unit_change_applies_after_reload(hass, aioclient_mock):
    """Changing the preference in the options flow reloads the entry and the
    new unit must reach already-registered entities."""
    entry = await _setup_station(hass, aioclient_mock, "LFLC", wind="native")
    assert (
        _state(hass, "LFLC", "wind_speed").attributes["unit_of_measurement"]
        == "kn"
    )

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "wind_speed_unit": "m/s"}
    )
    await hass.async_block_till_done()

    wind = _state(hass, "LFLC", "wind_speed")
    assert wind.attributes["unit_of_measurement"] == "m/s"
    assert float(wind.state) == pytest.approx(1.543333, abs=1e-5)  # 3 kt

    await _teardown(hass, entry)
