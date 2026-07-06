"""Runway sensors must expose a valid default icon (issue #14).

The descriptions used to point at "mdi:runway", which does not exist in the
MDI set - the frontend silently rendered no icon at all. The fix switched
both the aggregate and the per-runway sensors to "mdi:road-variant".
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


async def test_runway_sensors_use_existing_mdi_icon(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    raw_ob = "METAR UUEE 101030Z 33008KT 9999 18/04 Q1021 R24L/290062 NOSIG"
    aioclient_mock.get(
        AWC_URL,
        json=[
            {
                "icaoId": "UUEE",
                "name": "UUEE test station",
                "rawOb": raw_ob,
                "obsTime": 1781088600,
                "temp": 18,
                "dewp": 4,
                "wdir": 330,
                "wspd": 8,
                "visib": "6+",
                "altim": 1021,
            }
        ],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="UUEE",
        title="METAR UUEE",
        data={
            "icao": "UUEE",
            "stations": ["UUEE"],
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

    aggregate = hass.states.get("sensor.metar_uuee_all_runways_state")
    assert aggregate is not None
    assert aggregate.attributes["icon"] == "mdi:road-variant"

    per_runway = hass.states.get("sensor.metar_uuee_runway_24l_state")
    assert per_runway is not None
    assert per_runway.attributes["icon"] == "mdi:road-variant"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
