"""
Tests for the TAF (Terminal Aerodrome Forecast) client.

Self-contained: mocks aiohttp at the async_get_clientsession() boundary
rather than depending on a specific test harness (e.g.
pytest-homeassistant-custom-component's `hass` fixture), since this
integration's existing tests/ directory wasn't available to model these
tests after. If the project's conftest.py already provides a `hass`
fixture with a real aiohttp session, `hass` below can be swapped for it
and the `async_get_clientsession` patch removed.

The KRND sample payload is a real AWC /api/data/taf?format=json response
(reproduced from AWC's own API documentation), so these tests exercise the
client against the actual response shape, not a hand-invented one.

@license: MIT
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ha_metar_weather.taf_client import (
    AWCTafApiClient,
    AWCTafApiError,
    TafApiClient,
)


# --------------------------------------------------------------------------
# Fixtures / test doubles
# --------------------------------------------------------------------------

class _MockResponse:
    """Minimal async-context-manager stand-in for aiohttp.ClientResponse."""

    def __init__(self, status: int, payload=None, text: str = ""):
        self.status = status
        self._payload = payload
        self._text = text

    async def json(self):
        return self._payload

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _MockSession:
    """Stand-in for the aiohttp.ClientSession returned by
    async_get_clientsession(). `get()` returns a _MockResponse regardless
    of the URL/params passed - tests assert behaviour via the response
    they inject, not via request inspection.
    """

    def __init__(self, response: _MockResponse):
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


@pytest.fixture
def hass():
    """A bare mock; AWCTafApiClient only passes this through to
    async_get_clientsession(), which is patched below."""
    return MagicMock()


def _client_with_response(response: _MockResponse) -> AWCTafApiClient:
    with patch(
        "custom_components.ha_metar_weather.taf_client.async_get_clientsession",
        return_value=_MockSession(response),
    ):
        return AWCTafApiClient(hass=MagicMock())


# --------------------------------------------------------------------------
# Real AWC sample response (KRND) - from AWC's own API documentation.
# --------------------------------------------------------------------------

KRND_TAF_RESPONSE = [
    {
        "tafId": 13565231,
        "icaoId": "KRND",
        "dbPopTime": "2023-12-19 16:45:40",
        "bulletinTime": "2023-12-19 16:45:00",
        "issueTime": "2023-12-19 16:40:00",
        "validTimeFrom": 1703005200,
        "validTimeTo": 1703113200,
        "rawTAF": (
            "TAF KRND 191640Z 1917/2023 14010G15KT 9999 SCT250 QNH3014INS "
            "BECMG 1923/1924 12009KT 9999 SCT250 QNH3013INS "
            "BECMG 2005/2006 13006KT 8000 BR SCT010 BKN020 QNH3014INS "
            "BECMG 2011/2012 VRB06KT 6000 BR BKN005 OVC012 QNH3015INS "
            "BECMG 2015/2016 15012G20KT 9999 NSW SCT015 BKN030 QNH3011INS "
            "TX21/1921Z TN09/2013Z LAST NO AMDS AFT 2001 NEXT 2011"
        ),
        "mostRecent": 1,
        "remarks": "",
        "lat": 29.537,
        "lon": -98.268,
        "elev": 224,
        "prior": 6,
        "name": "Randolph AFB, TX, US",
        "fcsts": [
            {
                "timeGroup": 0,
                "timeFrom": 1703005200,
                "timeTo": 1703026800,
                "fcstChange": None,
                "probability": None,
                "wdir": 140,
                "wspd": 10,
                "wgst": 15,
                "visib": "6+",
                "altim": 1021,
                "wxString": None,
            },
        ],
    }
]


# --------------------------------------------------------------------------
# AWCTafApiClient.fetch_taf()
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_taf_returns_raw_taf_and_metadata():
    """A normal 200 JSON response yields the raw TAF string plus
    station name / issue time, matching the real KRND response."""
    response = _MockResponse(status=200, payload=KRND_TAF_RESPONSE)
    client = _client_with_response(response)

    result = await client.fetch_taf("KRND")

    assert result is not None
    assert result["raw_taf"].startswith("TAF KRND 191640Z")
    assert result["station_name"] == "Randolph AFB, TX, US"
    assert result["issue_time"] == "2023-12-19 16:40:00"


@pytest.mark.asyncio
async def test_fetch_taf_returns_none_on_204():
    """No content (204) means the station has no current TAF - not an
    error, just no data (e.g. a smaller airport without TAF service)."""
    response = _MockResponse(status=204)
    client = _client_with_response(response)

    result = await client.fetch_taf("EDXX")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_taf_returns_none_on_empty_list():
    """AWC can legitimately return an empty JSON list for an unknown or
    currently silent station."""
    response = _MockResponse(status=200, payload=[])
    client = _client_with_response(response)

    result = await client.fetch_taf("ZZZZ")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_taf_raises_on_http_error():
    """A non-200/204 status (e.g. AWC outage) surfaces as AWCTafApiError
    so the coordinator's retry logic can act on it, rather than silently
    returning None (which would look identical to "no TAF exists")."""
    response = _MockResponse(status=500, text="internal server error")
    client = _client_with_response(response)

    with pytest.raises(AWCTafApiError):
        await client.fetch_taf("KRND")


@pytest.mark.asyncio
async def test_fetch_taf_selects_most_recent_bulletin():
    """When AWC returns more than one bulletin for a station (e.g. the
    scheduled TAF plus a just-issued AMD), the one flagged mostRecent=1
    wins - not just the first item in the list."""
    older = dict(KRND_TAF_RESPONSE[0])
    older["mostRecent"] = 0
    older["issueTime"] = "2023-12-19 10:00:00"
    older["rawTAF"] = "TAF KRND 191000Z (older scheduled TAF)"

    newer = dict(KRND_TAF_RESPONSE[0])
    newer["mostRecent"] = 1
    newer["issueTime"] = "2023-12-19 16:40:00"
    newer["rawTAF"] = "TAF AMD KRND 191640Z (newer amendment)"

    # Older bulletin listed first, to make sure list order isn't relied on.
    response = _MockResponse(status=200, payload=[older, newer])
    client = _client_with_response(response)

    result = await client.fetch_taf("KRND")

    assert result["raw_taf"] == "TAF AMD KRND 191640Z (newer amendment)"


@pytest.mark.asyncio
async def test_fetch_taf_missing_raw_taf_field_returns_none():
    """A malformed/incomplete AWC response (no rawTAF) must not crash the
    coordinator - it's treated the same as "no TAF available"."""
    broken = dict(KRND_TAF_RESPONSE[0])
    del broken["rawTAF"]
    response = _MockResponse(status=200, payload=[broken])
    client = _client_with_response(response)

    result = await client.fetch_taf("KRND")

    assert result is None


