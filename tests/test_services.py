"""Integration services must survive an options-flow reload.

update_station and clear_history were registered only in async_setup, while
async_unload_entry removes them when the last entry unloads. An options-flow
change reloads the entry - unload plus setup - and async_setup does not run
again on reload, so both services silently disappeared until a Home Assistant
restart. Entry setup now (re-)registers them.
"""

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

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
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
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


async def test_services_survive_options_reload(hass, aioclient_mock):
    entry = await _setup_lflc(hass, aioclient_mock)
    assert hass.services.has_service(DOMAIN, "update_station")
    assert hass.services.has_service(DOMAIN, "clear_history")

    # An options change triggers update_listener -> async_reload (unload +
    # setup of the same entry).
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "wind_speed_unit": "kn"}
    )
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "update_station")
    assert hass.services.has_service(DOMAIN, "clear_history")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
