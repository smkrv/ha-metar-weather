"""Report selection: newest observation wins, stale reports are never adopted.

Issue #16: AWC's /api/data/metar windows and orders reports by *receipt* time.
When a station re-files a COR for an hours-old cycle (KSDL during a dust
event), the freshly received COR lands first in the response while carrying an
old observation time, and taking ``result[0]`` regressed every sensor to
hours-old data. Two layers guard against this now:

- the AWC client picks the report with the newest observation time
  (``obsTime``), receipt order is ignored;
- the coordinator refuses to replace held data with a report whose
  observation time is older than the one it already has (also covers the
  AVWX fallback path).
"""

from datetime import datetime, timezone

import pytest
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_metar_weather.api_client import DataSource
from custom_components.ha_metar_weather.awc_client import AWCApiClient
from custom_components.ha_metar_weather.const import DOMAIN


def _obs_epoch(minutes_from_now: float) -> int:
    """Epoch seconds relative to the real clock (negative = past)."""
    return int(
        datetime.now(timezone.utc).timestamp() + minutes_from_now * 60
    )

AWC_URL = "https://aviationweather.gov/api/data/metar"

# 2026-08-04, the reports from the issue #16 KSDL timeline (epoch UTC).
OBS_1500Z = 1785855600  # 04 15:00Z - the stale cycle the COR corrects
OBS_1753Z = 1785865980  # 04 17:53Z
OBS_1853Z = 1785869580  # 04 18:53Z - the actual current observation

STALE_COR = {
    "icaoId": "KSDL",
    "receiptTime": "2026-08-04T18:54:41.000Z",  # re-filed just now
    "obsTime": OBS_1500Z,
    "temp": 32.2,
    "dewp": 16.1,
    "wdir": 160,
    "wspd": 5,
    "visib": "5",
    "altim": 1011,
    "name": "Scottsdale Muni, AZ, US",
    "rawOb": (
        "SPECI KSDL 041500Z COR 16005KT 5SM HZ 32/16 A2987 RMK AO2 T03220161"
    ),
}

MID_REPORT = {
    "icaoId": "KSDL",
    "receiptTime": "2026-08-04T17:55:02.000Z",
    "obsTime": OBS_1753Z,
    "temp": 35.0,
    "dewp": 16.1,
    "wdir": "VRB",
    "wspd": 4,
    "visib": "5",
    "altim": 1012,
    "name": "Scottsdale Muni, AZ, US",
    "rawOb": (
        "METAR KSDL 041753Z COR VRB04KT 5SM HZ 35/16 A2989 RMK AO2 SLP089 "
        "T03500161"
    ),
}

