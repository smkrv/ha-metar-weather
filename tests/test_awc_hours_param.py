"""AWC rejects a fractional ``hours`` query parameter (issue #24).

Since 2026-11-02 aviationweather.gov validates ``hours`` as a whole number:
``/api/data/metar?ids=EBAW&format=json&hours=2`` returns the reports, while
``hours=2.0`` (or any other fractional value) returns HTTP 400 with
``{"status":"error","error":"Invalid value for hours"}`` (checked live on
2026-11-03). The integration sent ``hours=2.0``, so every AWC request failed,
station validation in the config flow failed, and existing stations went
unavailable whenever the AVWX fallback could not answer either.

The mock below reproduces that validation, so these tests fail for any
request whose ``hours`` value is not an integer literal. The EBAW payload is
the live AWC response captured on 2026-11-03 (``tests/fixtures/awc_EBAW.json``).
"""

import json
from http import HTTPStatus
from pathlib import Path

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.ha_metar_weather.awc_client import (
    AWCApiClient,
    validate_station_awc,
)
from custom_components.ha_metar_weather.const import DOMAIN

AWC_URL = "https://aviationweather.gov/api/data/metar"
# Setup also fires a TAF fetch per station; 204 = "no TAF" keeps it inert.
TAF_URL = "https://aviationweather.gov/api/data/taf"
FIXTURES = Path(__file__).parent / "fixtures"
INVALID_HOURS_BODY = '{"status":"error","error":"Invalid value for hours"}'


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components/."""
    return


def _ebaw_payload() -> list[dict]:
    return json.loads((FIXTURES / "awc_EBAW.json").read_text())


def _mock_awc_with_hours_validation(aioclient_mock: AiohttpClientMocker) -> None:
    """AWC as it behaves since 2026-11-02: whole hours only."""
    payload = _ebaw_payload()

    async def _respond(method, url, data):
        hours = url.query.get("hours", "")
        if hours.isdigit():
            return AiohttpClientMockResponse(method, url, json=payload)
        return AiohttpClientMockResponse(
            method, url, status=HTTPStatus.BAD_REQUEST, text=INVALID_HOURS_BODY
        )

    aioclient_mock.get(AWC_URL, side_effect=_respond)
    aioclient_mock.get(TAF_URL, status=204)


def _awc_metar_calls(aioclient_mock: AiohttpClientMocker) -> list:
    return [
        url
        for _method, url, _data, _headers in aioclient_mock.mock_calls
        if url.path == "/api/data/metar"
    ]


async def test_metar_request_sends_whole_hours(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """The request carries ``hours=2`` and AWC answers with the reports."""
    _mock_awc_with_hours_validation(aioclient_mock)

    report = await AWCApiClient(hass).fetch_single_metar("EBAW")

    assert report is not None
    assert report["rawOb"].startswith("METAR EBAW 031020Z")
    calls = _awc_metar_calls(aioclient_mock)
    assert len(calls) == 1
    # Two-hour window, written as an integer literal.
    assert calls[0].query["hours"] == "2"


async def test_station_validation_accepts_ebaw(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Config flow validation goes through the same request."""
    _mock_awc_with_hours_validation(aioclient_mock)

    assert await validate_station_awc(hass, "EBAW") is True


async def test_ebaw_setup_reads_awc_data(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """The issue #24 station sets up from AWC and reports its values."""
    _mock_awc_with_hours_validation(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="EBAW",
        title="METAR EBAW",
        data={
            "icao": "EBAW",
            "stations": ["EBAW"],
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
    await hass.async_block_till_done(wait_background_tasks=True)

    temperature = hass.states.get("sensor.metar_ebaw_temperature")
    assert temperature is not None
    assert temperature.state != STATE_UNAVAILABLE
    # "09/08" in METAR EBAW 031020Z: 9 degrees C.
    assert temperature.state == "9.0"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
