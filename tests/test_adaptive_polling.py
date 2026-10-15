"""Adaptive-polling coordinator tests: cadence learning, margin learning,
retry/fallback scheduling, and the fleet-scale/toggle constraints from the
PR review (jitter width, metarType/COR filtering, DEFAULT_SCAN_INTERVAL
bounds, UpdateFailed recovery, pref_disable_polling).

Coordinator-level tests instantiate MetarDataUpdateCoordinator directly
against a stub client (mirroring test_taf.py's _StubTafClient), so the
scheduling math can be exercised without a real AWC round trip. Full-stack
tests use MockConfigEntry + aioclient_mock, matching test_report_selection.py.
"""

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_metar_weather import MetarDataUpdateCoordinator
from custom_components.ha_metar_weather.const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    ADAPTIVE_MIN_INTERVAL,
    ADAPTIVE_MAX_INTERVAL,
    ADAPTIVE_MARGIN_MIN,
    ADAPTIVE_MARGIN_MAX,
    OBS_STALE_RETRY_INTERVALS,
)

METAR_URL = "https://aviationweather.gov/api/data/metar"
# Setup also fires a TAF fetch per station; 204 = "no TAF" keeps it inert -
# every full-stack test below must mock it (repo-wide gotcha, see test_taf.py).
TAF_URL = "https://aviationweather.gov/api/data/taf"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components/."""
    return


@pytest.fixture
def hass_with_domain(hass: HomeAssistant) -> HomeAssistant:
    """A bare hass with hass.data[DOMAIN] present.

    Coordinator-level tests call _async_update_data()/_compute_next_update_
    interval() directly, bypassing full entry setup - but _async_update_data
    still reads hass.data[DOMAIN]["storage"] to save history, same as it
    would in production. Mirrors what async_setup() does for a real entry.
    """
    hass.data.setdefault(DOMAIN, {})
    return hass


class _StubMetarClient:
    """Stand-in for MetarApiClient: yields queued results/exceptions."""

    def __init__(self, results):
        self._results = list(results)
        self.last_source = "awc"

    async def fetch_data(self):
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _report(
    obs_time: datetime,
    *,
    metar_type: str = "METAR",
    receipt_time: datetime | None = None,
    temp: float = 20.0,
) -> dict:
    """A minimal parsed-report dict, shaped like MetarApiClient.fetch_data()'s
    return value (post api_client.merge_awc_numerics), for coordinator-level
    tests that don't go through the real AWC JSON parsing."""
    return {
        "raw_metar": f"METAR TEST {obs_time:%d%H%M}Z 00000KT CAVOK 20/15 Q1013",
        "station_name": "Test Station",
        "observation_time": obs_time.isoformat(),
        "metar_type": metar_type,
        "receipt_time": receipt_time.isoformat() if receipt_time else None,
        "temperature": temp,
    }


# --- fallback paths: missing/unparseable observation_time -------------------


async def test_missing_observation_time_falls_back_to_default(hass_with_domain):
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient([{"raw_metar": "x", "observation_time": None}]),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    await coordinator._async_update_data()
    assert coordinator.update_interval == DEFAULT_SCAN_INTERVAL


async def test_unparseable_observation_time_falls_back_to_default(hass_with_domain):
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient([{"raw_metar": "x", "observation_time": "not-a-date"}]),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    await coordinator._async_update_data()
    assert coordinator.update_interval == DEFAULT_SCAN_INTERVAL


# --- fallback: fewer than two deltas -----------------------------------------


async def test_single_observation_uses_default_raw_interval(hass_with_domain):
    """With < 2 samples, _learned_interval_raw() is DEFAULT_SCAN_INTERVAL;
    the scheduled delay should reflect DEFAULT_SCAN_INTERVAL + the fixed
    fallback margin (no receipt_time yet -> ADAPTIVE_INTERVAL_MARGIN), give
    or take jitter."""
    obs = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient([_report(obs)]),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    with freeze_time(obs):
        await coordinator._async_update_data()

    # obs + 30min default + 5min fallback margin + [0,8min) jitter
    low = timedelta(minutes=35)
    high = timedelta(minutes=43)
    assert low <= coordinator.update_interval <= high


# --- SPECI in the middle of the series: excluded from cadence learning ------


