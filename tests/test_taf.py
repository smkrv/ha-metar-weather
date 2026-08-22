"""TAF tests: client parsing, coordinator semantics, and the full stack.

The client tests run against the same mocked-aiohttp layer as the other
full-stack tests (pytest-homeassistant-custom-component's aioclient_mock),
so URL and query parameters are matched for real. The KRND raw TAF is a
genuine AWC sample and is 336 characters long - which is exactly why the
sensor's state is the issue time and the raw string lives in an attribute
(HA caps states at 255 characters).
"""

from datetime import datetime, timezone

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_metar_weather import TafDataUpdateCoordinator
from custom_components.ha_metar_weather.const import DOMAIN
from custom_components.ha_metar_weather.taf_client import (
    AWCTafApiClient,
    AWCTafApiError,
    parse_issue_time,
)

METAR_URL = "https://aviationweather.gov/api/data/metar"
TAF_URL = "https://aviationweather.gov/api/data/taf"

KRND_RAW_TAF = (
    "TAF KRND 191640Z 1917/2023 14010G15KT 9999 SCT250 QNH3014INS "
    "BECMG 1923/1924 12009KT 9999 SCT250 QNH3013INS "
    "BECMG 2005/2006 13006KT 8000 BR SCT010 BKN020 QNH3014INS "
    "BECMG 2011/2012 VRB06KT 6000 BR BKN005 OVC012 QNH3015INS "
    "BECMG 2015/2016 15012G20KT 9999 NSW SCT015 BKN030 QNH3011INS "
    "TX21/1921Z TN09/2013Z LAST NO AMDS AFT 2001 NEXT 2011"
)

# Current (2026) AWC response shape: ISO issueTime with trailing Z,
# integer mostRecent. Only the fields the client reads, plus a few extras
# it must ignore.
KRND_TAF_PAYLOAD = [
    {
        "tafId": 13565231,
        "icaoId": "KRND",
        "dbPopTime": "2026-08-19T16:45:40.000Z",
        "bulletinTime": "2026-08-19T16:45:00.000Z",
        "issueTime": "2026-08-19T16:40:00.000Z",
        "validTimeFrom": 1787503200,
        "validTimeTo": 1787611200,
        "rawTAF": KRND_RAW_TAF,
        "mostRecent": 1,
        "remarks": "",
        "name": "Randolph AFB, TX, US",
        "fcsts": [],
    }
]