FRESH_REPORT = {
    "icaoId": "KSDL",
    "receiptTime": "2026-08-04T18:54:39.000Z",
    "obsTime": OBS_1853Z,
    "temp": 36.1,
    "dewp": 16.7,
    "wdir": "VRB",
    "wspd": 4,
    "visib": "5",
    "altim": 1011,
    "name": "Scottsdale Muni, AZ, US",
    "rawOb": (
        "METAR KSDL 041853Z COR VRB04KT 5SM HZ 36/17 A2988 RMK AO2 SLP086 "
        "T03610167"
    ),
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components/."""
    return


async def _setup_station(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    payload: list[dict],
) -> MockConfigEntry:
    aioclient_mock.get(AWC_URL, json=payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="KSDL",
        title="METAR KSDL",
        data={
            "icao": "KSDL",
            "stations": ["KSDL"],
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


async def _refresh_with(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry: MockConfigEntry,
    payload: list[dict],
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(AWC_URL, json=payload)
    coordinator = hass.data[DOMAIN][entry.entry_id]["KSDL"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()


def _temperature(hass: HomeAssistant):
    state = hass.states.get("sensor.metar_ksdl_temperature")
    assert state is not None
    return state


# --- AWC client: observation time beats receipt order -------------------------


def test_newest_observation_selected_regardless_of_position():
    reports = [STALE_COR, FRESH_REPORT, MID_REPORT]
    assert AWCApiClient.select_newest_report(reports) is FRESH_REPORT
    assert (
        AWCApiClient.select_newest_report(list(reversed(reports)))
        is FRESH_REPORT
    )


def test_iso_obs_time_and_missing_obs_time_handled():
    iso_newest = {**FRESH_REPORT, "obsTime": "2026-08-04T19:53:00Z"}
    no_time = {k: v for k, v in MID_REPORT.items() if k != "obsTime"}
    assert (
        AWCApiClient.select_newest_report([STALE_COR, no_time, iso_newest])
        is iso_newest
    )
    # No parseable observation time anywhere: keep AWC's first item.
    assert AWCApiClient.select_newest_report([no_time]) is no_time


def test_same_cycle_cor_wins_by_receipt_time():
    original = {
        **FRESH_REPORT,
        "receiptTime": "2026-08-04T18:54:39.000Z",
        "temp": 36.1,
    }
    correction = {
        **FRESH_REPORT,
        "receiptTime": "2026-08-04T19:10:00.000Z",
        "temp": 36.7,
    }
    assert (
        AWCApiClient.select_newest_report([correction, original]) is correction
    )
    assert (
        AWCApiClient.select_newest_report([original, correction]) is correction
    )


def test_future_dated_report_is_never_selected():
    """A mis-keyed DDHHMM group decoded hours ahead must not win over the
    genuine current observation in the same response."""
    genuine = {**FRESH_REPORT, "obsTime": _obs_epoch(-10)}
    bogus = {**FRESH_REPORT, "obsTime": _obs_epoch(5 * 60)}
    assert AWCApiClient.select_newest_report([bogus, genuine]) is genuine
    assert AWCApiClient.select_newest_report([genuine, bogus]) is genuine
    # Every candidate future-dated (or the local clock is wrong): fall back
    # to AWC's first item rather than returning nothing.
    assert AWCApiClient.select_newest_report([bogus]) is bogus


# --- full stack: the KSDL regression itself -----------------------------------


async def test_stale_cor_first_in_response_is_not_adopted(
    hass, aioclient_mock
):
    """The exact issue #16 payload shape: re-filed old COR listed first."""
    entry = await _setup_station(
        hass, aioclient_mock, [STALE_COR, FRESH_REPORT, MID_REPORT]
    )

    temp = _temperature(hass)
    assert float(temp.state) == pytest.approx(36.1)
    assert temp.attributes["last_update"] == "2026-08-04T18:53:00+00:00"

    await _teardown(hass, entry)


async def test_coordinator_keeps_held_data_over_older_observation(
    hass, aioclient_mock
):
    """A later poll returning only the stale COR must not regress sensors."""
    entry = await _setup_station(hass, aioclient_mock, [FRESH_REPORT])
    assert float(_temperature(hass).state) == pytest.approx(36.1)

    await _refresh_with(hass, aioclient_mock, entry, [STALE_COR])

    temp = _temperature(hass)
    assert temp.state not in ("unavailable", "unknown")
    assert float(temp.state) == pytest.approx(36.1)
    assert temp.attributes["last_update"] == "2026-08-04T18:53:00+00:00"

    await _teardown(hass, entry)


async def test_same_observation_correction_is_adopted(hass, aioclient_mock):
    """A COR for the *current* cycle carries the same observation time and
    must replace the held values - the guard only rejects strictly older."""
    entry = await _setup_station(hass, aioclient_mock, [FRESH_REPORT])
    assert float(_temperature(hass).state) == pytest.approx(36.1)

    corrected = {
        **FRESH_REPORT,
        "temp": 36.7,
        "receiptTime": "2026-08-04T19:10:00.000Z",
        "rawOb": (
            "METAR KSDL 041853Z COR VRB04KT 5SM HZ 37/17 A2988 RMK AO2 "
            "SLP086 T03670167"
        ),
    }
    await _refresh_with(hass, aioclient_mock, entry, [corrected])

    assert float(_temperature(hass).state) == pytest.approx(36.7)

    await _teardown(hass, entry)


async def test_newer_observation_still_replaces_held_data(
    hass, aioclient_mock
):
    """Normal forward progress must be unaffected by the stale guard."""
    entry = await _setup_station(hass, aioclient_mock, [MID_REPORT])
    assert float(_temperature(hass).state) == pytest.approx(35.0)

    await _refresh_with(hass, aioclient_mock, entry, [FRESH_REPORT])

    temp = _temperature(hass)
    assert float(temp.state) == pytest.approx(36.1)
    assert temp.attributes["last_update"] == "2026-08-04T18:53:00+00:00"

    await _teardown(hass, entry)


# --- guard poisoning: fabricated and future observation times -----------------


async def test_missing_obs_time_cannot_block_later_reports(
    hass, aioclient_mock
):
    """A report without obsTime must not synthesize a wall-clock observation
    time: that stamp would out-rank every genuine report for a full cycle
    and freeze the sensors while they look healthy."""
    unstamped = {
        k: v for k, v in FRESH_REPORT.items() if k != "obsTime"
    } | {"temp": 30.0}
    entry = await _setup_station(hass, aioclient_mock, [unstamped])

    temp = _temperature(hass)
    assert float(temp.state) == pytest.approx(30.0)
    assert temp.attributes.get("last_update") is None

    genuine = {**FRESH_REPORT, "obsTime": _obs_epoch(-10), "temp": 21.0}
    await _refresh_with(hass, aioclient_mock, entry, [genuine])

    assert float(_temperature(hass).state) == pytest.approx(21.0)

    await _teardown(hass, entry)


async def test_future_dated_held_state_recovers(hass, aioclient_mock):
    """If a future-dated report ever became the held state, the guard must
    not wedge on it: the next genuine report is accepted."""
    bogus = {**FRESH_REPORT, "obsTime": _obs_epoch(5 * 60), "temp": 30.0}
    entry = await _setup_station(hass, aioclient_mock, [bogus])
    assert float(_temperature(hass).state) == pytest.approx(30.0)

    genuine = {**FRESH_REPORT, "obsTime": _obs_epoch(-5), "temp": 21.0}
    await _refresh_with(hass, aioclient_mock, entry, [genuine])

    assert float(_temperature(hass).state) == pytest.approx(21.0)

    await _teardown(hass, entry)


# --- data_source provenance ---------------------------------------------------


async def test_data_source_reflects_held_data_not_rejected_fetch(
    hass, aioclient_mock
):
    """When a stale fetch is rejected, the data_source attribute must keep
    naming the source of the data on display, not the rejected fetch's."""
    entry = await _setup_station(hass, aioclient_mock, [FRESH_REPORT])
    coordinator = hass.data[DOMAIN][entry.entry_id]["KSDL"]
    assert _temperature(hass).attributes["data_source"] == "awc"

    stale = dict(coordinator.data)
    stale["observation_time"] = "2026-08-04T15:00:00+00:00"
    stale["temperature"] = 32.2

    async def _stale_avwx_fetch():
        coordinator.client._last_source = DataSource.AVWX
        return stale

    coordinator.client.fetch_data = _stale_avwx_fetch
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    temp = _temperature(hass)
    assert float(temp.state) == pytest.approx(36.1)
    assert temp.attributes["data_source"] == "awc"

    await _teardown(hass, entry)