async def test_speci_excluded_from_interval_learning(hass_with_domain):
    """Two METARs an hour apart with a SPECI in between must learn a 60-min
    cadence, not something dragged toward the SPECI's shorter gap."""
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    t_speci = t0 + timedelta(minutes=20)
    t1 = t0 + timedelta(hours=1)
    t2 = t0 + timedelta(hours=2)

    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient(
            [
                _report(t0, metar_type="METAR"),
                _report(t_speci, metar_type="SPECI"),
                _report(t1, metar_type="METAR"),
                _report(t2, metar_type="METAR"),
            ]
        ),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )

    with freeze_time(t0):
        await coordinator._async_update_data()
    with freeze_time(t_speci):
        await coordinator._async_update_data()
    with freeze_time(t1):
        await coordinator._async_update_data()
    with freeze_time(t2):
        await coordinator._async_update_data()

    assert len(coordinator._interval_samples) == 2  # t0->t1, t1->t2 only
    assert coordinator._learned_interval_raw() == timedelta(minutes=60)
    # The SPECI still updated _last_observation_time (sensors saw it) but
    # never became _last_metar_time's source for a delta.
    assert coordinator._last_metar_time == t2


async def test_same_cycle_cor_yields_no_zero_delta_sample(hass_with_domain):
    """A COR with the same observation_time as the held report must not
    enter the delta history (it would be a zero-length sample)."""
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)

    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient(
            [
                _report(t0),
                _report(t0, temp=21.0),  # COR: same obs_time, different temp
                _report(t1),
            ]
        ),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )

    with freeze_time(t0):
        await coordinator._async_update_data()  # new observation
        await coordinator._async_update_data()  # same obs_time -> retry branch
    with freeze_time(t1):
        await coordinator._async_update_data()

    assert list(coordinator._interval_samples) == [timedelta(minutes=30)]


# --- retry exhaustion hitting the clamp --------------------------------------


async def test_retry_exhaustion_anchors_and_caps_at_default_interval(
    hass_with_domain,
):
    """A station whose publication lag runs long must be checked again
    within DEFAULT_SCAN_INTERVAL, not left waiting for the full anchor."""
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    same = _report(t0)

    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient([same, same, same, same]),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )

    with freeze_time(t0):
        await coordinator._async_update_data()  # baseline (new observation)

    # The retry chain only starts once the expected slot has passed:
    # obs + learned interval (default raw 30 min + fixed 5 min margin).
    due = t0 + DEFAULT_SCAN_INTERVAL + timedelta(minutes=5)

    for expected_delay in OBS_STALE_RETRY_INTERVALS:
        with freeze_time(due):
            await coordinator._async_update_data()  # same obs_time -> retry
        assert coordinator.update_interval == expected_delay

    # Retries exhausted: with only a single observation so far,
    # _learned_interval_raw() is DEFAULT_SCAN_INTERVAL and the anchor
    # (obs + raw + (raw+margin)) is far beyond DEFAULT_SCAN_INTERVAL out -
    # the cap must win.
    with freeze_time(due):
        await coordinator._async_update_data()

    assert coordinator.update_interval <= DEFAULT_SCAN_INTERVAL
    assert coordinator.update_interval >= ADAPTIVE_MIN_INTERVAL


async def test_final_interval_never_exceeds_configured_bounds(hass_with_domain):
    """Regardless of path, update_interval must stay within
    [ADAPTIVE_MIN_INTERVAL, ADAPTIVE_MAX_INTERVAL]."""
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)

    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient([_report(t0), _report(t1)]),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    with freeze_time(t0):
        await coordinator._async_update_data()
    with freeze_time(t1):
        await coordinator._async_update_data()

    assert ADAPTIVE_MIN_INTERVAL <= coordinator.update_interval <= ADAPTIVE_MAX_INTERVAL


# --- a failed update resets the interval -------------------------------------