# --------------------------------------------------------------------------
# TafApiClient wrapper (used by TafDataUpdateCoordinator)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_taf_api_client_sets_last_source_on_success():
    """last_source is used by the coordinator/sensor attributes to show
    where the currently displayed TAF came from."""
    with patch(
        "custom_components.ha_metar_weather.taf_client.async_get_clientsession",
        return_value=MagicMock(),
    ):
        client = TafApiClient(hass=MagicMock(), icao="krnd")
    client._awc_client = AsyncMock()
    client._awc_client.fetch_taf = AsyncMock(
        return_value={"raw_taf": "TAF KRND ...", "station_name": None, "issue_time": None}
    )

    assert client.last_source is None
    data = await client.fetch_data()

    assert data is not None
    assert client.last_source == "awc"


@pytest.mark.asyncio
async def test_taf_api_client_uppercases_icao():
    """ICAO codes are matched case-sensitively by some downstream code
    (e.g. hass.data[DOMAIN]["taf"][entry_id] keys), so the wrapper must
    normalize lowercase input the same way MetarApiClient does."""
    with patch(
        "custom_components.ha_metar_weather.taf_client.async_get_clientsession",
        return_value=MagicMock(),
    ):
        client = TafApiClient(hass=MagicMock(), icao="krnd")
    assert client.icao == "KRND"


@pytest.mark.asyncio
async def test_taf_api_client_last_source_stays_none_when_no_taf():
    """If the station has no TAF, last_source must not claim "awc" served
    data it didn't actually serve."""
    with patch(
        "custom_components.ha_metar_weather.taf_client.async_get_clientsession",
        return_value=MagicMock(),
    ):
        client = TafApiClient(hass=MagicMock(), icao="EDXX")
    client._awc_client = AsyncMock()
    client._awc_client.fetch_taf = AsyncMock(return_value=None)

    data = await client.fetch_data()

    assert data is None
    assert client.last_source is None
