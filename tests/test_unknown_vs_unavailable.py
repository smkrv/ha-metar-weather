"""Tests for unknown-vs-unavailable semantics (issue #13, PR #15).

Fields legitimately absent from a METAR (no gust, no wind direction when the
wind is calm or variable) must read "unknown", not "unavailable": most
Lovelace cards decorate "unavailable" with a warning badge, which is wrong
for normal, expected data gaps. "unavailable" stays reserved for real fetch
failures (coordinator update failed / no data yet).

Full-stack tests use a real Home Assistant core + sensor platform with a
mocked AWC response; unit tests pin the available-property logic itself.
"""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_metar_weather.const import DOMAIN
from custom_components.ha_metar_weather.sensor import SENSOR_TYPES, MetarSensor

AWC_URL = "https://aviationweather.gov/api/data/metar"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components/."""
    return


def _payload(icao: str, raw_ob: str, **awc_fields) -> list[dict]:
    """AWC JSON mirroring the raw report; wind fields overridable per test."""
    entry = {
        "icaoId": icao,
        "name": f"{icao} test station",
        "rawOb": raw_ob,
        "obsTime": 1781088600,
        "temp": 18,
        "dewp": 4,
        "visib": "6+",
        "altim": 1021,
    }
    entry.update(awc_fields)
    return [entry]


async def _setup_station(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    icao: str,
    raw_ob: str,
    **awc_fields,
) -> MockConfigEntry:
    aioclient_mock.get(AWC_URL, json=_payload(icao, raw_ob, **awc_fields))
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=icao,
        title=f"METAR {icao}",
        data={
            "icao": icao,
            "stations": [icao],
            "terms_accepted": True,
            "temperature_unit": "auto",
            "wind_speed_unit": "auto",
            "visibility_unit": "auto",
            "pressure_unit": "auto",
            "altitude_unit": "auto",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _teardown(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, icao: str, key: str) -> str:
    state = hass.states.get(f"sensor.metar_{icao.lower()}_{key}")
    assert state is not None, f"entity for {key} missing"
    return state.state


# --- full stack: absent fields read "unknown", present ones keep values ----


async def test_calm_wind_reports_unknown_not_unavailable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """00000KT: no gust, no meaningful direction - the issue #13 case."""
    entry = await _setup_station(
        hass,
        aioclient_mock,
        "LFLC",
        "METAR LFLC 101030Z AUTO 00000KT 9999 18/04 Q1021 NOSIG",
        wdir=0,
        wspd=0,
    )
    for key in ("wind_gust", "wind_direction", "wind_variable_direction"):
        assert _state(hass, "LFLC", key) == STATE_UNKNOWN, key
    # Fields present in the report are unaffected.
    assert _state(hass, "LFLC", "temperature") == "18.0"
    assert _state(hass, "LFLC", "wind_speed") == "0.0"
    await _teardown(hass, entry)


async def test_variable_wind_direction_reports_unknown(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """VRB03KT: direction has no number; the VRB flag has its own sensor."""
    entry = await _setup_station(
        hass,
        aioclient_mock,
        "LFLC",
        "METAR LFLC 101030Z AUTO VRB03KT 9999 18/04 Q1021 NOSIG",
        wdir="VRB",
        wspd=3,
    )
    assert _state(hass, "LFLC", "wind_direction") == STATE_UNKNOWN
    assert _state(hass, "LFLC", "wind_variable_direction") == "VRB"
    assert _state(hass, "LFLC", "wind_gust") == STATE_UNKNOWN
    await _teardown(hass, entry)


async def test_no_field_reads_unavailable_on_fresh_data(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """With a successful update, no sensor of the station is 'unavailable'."""
    entry = await _setup_station(
        hass,
        aioclient_mock,
        "LFLC",
        "METAR LFLC 101030Z AUTO 33008KT 9999 SCT058 18/04 Q1021 NOSIG",
        wdir=330,
        wspd=8,
    )
    station_states = [
        s for s in hass.states.async_all() if s.entity_id.startswith("sensor.metar_lflc_")
    ]
    assert len(station_states) == len(SENSOR_TYPES)
    for state in station_states:
        assert state.state != STATE_UNAVAILABLE, state.entity_id
    await _teardown(hass, entry)


# --- unit level: the available property itself ------------------------------


def _make_sensor(coordinator, key: str = "wind_gust") -> MetarSensor:
    description = next(d for d in SENSOR_TYPES if d.key == key)
    return MetarSensor(
        coordinator=coordinator,
        station="LFLC",
        description=description,
        config_entry=MagicMock(),
    )


def test_available_true_when_field_absent_from_fresh_data():
    coordinator = MagicMock(last_update_success=True, data={"temperature": 18.0})
    assert _make_sensor(coordinator).available is True


def test_unavailable_when_update_failed():
    coordinator = MagicMock(last_update_success=False, data={"temperature": 18.0})
    assert _make_sensor(coordinator).available is False


def test_unavailable_before_first_data():
    coordinator = MagicMock(last_update_success=True, data=None)
    assert _make_sensor(coordinator).available is False