async def test_update_failed_resets_interval_to_default(hass_with_domain):
    """A learned long interval (e.g. an hourly station) must not postpone
    recovery after a failed fetch by as much as the learned cadence."""
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)

    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient(
            [
                _report(t0),
                _report(t1),  # second METAR -> learns a 60-min raw cadence
                *([RuntimeError("boom")] * 10),  # exhausts RETRY_INTERVALS
            ]
        ),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    with freeze_time(t0):
        await coordinator._async_update_data()
    with freeze_time(t1):
        await coordinator._async_update_data()
    assert coordinator.update_interval > DEFAULT_SCAN_INTERVAL  # learned ~65min

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.update_interval == DEFAULT_SCAN_INTERVAL


# --- margin learning from receiptTime ----------------------------------------


async def test_margin_learned_from_receipt_time(hass_with_domain):
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)
    t2 = t0 + timedelta(minutes=60)

    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient(
            [
                _report(t0, receipt_time=t0 + timedelta(minutes=3)),
                _report(t1, receipt_time=t1 + timedelta(minutes=3)),
                _report(t2, receipt_time=t2 + timedelta(minutes=3)),
            ]
        ),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    with freeze_time(t0):
        await coordinator._async_update_data()
    with freeze_time(t1):
        await coordinator._async_update_data()
    with freeze_time(t2):
        await coordinator._async_update_data()

    assert coordinator._learned_margin() == timedelta(minutes=3)


async def test_margin_clamped_to_configured_bounds(hass_with_domain):
    """A lag inside the sanity-filter bound (<=30min) but above
    ADAPTIVE_MARGIN_MAX must still be accepted as a sample, then clamped
    down when read back - distinct from test_record_margin_sample's
    sanity filter, which rejects anything implausible outright."""
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)

    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient(
            [
                _report(t0, receipt_time=t0 + timedelta(minutes=20)),
                _report(t1, receipt_time=t1 + timedelta(minutes=20)),
            ]
        ),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    with freeze_time(t0):
        await coordinator._async_update_data()
    with freeze_time(t1):
        await coordinator._async_update_data()

    assert coordinator._learned_margin() == ADAPTIVE_MARGIN_MAX
    assert ADAPTIVE_MARGIN_MIN <= coordinator._learned_margin() <= ADAPTIVE_MARGIN_MAX


# --- storage seeding at setup -------------------------------------------------


class _StubStorage:
    def __init__(self, records):
        self._records = records

    async def async_get_all_station_records(self, station):
        return self._records


async def test_seed_from_storage_recovers_cadence(hass_with_domain):
    t0 = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)
    t2 = t0 + timedelta(minutes=60)
    storage = _StubStorage(
        [
            {
                "metar_type": "METAR",
                "observation_time": t0.isoformat(),
                "receipt_time": (t0 + timedelta(minutes=2)).isoformat(),
            },
            {
                "metar_type": "SPECI",  # must be skipped
                "observation_time": (t0 + timedelta(minutes=15)).isoformat(),
            },
            {
                "metar_type": "METAR",
                "observation_time": t1.isoformat(),
                "receipt_time": (t1 + timedelta(minutes=2)).isoformat(),
            },
            {
                # Pre-upgrade record with no metar_type at all - skipped,
                # not guessed at.
                "observation_time": (t0 - timedelta(minutes=30)).isoformat(),
            },
            {
                "metar_type": "METAR",
                "observation_time": t2.isoformat(),
                "receipt_time": (t2 + timedelta(minutes=2)).isoformat(),
            },
        ]
    )
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient([]),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )

    await coordinator.async_seed_from_storage(storage)

    assert coordinator._learned_interval_raw() == timedelta(minutes=30)
    assert coordinator._learned_margin() == timedelta(minutes=2)
    assert coordinator._last_metar_time == t2
    assert coordinator._last_observation_time == t2


async def test_seed_from_storage_noop_when_storage_is_none(hass_with_domain):
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient([]),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    await coordinator.async_seed_from_storage(None)
    assert coordinator._last_metar_time is None


# --- full stack: an entry with polling disabled still doesn't poll ----------


LFLC_METAR_PAYLOAD = [
    {
        "icaoId": "LFLC",
        "name": "Clermont-Ferrand/Auvergne Arpt, AR, FR",
        "rawOb": (
            "METAR LFLC 100100Z AUTO 09001KT 9999 FEW066 BKN110 OVC130 "
            "12/08 Q1020 NOSIG"
        ),
        "obsTime": 1781053200,
        "metarType": "METAR",
        "receiptTime": 1781053380,
        "temp": 12,
        "dewp": 8,
        "wdir": 90,
        "wspd": 1,
        "visib": "6+",
        "altim": 1020,
    }
]