LFLC_METAR_PAYLOAD = [
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


# --- parse_issue_time ---------------------------------------------------------


def test_parse_issue_time_current_iso_format():
    assert parse_issue_time("2026-08-19T16:40:00.000Z") == datetime(
        2026, 8, 19, 16, 40, tzinfo=timezone.utc
    )


def test_parse_issue_time_legacy_space_format():
    """Pre-2026 AWC format: naive "YYYY-MM-DD HH:MM:SS" is UTC."""
    assert parse_issue_time("2023-12-19 16:40:00") == datetime(
        2023, 12, 19, 16, 40, tzinfo=timezone.utc
    )


def test_parse_issue_time_epoch_seconds():
    """validTimeFrom/To are already epoch ints in today's TAF response,
    and obsTime flipped from ISO to epoch in 2026-03 - issueTime must
    survive the same flip."""
    assert parse_issue_time(1703003400) == datetime(
        2023, 12, 19, 16, 30, tzinfo=timezone.utc
    )


@pytest.mark.parametrize("raw", [None, "", "garbage", True, -5, ["x"]])
def test_parse_issue_time_unparseable_returns_none(raw):
    assert parse_issue_time(raw) is None


# --- AWCTafApiClient ----------------------------------------------------------


async def test_fetch_taf_parses_response(hass, aioclient_mock):
    aioclient_mock.get(TAF_URL, json=KRND_TAF_PAYLOAD)
    result = await AWCTafApiClient(hass).fetch_taf("krnd")

    assert result is not None
    assert result["raw_taf"] == KRND_RAW_TAF
    assert result["station_name"] == "Randolph AFB, TX, US"
    assert result["issue_time"] == datetime(2026, 8, 19, 16, 40, tzinfo=timezone.utc)
    # The ICAO code is uppercased on the wire.
    assert aioclient_mock.mock_calls[-1][1].query["ids"] == "KRND"


async def test_fetch_taf_none_on_204(hass, aioclient_mock):
    """204 = station publishes no TAF; a valid result, not an error."""
    aioclient_mock.get(TAF_URL, status=204)
    assert await AWCTafApiClient(hass).fetch_taf("UUBI") is None


async def test_fetch_taf_none_on_empty_list(hass, aioclient_mock):
    aioclient_mock.get(TAF_URL, json=[])
    assert await AWCTafApiClient(hass).fetch_taf("UUBI") is None


async def test_fetch_taf_none_on_missing_raw_taf(hass, aioclient_mock):
    payload = [dict(KRND_TAF_PAYLOAD[0], rawTAF=None)]
    aioclient_mock.get(TAF_URL, json=payload)
    assert await AWCTafApiClient(hass).fetch_taf("KRND") is None


async def test_fetch_taf_raises_on_http_error(hass, aioclient_mock):
    aioclient_mock.get(TAF_URL, status=500, text="boom")
    with pytest.raises(AWCTafApiError):
        await AWCTafApiClient(hass).fetch_taf("KRND")


async def test_fetch_taf_raises_on_connection_error(hass, aioclient_mock):
    aioclient_mock.get(TAF_URL, exc=aiohttp.ClientError("no route"))
    with pytest.raises(AWCTafApiError):
        await AWCTafApiClient(hass).fetch_taf("KRND")


async def test_fetch_taf_selects_most_recent_bulletin(hass, aioclient_mock):
    """AWC may return the scheduled TAF plus a fresh AMD; mostRecent wins."""
    older = dict(
        KRND_TAF_PAYLOAD[0],
        mostRecent=0,
        issueTime="2026-08-19T10:40:00.000Z",
        rawTAF="TAF KRND 191040Z (superseded)",
    )
    newer = dict(
        KRND_TAF_PAYLOAD[0],
        mostRecent=1,
        issueTime="2026-08-19T16:40:00.000Z",
        rawTAF="TAF AMD KRND 191640Z (current)",
    )
    aioclient_mock.get(TAF_URL, json=[older, newer])
    result = await AWCTafApiClient(hass).fetch_taf("KRND")
    assert result["raw_taf"] == "TAF AMD KRND 191640Z (current)"


# --- TafDataUpdateCoordinator -------------------------------------------------


class _StubTafClient:
    def __init__(self, results):
        self._results = list(results)

    async def fetch_taf(self, icao):
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def test_coordinator_rejects_stale_issue_time(hass):
    newer = {
        "raw_taf": "TAF KRND 191640Z (current)",
        "station_name": "Randolph AFB, TX, US",
        "issue_time": datetime(2026, 8, 19, 16, 40, tzinfo=timezone.utc),
    }
    stale = {
        "raw_taf": "TAF KRND 191040Z (stale)",
        "station_name": "Randolph AFB, TX, US",
        "issue_time": datetime(2026, 8, 19, 10, 40, tzinfo=timezone.utc),
    }
    coordinator = TafDataUpdateCoordinator(
        hass, _StubTafClient([newer, stale]), "KRND"
    )
    assert await coordinator._async_update_data() == newer
    coordinator.data = newer
    # A lagging fetch that yields an older issuance keeps the held TAF.
    assert await coordinator._async_update_data() == newer


async def test_coordinator_update_failed_on_client_error(hass):
    coordinator = TafDataUpdateCoordinator(
        hass, _StubTafClient([AWCTafApiError("API error: 500")]), "KRND"
    )
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_coordinator_none_when_no_taf(hass):
    coordinator = TafDataUpdateCoordinator(hass, _StubTafClient([None]), "KRND")
    assert await coordinator._async_update_data() is None


# --- full stack ---------------------------------------------------------------


async def _setup_lflc(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    taf_payload=None,
    taf_status: int = 200,
) -> MockConfigEntry:
    aioclient_mock.get(METAR_URL, json=LFLC_METAR_PAYLOAD)
    if taf_payload is not None:
        aioclient_mock.get(TAF_URL, json=taf_payload)
    else:
        aioclient_mock.get(TAF_URL, status=taf_status)
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
    # The first TAF fetch is an entry background task, which a bare
    # async_block_till_done() does not wait for.
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _teardown(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_taf_sensor_state_and_attributes(hass, aioclient_mock):
    """State is the issue time; the full raw TAF (336 chars here, well past
    HA's 255-char state cap) survives in the raw_taf attribute."""
    payload = [dict(KRND_TAF_PAYLOAD[0], icaoId="LFLC")]
    entry = await _setup_lflc(hass, aioclient_mock, taf_payload=payload)

    state = hass.states.get("sensor.metar_lflc_taf")
    assert state is not None
    assert state.state == "2026-08-19T16:40:00+00:00"
    assert state.attributes["raw_taf"] == KRND_RAW_TAF
    assert len(state.attributes["raw_taf"]) > 255
    assert state.attributes["station_name"] == "Randolph AFB, TX, US"
    assert state.attributes["device_class"] == "timestamp"

    await _teardown(hass, entry)


async def test_taf_sensor_unknown_when_station_has_no_taf(hass, aioclient_mock):
    """No current TAF (AWC 204) is a successful fetch: the entity exists
    and reads "unknown" - never "unavailable" (issue #13 semantics)."""
    entry = await _setup_lflc(hass, aioclient_mock, taf_status=204)

    state = hass.states.get("sensor.metar_lflc_taf")
    assert state is not None
    assert state.state == "unknown"

    await _teardown(hass, entry)


async def test_taf_sensor_unavailable_on_fetch_failure(hass, aioclient_mock):
    """A real fetch failure is the one case that reads "unavailable"."""
    entry = await _setup_lflc(hass, aioclient_mock, taf_status=500)

    state = hass.states.get("sensor.metar_lflc_taf")
    assert state is not None
    assert state.state == "unavailable"

    # METAR sensors are untouched by the TAF failure.
    metar_state = hass.states.get("sensor.metar_lflc_temperature")
    assert metar_state is not None
    assert metar_state.state not in ("unknown", "unavailable")

    await _teardown(hass, entry)


async def test_update_station_service_refreshes_taf(hass, aioclient_mock):
    """update_station refreshes the station's TAF along with its METAR."""
    entry = await _setup_lflc(hass, aioclient_mock, taf_status=204)

    payload = [dict(KRND_TAF_PAYLOAD[0], icaoId="LFLC")]
    aioclient_mock.clear_requests()
    aioclient_mock.get(METAR_URL, json=LFLC_METAR_PAYLOAD)
    aioclient_mock.get(TAF_URL, json=payload)

    await hass.services.async_call(
        DOMAIN, "update_station", {"station": "LFLC"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get("sensor.metar_lflc_taf")
    assert state.state == "2026-08-19T16:40:00+00:00"

    await _teardown(hass, entry)
