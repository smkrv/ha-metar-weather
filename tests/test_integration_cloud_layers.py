"""Full-stack tests for the cloud_layers sensor state (issues #11, #12).

Real Home Assistant core + sensor platform with a mocked AWC response: assert
the state string the user actually sees, including the localized French form
from Gsyltc's reports ("clr Noneft" on clear sky, untranslated layer names).
"""

import pytest
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_metar_weather.const import DOMAIN

AWC_URL = "https://aviationweather.gov/api/data/metar"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components/."""
    return


def _payload(icao: str, raw_ob: str) -> list[dict]:
    return [
        {
            "icaoId": icao,
            "name": f"{icao} test station",
            "rawOb": raw_ob,
            "obsTime": 1781088600,
            "temp": 18,
            "dewp": 4,
            "wdir": 330,
            "wspd": 8,
            "visib": "6+",
            "altim": 1021,
        }
    ]


async def _setup_station(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    icao: str,
    raw_ob: str,
) -> MockConfigEntry:
    aioclient_mock.get(AWC_URL, json=_payload(icao, raw_ob))
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


def _cloud_layers_state(hass: HomeAssistant, icao: str) -> str:
    state = hass.states.get(f"sensor.metar_{icao.lower()}_cloud_layers")
    assert state is not None
    return state.state


async def test_clear_sky_no_noneft(hass, aioclient_mock):
    """Issue #11: CLR rendered as 'clr Noneft'."""
    entry = await _setup_station(
        hass, aioclient_mock, "KAUS",
        "METAR KAUS 101153Z 18007KT 10SM CLR 26/19 A3001",
    )
    state = _cloud_layers_state(hass, "KAUS")
    assert state == "No clouds below 12,000 ft"
    assert "None" not in state
    await _teardown(hass, entry)


async def test_layers_english_default(hass, aioclient_mock):
    entry = await _setup_station(
        hass, aioclient_mock, "LFLC",
        "METAR LFLC 101030Z AUTO 33008KT 9999 SCT058 BKN084 18/04 Q1021 NOSIG",
    )
    assert _cloud_layers_state(hass, "LFLC") == "Scattered 5800ft, Broken 8400ft"

    # Language-independent structured attribute: the contract for automations
    # and templates now that the state text is localized.
    state = hass.states.get("sensor.metar_lflc_cloud_layers")
    assert state.attributes["layers"] == [
        {"coverage": "scattered", "height": 5800, "type": None},
        {"coverage": "broken", "height": 8400, "type": None},
    ]
    await _teardown(hass, entry)


async def test_layers_localized_french(hass, aioclient_mock):
    """Issue #12: French install must see 'Épars ..., Fragmenté ...'."""
    hass.config.language = "fr"
    entry = await _setup_station(
        hass, aioclient_mock, "LFLC",
        "METAR LFLC 101030Z AUTO 33008KT 9999 SCT075 BKN250 18/04 Q1021 NOSIG",
    )
    assert _cloud_layers_state(hass, "LFLC") == "Épars 7500ft, Fragmenté 25000ft"
    await _teardown(hass, entry)


async def test_clear_sky_localized_french(hass, aioclient_mock):
    """Both Gsyltc issues at once: clear sky on a French install."""
    hass.config.language = "fr"
    entry = await _setup_station(
        hass, aioclient_mock, "LFPO",
        "METAR LFPO 101100Z 27005KT CAVOK 21/10 Q1018 NOSIG",
    )
    assert _cloud_layers_state(hass, "LFPO") == "Plafond et visibilité OK"
    await _teardown(hass, entry)