async def _setup_lflc(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    *,
    pref_disable_polling: bool = False,
) -> MockConfigEntry:
    aioclient_mock.get(METAR_URL, json=LFLC_METAR_PAYLOAD)
    aioclient_mock.get(TAF_URL, status=204)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="LFLC",
        title="METAR LFLC",
        pref_disable_polling=pref_disable_polling,
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
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _teardown(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_polling_disabled_entry_does_not_reschedule(hass, aioclient_mock):
    """With 'Enable polling for updates' off, core's _schedule_refresh must
    not queue a next fetch - regardless of the adaptively-computed
    update_interval - because config_entry is now wired into the
    coordinator (it previously wasn't)."""
    entry = await _setup_lflc(hass, aioclient_mock, pref_disable_polling=True)
    coordinator = hass.data[DOMAIN][entry.entry_id]["LFLC"]
    assert coordinator.config_entry is entry

    call_count = 0

    async def _counting_fetch():
        nonlocal call_count
        call_count += 1
        return LFLC_METAR_PAYLOAD[0]

    coordinator.client.fetch_data = _counting_fetch

    from homeassistant.util import dt as dt_util

    # Advance well past any interval the adaptive schedule could have
    # picked (its ceiling is ADAPTIVE_MAX_INTERVAL); if polling were still
    # active, this would trigger at least one more coordinator refresh.
    future = dt_util.utcnow() + ADAPTIVE_MAX_INTERVAL + timedelta(minutes=5)
    with freeze_time(future):
        async_fire_time_changed(hass, future)
        await hass.async_block_till_done()

    assert call_count == 0

    await _teardown(hass, entry)


# --- jitter stays within the widened bounds ----------------------------------


async def test_jitter_stays_within_widened_bounds(hass_with_domain):
    """Regression guard for the fleet-scale correction: jitter must be able
    to reach up to 8 minutes, not be capped at the old 150s ceiling."""
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    seen_delays = set()

    for i in range(30):
        coordinator = MetarDataUpdateCoordinator(
            hass_with_domain,
            _StubMetarClient([_report(t0)]),
            f"TEST{i}",
            DEFAULT_SCAN_INTERVAL,
        )
        with freeze_time(t0):
            await coordinator._async_update_data()
        seen_delays.add(coordinator.update_interval)

    spread = max(seen_delays) - min(seen_delays)
    # 30 draws from a 0-8min uniform range should span well past the old
    # 150s-wide window at least some of the time; a flaky-but-vanishingly-
    # unlikely false negative is preferable to hardcoding the RNG.
    assert spread > timedelta(minutes=2, seconds=30)


# --- review follow-ups: SPECI anchor, silent stations, restart, AVWX, seed ---


def _seeded_coordinator(hass, last_metar: datetime, raw_min: int = 60):
    """Coordinator with a trusted cadence and a known last routine METAR."""
    coordinator = MetarDataUpdateCoordinator(
        hass, _StubMetarClient([]), "TEST", DEFAULT_SCAN_INTERVAL
    )
    for _ in range(5):
        coordinator._interval_samples.append(timedelta(minutes=raw_min))
        coordinator._margin_samples.append(timedelta(minutes=3))
    coordinator._last_metar_time = last_metar
    coordinator._last_observation_time = last_metar
    return coordinator


async def test_speci_does_not_shift_routine_anchor(hass_with_domain):
    """A SPECI mid-hour must not push the next routine fetch off the
    station's release grid: the anchor stays the last routine METAR."""
    t_metar = datetime(2026, 8, 23, 10, 50, tzinfo=timezone.utc)
    t_speci = datetime(2026, 8, 23, 11, 35, tzinfo=timezone.utc)
    coordinator = _seeded_coordinator(hass_with_domain, t_metar)
    coordinator.client = _StubMetarClient([_report(t_speci, metar_type="SPECI")])

    with freeze_time(t_speci + timedelta(minutes=4)):
        await coordinator._async_update_data()

    # Next routine: 11:50 + 3 min margin -> 11:53 (+ up to 8 min jitter),
    # i.e. 14..22 min after "now" (11:39) - not 11:35 + 63 min.
    assert timedelta(minutes=14) <= coordinator.update_interval <= timedelta(minutes=22)
    assert coordinator._last_metar_time == t_metar  # SPECI is no routine sample


async def test_untyped_report_never_learns_cadence(hass_with_domain):
    """AVWX reports carry no metar_type: they can't be told apart from a
    SPECI, so they must not feed the cadence samples."""
    t0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=17)  # could be an off-grid SPECI
    t2 = t0 + timedelta(minutes=60)
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient(
            [
                {**_report(t0), "metar_type": None},
                {**_report(t1), "metar_type": None},
                {**_report(t2), "metar_type": None},
            ]
        ),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    for t in (t0, t1, t2):
        with freeze_time(t):
            await coordinator._async_update_data()

    assert len(coordinator._interval_samples) == 0
    assert coordinator._learned_interval_raw() == DEFAULT_SCAN_INTERVAL


async def test_silent_station_does_not_loop_on_short_retries(hass_with_domain):
    """A station that stopped reporting must settle on DEFAULT_SCAN_INTERVAL
    instead of cycling 3/3/5-minute checks."""
    obs = datetime(2026, 8, 23, 0, 51, tzinfo=timezone.utc)
    coordinator = _seeded_coordinator(hass_with_domain, obs)
    data = _report(obs)

    # Well past the slot (obs + 63 min) and past the margin ceiling.
    now = obs + timedelta(hours=2)
    with freeze_time(now):
        assert (
            coordinator._compute_next_update_interval(data) == DEFAULT_SCAN_INTERVAL
        )

    # Slightly late (inside the margin ceiling): short retries, then the
    # normal cycle - never the 5-minute floor.
    now = obs + timedelta(minutes=70)
    delays = []
    for _ in range(4):
        with freeze_time(now):
            delay = coordinator._compute_next_update_interval(data)
        delays.append(delay)
        now += delay
    assert delays[:2] == list(OBS_STALE_RETRY_INTERVALS)
    assert delays[2] == DEFAULT_SCAN_INTERVAL


async def test_restart_with_unchanged_report_waits_for_next_slot(hass_with_domain):
    """After a restart the seeded report is simply refetched: that is not a
    late report, so no 3-minute retry chain - wait for the next slot."""
    obs = datetime(2026, 8, 23, 10, 53, tzinfo=timezone.utc)
    coordinator = _seeded_coordinator(hass_with_domain, obs)
    now = obs + timedelta(minutes=6)

    with freeze_time(now):
        delay = coordinator._compute_next_update_interval(_report(obs))

    # slot = obs + 60 + 3 = 11:56 -> 57 min away (+ jitter), clamped to 60.
    assert delay >= timedelta(minutes=57)
    assert delay <= ADAPTIVE_MAX_INTERVAL
    assert coordinator._stale_retry_count == 0


async def test_seed_deduplicates_repeated_history_records(hass_with_domain):
    """History appends on every fetch; the same report stored five times
    must count as one margin sample, not five."""
    t0 = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)
    record_t0 = {
        "metar_type": "METAR",
        "observation_time": t0.isoformat(),
        "receipt_time": (t0 + timedelta(minutes=10)).isoformat(),
    }
    record_t1 = {
        "metar_type": "METAR",
        "observation_time": t1.isoformat(),
        "receipt_time": (t1 + timedelta(minutes=2)).isoformat(),
    }
    storage = _StubStorage([record_t0] * 4 + [record_t1])
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain, _StubMetarClient([]), "TEST", DEFAULT_SCAN_INTERVAL
    )

    await coordinator.async_seed_from_storage(storage)

    assert len(coordinator._margin_samples) == 2
    assert len(coordinator._interval_samples) == 1


async def test_polling_disabled_also_disables_taf_polling(hass, aioclient_mock):
    """The per-entry polling toggle must cover the TAF coordinator too."""
    entry = await _setup_lflc(hass, aioclient_mock, pref_disable_polling=True)
    taf_coordinator = hass.data[DOMAIN]["taf"][entry.entry_id]["LFLC"]
    assert taf_coordinator.config_entry is entry

    await _teardown(hass, entry)
