"""Adaptive-polling coordinator tests.

The schedule is a per-station grid: origin = last routine METAR + learned
margin, step = cadence split into parts of at most DEFAULT_SCAN_INTERVAL,
target = origin + k * step + the install's stable offset (smallest k at
least ADAPTIVE_MIN_INTERVAL ahead). Cadence and publication lag are learned
from the routine-METAR history inside each AWC response, never from this
install's own polling. Expected intervals below are computed by hand from
that definition (offset pinned via ``coordinator._offset``), not accepted
from ranges.

Coordinator-level tests instantiate MetarDataUpdateCoordinator directly
against a stub client (mirroring test_taf.py's _StubTafClient), so the
scheduling math can be exercised without a real AWC round trip. Full-stack
tests use MockConfigEntry + aioclient_mock, matching test_report_selection.py.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_metar_weather import MetarDataUpdateCoordinator
from custom_components.ha_metar_weather.awc_client import AWCApiClient
from custom_components.ha_metar_weather.const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    ADAPTIVE_MIN_INTERVAL,
    ADAPTIVE_MAX_INTERVAL,
    ADAPTIVE_MARGIN_MIN,
    ADAPTIVE_MARGIN_MAX,
    ADAPTIVE_OFFSET_SPAN_SECONDS,
)

METAR_URL = "https://aviationweather.gov/api/data/metar"
# Setup also fires a TAF fetch per station; 204 = "no TAF" keeps it inert -
# every full-stack test below must mock it (repo-wide gotcha, see test_taf.py).
TAF_URL = "https://aviationweather.gov/api/data/taf"

MIN = timedelta(minutes=1)
T0 = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)


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
    """Stand-in for MetarApiClient: yields queued results/exceptions.

    A result is a report dict, an exception, or ``(report, history)`` where
    history is the routine-METAR list MetarApiClient.routine_history would
    carry for that fetch.
    """

    def __init__(self, results):
        self._results = list(results)
        self.last_source = "awc"
        self.routine_history = []
        self.calls = 0

    async def fetch_data(self):
        self.calls += 1
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, tuple):
            result, self.routine_history = result
        return result


def _report(
    obs_time: datetime,
    *,
    metar_type: str | None = "METAR",
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


def _history(*obs_times: datetime, lag: timedelta = 4 * MIN):
    """Routine-METAR history as AWC would carry it: (obs, obs + lag) pairs."""
    return [(obs, obs + lag) for obs in obs_times]


def _coordinator(hass, *, offset: timedelta = 2 * MIN, client=None):
    coordinator = MetarDataUpdateCoordinator(
        hass, client or _StubMetarClient([]), "TEST", DEFAULT_SCAN_INTERVAL
    )
    coordinator._offset = offset
    return coordinator


def _next(coordinator, report: dict, now: datetime, history=None) -> timedelta:
    """Run the scheduler once at a given (frozen) time."""
    with freeze_time(now):
        return coordinator._compute_next_update_interval(report, history)


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


# --- the grid: exact intervals -------------------------------------------------


def test_half_hourly_station_next_fetch_on_grid(hass_with_domain):
    """History 09:00/09:30/10:00, lag 4 min -> cadence 30, margin 4, offset
    2: origin 10:00 + 4 + 2 = 10:06. At 10:07 the next point >= 10:12 is
    10:36, i.e. 29 minutes away."""
    c = _coordinator(hass_with_domain)
    history = _history(
        T0 - 60 * MIN, T0 - 30 * MIN, T0
    )
    delay = _next(
        c, _report(T0, receipt_time=T0 + 4 * MIN), T0 + 7 * MIN, history
    )
    assert delay == timedelta(minutes=29)
    assert c._learned_cadence() == timedelta(minutes=30)
    assert c._learned_margin() == timedelta(minutes=4)


def test_hourly_station_keeps_mid_cycle_check(hass_with_domain):
    """An hourly station is still polled every 30 minutes: step = 60 / 2.
    Lag 6 min, offset 2: origin 10:00 + 8 = 10:08; at 10:08 the next grid
    point is 10:38 (30 min), and the mid-cycle fetch with the unchanged
    10:00 report - not late, its slot is 11:06 - waits for 11:08 instead of
    burning stale retries."""
    c = _coordinator(hass_with_domain)
    history = _history(T0 - 120 * MIN, T0 - 60 * MIN, T0, lag=6 * MIN)
    report = _report(T0, receipt_time=T0 + 6 * MIN)
    assert c._learned_cadence() == timedelta(0) + DEFAULT_SCAN_INTERVAL  # not yet learned
    first = _next(c, report, T0 + 8 * MIN, history)
    assert c._learned_cadence() == timedelta(minutes=60)
    assert first == timedelta(minutes=30)

    second = _next(c, report, T0 + 38 * MIN, history)
    assert second == timedelta(minutes=30)  # 10:38 -> 11:08
    assert c._stale_retry_count == 0


def test_twenty_minute_station_keeps_its_own_step(hass_with_domain):
    """cadence 20 -> parts = ceil(20/30) = 1, step 20. Origin 10:00 + 4 + 2;
    at 10:06 the next point >= 10:11 is 10:26."""
    c = _coordinator(hass_with_domain)
    history = _history(T0 - 40 * MIN, T0 - 20 * MIN, T0)
    delay = _next(c, _report(T0, receipt_time=T0 + 4 * MIN), T0 + 6 * MIN, history)
    assert c._learned_cadence() == timedelta(minutes=20)
    assert delay == timedelta(minutes=20)


def test_speci_does_not_shift_the_routine_origin(hass_with_domain):
    """A SPECI at 10:20, fetched at 10:21, anchors on the 10:00 METAR: origin
    10:06, floor 10:26 -> 10:36 (15 min), not a SPECI-offset 10:50."""
    c = _coordinator(hass_with_domain)
    history = _history(T0 - 30 * MIN, T0)
    _next(c, _report(T0, receipt_time=T0 + 4 * MIN), T0 + 7 * MIN, history)

    speci = _report(T0 + 20 * MIN, metar_type="SPECI")
    delay = _next(c, speci, T0 + 21 * MIN, history)
    assert delay == timedelta(minutes=15)
    assert c._last_metar_time == T0


def test_restart_with_a_fresh_report_is_on_grid_immediately(hass_with_domain):
    """No stored state: the first fetch already carries two hours of
    history, so cadence and margin are known at once (no cold start)."""
    c = _coordinator(hass_with_domain)
    history = _history(T0 - 90 * MIN, T0 - 60 * MIN, T0 - 30 * MIN, T0)
    delay = _next(c, _report(T0, receipt_time=T0 + 4 * MIN), T0 + 20 * MIN, history)
    # origin 10:06, floor 10:25 -> 10:36
    assert delay == timedelta(minutes=16)


# --- late reports, exhaustion, silent stations --------------------------------


def test_retry_chain_then_exhaustion_lands_on_the_grid(hass_with_domain):
    """10:30 report is late: fetch at 10:36 sees the 10:00 report again
    (slot 10:34) -> retries of 3 and 3 minutes, then exhaustion. At 10:42
    the next grid point >= 10:47 is 11:06 -> 24 minutes."""
    c = _coordinator(hass_with_domain)
    history = _history(T0 - 30 * MIN, T0)
    report = _report(T0, receipt_time=T0 + 4 * MIN)
    assert _next(c, report, T0 + 7 * MIN, history) == timedelta(minutes=29)

    assert _next(c, report, T0 + 36 * MIN, history) == timedelta(minutes=3)
    assert _next(c, report, T0 + 39 * MIN, history) == timedelta(minutes=3)
    assert _next(c, report, T0 + 42 * MIN, history) == timedelta(minutes=24)
    assert c._exhausted_cycles == 1


@pytest.mark.parametrize(
    "offset, exhaustion_delay, silent_delay",
    [
        # exhaustion at 10:42: base 10:04 -> floor 10:47 -> k=2 -> 11:04
        # silent at 14:00: base 10:04 -> floor 14:05 -> k=9 -> 14:34
        (timedelta(0), timedelta(minutes=22), timedelta(minutes=34)),
        # base 10:06 -> 11:06 (24); base 10:06 -> k=8 -> 14:06 (6)
        (2 * MIN, timedelta(minutes=24), timedelta(minutes=6)),
        # base 10:12 -> floor 10:47 -> k=2 -> 11:12 (30); k=8 -> 14:12 (12)
        (8 * MIN, timedelta(minutes=30), timedelta(minutes=12)),
    ],
)
def test_offset_applies_in_exhaustion_and_silent_branches(
    hass_with_domain, offset, exhaustion_delay, silent_delay
):
    """Neither branch returns a bare now + 30 min: both target the
    station's grid plus the install's offset."""
    history = _history(T0 - 30 * MIN, T0)
    report = _report(T0, receipt_time=T0 + 4 * MIN)

    c = _coordinator(hass_with_domain, offset=offset)
    _next(c, report, T0 + 7 * MIN, history)
    _next(c, report, T0 + 36 * MIN, history)
    _next(c, report, T0 + 39 * MIN, history)
    assert _next(c, report, T0 + 42 * MIN, history) == exhaustion_delay

    silent = _coordinator(hass_with_domain, offset=offset)
    _next(silent, report, T0 + 7 * MIN, history)
    delay = _next(silent, report, T0 + 240 * MIN, history)
    assert delay == silent_delay
    assert silent._stale_retry_count == 0


def test_exhaustion_anchors_on_last_routine_metar_not_a_speci(hass_with_domain):
    """After retries run dry with a SPECI as the held report, the fallback
    must anchor on the routine METAR: 11:06, not a SPECI-derived point."""
    c = _coordinator(hass_with_domain)
    history = _history(T0 - 30 * MIN, T0)
    _next(c, _report(T0, receipt_time=T0 + 4 * MIN), T0 + 7 * MIN, history)
    speci = _report(T0 + 20 * MIN, metar_type="SPECI")
    _next(c, speci, T0 + 21 * MIN, history)
    # slot 10:34; retries from 10:36
    assert _next(c, speci, T0 + 36 * MIN, history) == timedelta(minutes=3)
    assert _next(c, speci, T0 + 39 * MIN, history) == timedelta(minutes=3)
    assert _next(c, speci, T0 + 42 * MIN, history) == timedelta(minutes=24)


# --- chronic lag ----------------------------------------------------------------


def test_chronic_lag_falls_back_to_flat_polling_and_recovers(hass_with_domain):
    """Lag 18 min (> margin cap 15): every cycle runs the retry chain dry.
    After three exhausted cycles in a row the station is polled flat (30 min)
    until a report is published within the margin again.

    Hand-computed per cycle (offset 2 min, margin capped at 15): origin
    10:00 -> base 10:17, slot 10:45; retries at 10:46 and 10:49, exhaustion
    at 10:52 -> floor 10:57 -> k=2 -> 11:17, i.e. 25 minutes. The same holds
    for every following cycle until the third one flips to flat polling."""
    c = _coordinator(hass_with_domain)
    lag = 18 * MIN
    cycle = 30 * MIN
    obs = T0
    history = _history(obs - cycle, obs, lag=lag)
    _next(c, _report(obs, receipt_time=obs + lag), obs + lag, history)

    exhausted = []
    for n in range(3):
        report = _report(obs, receipt_time=obs + lag)
        slot = obs + cycle + 15 * MIN
        assert _next(c, report, slot + 1 * MIN, history) == 3 * MIN
        assert _next(c, report, slot + 4 * MIN, history) == 3 * MIN
        exhausted.append(_next(c, report, slot + 7 * MIN, history))
        assert c._exhausted_cycles == n + 1
        # The late report finally shows up (first seen at the next grid point).
        obs = obs + cycle
        history = _history(obs - cycle, obs, lag=lag)
        new_delay = _next(c, _report(obs, receipt_time=obs + lag), obs + lag, history)
        if n == 2:
            assert new_delay == DEFAULT_SCAN_INTERVAL

    assert exhausted == [25 * MIN, 25 * MIN, DEFAULT_SCAN_INTERVAL]
    assert c._chronic_lag is True

    # A report published within the margin ends the flat mode: learned margin
    # is still 15 (p90 of the old lags), so origin + 17 min is the next point.
    obs = obs + cycle
    history = _history(obs - cycle, obs, lag=4 * MIN)
    delay = _next(c, _report(obs, receipt_time=obs + 4 * MIN), obs + 6 * MIN, history)
    assert c._chronic_lag is False
    assert c._exhausted_cycles == 0
    assert delay == 11 * MIN


def test_two_exhausted_cycles_in_a_row_do_not_trigger_flat_polling(hass_with_domain):
    c = _coordinator(hass_with_domain)
    history = _history(T0 - 30 * MIN, T0)
    report = _report(T0, receipt_time=T0 + 4 * MIN)
    _next(c, report, T0 + 7 * MIN, history)
    _next(c, report, T0 + 36 * MIN, history)
    _next(c, report, T0 + 39 * MIN, history)
    assert _next(c, report, T0 + 42 * MIN, history) == 24 * MIN
    assert c._exhausted_cycles == 1
    assert c._chronic_lag is False


def test_report_published_within_the_margin_resets_the_exhaustion_count(
    hass_with_domain,
):
    """The count is of *consecutive* exhausted cycles: one report published
    within the margin (AWC's own receiptTime) breaks the run, even when this
    install only noticed it at the grid fetch after the retries."""
    c = _coordinator(hass_with_domain)
    history = _history(T0 - 30 * MIN, T0)
    report = _report(T0, receipt_time=T0 + 4 * MIN)
    _next(c, report, T0 + 7 * MIN, history)
    _next(c, report, T0 + 36 * MIN, history)
    _next(c, report, T0 + 39 * MIN, history)
    _next(c, report, T0 + 42 * MIN, history)
    assert c._exhausted_cycles == 1

    t1 = T0 + 30 * MIN
    h1 = _history(T0 - 30 * MIN, T0, t1, lag=4 * MIN)
    _next(c, _report(t1, receipt_time=t1 + 4 * MIN), T0 + 66 * MIN, h1)
    assert c._exhausted_cycles == 0
    assert c._chronic_lag is False


# --- learning from AWC's own history -------------------------------------------


def test_lower_median_converges_back_to_half_hourly(hass_with_domain):
    """A station that missed one routine report once has a 60-minute delta
    in AWC's history; it must not lock the cadence at 60."""
    c = _coordinator(hass_with_domain)
    c._learn_routine_reports(_history(T0, T0 + 60 * MIN))
    assert c._learned_cadence() == timedelta(minutes=60)
    c._learn_routine_reports(_history(T0 + 90 * MIN, T0 + 120 * MIN))
    # deltas 60, 30, 30 -> lower median 30
    assert c._learned_cadence() == timedelta(minutes=30)
    # [30, 60] -> lower median 30, never the upper one
    d = _coordinator(hass_with_domain)
    d._learn_routine_reports(_history(T0, T0 + 30 * MIN, T0 + 90 * MIN))
    assert d._learned_cadence() == timedelta(minutes=30)


def test_late_fetch_cannot_poison_the_cadence(hass_with_domain):
    """LFLC, 14:05: AWC answers 504, AVWX serves the 14:00 METAR *untyped*;
    AWC is back at 14:34 with the 14:30 report. Learning from the response's
    history sees 13:30, 14:00, 14:30 -> cadence 30, never 60."""
    base = datetime(2026, 8, 23, 13, 30, tzinfo=timezone.utc)
    c = _coordinator(hass_with_domain)
    _next(c, _report(base, receipt_time=base + 4 * MIN), base + 6 * MIN,
          _history(base - 30 * MIN, base))
    avwx = _report(base + 30 * MIN, metar_type=None)
    _next(c, avwx, base + 35 * MIN, None)
    assert c._last_metar_time == base  # untyped report never moves the origin
    assert c._learned_cadence() == timedelta(minutes=30)

    full = _history(base, base + 30 * MIN, base + 60 * MIN)
    delay = _next(
        c, _report(base + 60 * MIN, receipt_time=base + 64 * MIN),
        base + 65 * MIN, full,
    )
    assert c._learned_cadence() == timedelta(minutes=30)
    # origin 14:30 + margin 4 + offset 2 = 14:36; floor 14:40 -> 15:06
    assert delay == timedelta(minutes=31)


def test_untyped_report_never_learns_anything(hass_with_domain):
    c = _coordinator(hass_with_domain)
    for n in range(4):
        obs = T0 + n * 30 * MIN
        _next(c, _report(obs, metar_type=None), obs + 6 * MIN, None)
    assert c._routine_log == {}
    assert c._last_metar_time is None
    assert c._learned_cadence() == DEFAULT_SCAN_INTERVAL


def test_same_cycle_cor_is_one_routine_entry(hass_with_domain):
    """A COR shares its original's observation time: one entry, no zero
    delta, and the first publication's lag wins."""
    c = _coordinator(hass_with_domain)
    entries = [(T0, T0 + 4 * MIN), (T0 + 30 * MIN, T0 + 33 * MIN)]
    c._learn_routine_reports(entries + [(T0 + 30 * MIN, T0 + 41 * MIN)])
    assert sorted(c._routine_log) == [T0, T0 + 30 * MIN]
    assert c._routine_log[T0 + 30 * MIN] == 3 * MIN
    assert c._learned_cadence() == timedelta(minutes=30)


def test_margin_is_a_real_p90_of_the_publication_lags(hass_with_domain):
    """Eight lags of 2 min, then 10 and 12: nearest-rank p90 of ten samples
    is the ninth value - not the median (2) and not the maximum (12)."""
    c = _coordinator(hass_with_domain)
    lags = [2] * 8 + [10, 12]
    c._learn_routine_reports(
        [(T0 + n * 30 * MIN, T0 + n * 30 * MIN + lag * MIN) for n, lag in enumerate(lags)]
    )
    assert c._learned_margin() == timedelta(minutes=10)


def test_margin_clamped_to_configured_bounds(hass_with_domain):
    low = _coordinator(hass_with_domain)
    low._learn_routine_reports(_history(T0, T0 + 30 * MIN, lag=timedelta(seconds=10)))
    assert low._learned_margin() == ADAPTIVE_MARGIN_MIN

    high = _coordinator(hass_with_domain)
    high._learn_routine_reports(_history(T0, T0 + 30 * MIN, lag=25 * MIN))
    assert high._learned_margin() == ADAPTIVE_MARGIN_MAX

    skewed = _coordinator(hass_with_domain)
    skewed._learn_routine_reports(
        [(T0, T0 - 5 * MIN), (T0 + 30 * MIN, T0 + 400 * MIN)]
    )
    assert skewed._learned_margin() == timedelta(minutes=5)  # no usable lag


def test_history_is_bounded(hass_with_domain):
    c = _coordinator(hass_with_domain)
    c._learn_routine_reports(_history(*[T0 + n * 30 * MIN for n in range(60)]))
    assert len(c._routine_log) == 24
    assert c._last_metar_time == T0 + 59 * 30 * MIN


# --- the per-install offset --------------------------------------------------------


def _coordinator_for(hass, entry_id: str, station: str = "TEST"):
    entry = SimpleNamespace(entry_id=entry_id)
    return MetarDataUpdateCoordinator(
        hass, _StubMetarClient([]), station, DEFAULT_SCAN_INTERVAL,
        config_entry=entry,
    )


def test_offset_is_stable_per_entry_and_spread_over_installs(hass_with_domain):
    offsets = [
        _coordinator_for(hass_with_domain, f"entry-{n}")._offset for n in range(1000)
    ]
    again = [
        _coordinator_for(hass_with_domain, f"entry-{n}")._offset for n in range(1000)
    ]
    assert offsets == again  # deterministic, survives restarts
    seconds = sorted(int(o.total_seconds()) for o in offsets)
    assert 0 <= seconds[0] and seconds[-1] < ADAPTIVE_OFFSET_SPAN_SECONDS
    assert seconds[500] > 180  # median well inside the 0-8 min span
    assert seconds[900] > 360  # p90 stays wide
    assert len(set(seconds)) > 350


def test_offset_differs_between_stations_of_one_entry(hass_with_domain):
    a = _coordinator_for(hass_with_domain, "entry-1", "KJFK")._offset
    b = _coordinator_for(hass_with_domain, "entry-1", "EGLL")._offset
    assert a != b


def test_offsets_stay_spread_over_48_hours_of_an_hourly_station(
    hass_with_domain, monkeypatch
):
    """The regression the stable offset exists for: with a per-cycle random
    jitter and a ceiling shorter than the interval the spread collapses to
    zero within hours. 80 installs follow an hourly station for 48 h; the
    spread of their fetch times inside the cycle must survive."""
    clock = [T0]
    monkeypatch.setattr(dt_util, "utcnow", lambda: clock[0])
    lag = 5 * MIN
    installs = [_coordinator_for(hass_with_domain, f"entry-{n}") for n in range(80)]
    next_fetch = {c: T0 + lag for c in installs}
    last_phase = {}
    end = T0 + timedelta(hours=48)
    while True:
        c = min(next_fetch, key=next_fetch.get)
        now = next_fetch[c]
        if now >= end:
            break
        clock[0] = now
        hour = now.replace(minute=0, second=0, microsecond=0)
        newest = hour if now - hour >= lag else hour - 60 * MIN
        history = _history(*[newest - n * 60 * MIN for n in (3, 2, 1, 0)], lag=lag)
        delay = c._compute_next_update_interval(
            _report(newest, receipt_time=newest + lag), history
        )
        assert delay >= ADAPTIVE_MIN_INTERVAL
        assert delay <= ADAPTIVE_MAX_INTERVAL + ADAPTIVE_MIN_INTERVAL
        next_fetch[c] = now + delay
        last_phase[c] = (now - hour).total_seconds() % 1800
    phases = sorted(last_phase.values())
    assert phases[int(len(phases) * 0.9)] - phases[0] > 5 * 60


# --- AWC field extraction against a fixture ---------------------------------------

AWC_HISTORY_FIXTURE = [
    {  # newest routine report (AWC lists by receipt time)
        "icaoId": "KJFK", "metarType": "METAR",
        "obsTime": 1781053200, "receiptTime": 1781053380,
    },
    {  # a SPECI in between: never a routine sample
        "icaoId": "KJFK", "metarType": "SPECI",
        "obsTime": 1781052300, "receiptTime": 1781052360,
    },
    {  # earlier routine report, ISO time strings
        "icaoId": "KJFK", "metarType": "METAR",
        "obsTime": "2026-06-10T00:30:00Z", "receiptTime": "2026-06-10T00:32:00Z",
    },
    {  # COR of the newest cycle, received later: first publication wins
        "icaoId": "KJFK", "metarType": "METAR",
        "obsTime": 1781053200, "receiptTime": 1781053500,
    },
    {"icaoId": "KJFK", "obsTime": 1781049600},  # untyped: skipped
    {"icaoId": "KJFK", "metarType": "METAR"},  # no obsTime: skipped
]


def test_extract_routine_history_from_fixture():
    history = AWCApiClient.extract_routine_history(AWC_HISTORY_FIXTURE)
    assert history == [
        (
            datetime(2026, 6, 10, 0, 30, tzinfo=timezone.utc),
            datetime(2026, 6, 10, 0, 32, tzinfo=timezone.utc),
        ),
        (
            datetime.fromtimestamp(1781053200, tz=timezone.utc),
            datetime.fromtimestamp(1781053380, tz=timezone.utc),
        ),
    ]


def test_parse_awc_response_carries_type_and_receipt_time():
    parsed = AWCApiClient.parse_awc_response(
        {
            "icaoId": "KJFK", "name": "New York", "rawOb": "METAR KJFK 100100Z 00000KT 10SM CLR 12/08 A3012",
            "obsTime": 1781053200, "receiptTime": 1781053380, "metarType": "speci",
            "temp": 12, "dewp": 8,
        }
    )
    assert parsed["metar_type"] == "SPECI"
    assert parsed["receipt_time"] == datetime.fromtimestamp(
        1781053380, tz=timezone.utc
    ).isoformat()


async def test_fetch_single_metar_records_routine_history(hass_with_domain, monkeypatch):
    client = AWCApiClient(hass_with_domain)
    monkeypatch.setattr(client, "fetch_metar", AsyncMock(return_value=AWC_HISTORY_FIXTURE))
    newest = await client.fetch_single_metar("KJFK")
    assert newest["obsTime"] == 1781053200
    assert len(client.last_routine_history) == 2


# --- a failed update resets the interval --------------------------------------


async def test_update_failed_resets_interval_to_default(hass_with_domain, monkeypatch):
    """A learned long interval (e.g. an hourly station) must not postpone
    recovery after a failed fetch by as much as the learned cadence."""
    real_sleep = asyncio.sleep

    async def _fast_sleep(delay, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    t1 = T0 + timedelta(hours=1)
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain,
        _StubMetarClient(
            [
                (_report(t1, receipt_time=t1 + 4 * MIN), _history(T0, t1)),
                *([RuntimeError("boom")] * 10),  # exhausts RETRY_INTERVALS
            ]
        ),
        "TEST",
        DEFAULT_SCAN_INTERVAL,
    )
    coordinator._offset = 2 * MIN
    with freeze_time(t1 + 6 * MIN):
        await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(minutes=30)
    coordinator.update_interval = timedelta(minutes=59)  # a learned long wait

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.update_interval == DEFAULT_SCAN_INTERVAL


async def test_scheduling_error_is_not_retried_as_a_fetch_failure(
    hass_with_domain, monkeypatch
):
    """An exception in the scheduler keeps the fresh data, falls back to the
    default interval and does not re-fetch (retries sleep up to 17 s)."""
    client = _StubMetarClient([_report(T0, receipt_time=T0 + 4 * MIN)])
    coordinator = MetarDataUpdateCoordinator(
        hass_with_domain, client, "TEST", DEFAULT_SCAN_INTERVAL
    )

    def _boom(*args, **kwargs):
        raise ValueError("scheduler bug")

    monkeypatch.setattr(coordinator, "_compute_next_update_interval", _boom)
    data = await coordinator._async_update_data()
    assert data["observation_time"] == T0.isoformat()
    assert client.calls == 1
    assert coordinator.update_interval == DEFAULT_SCAN_INTERVAL


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
    update_interval - because the config entry is handed to the coordinator
    explicitly (core would otherwise pick it up from a ContextVar)."""
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
    # picked (a fetch is never more than ADAPTIVE_MAX_INTERVAL + ADAPTIVE_MIN_INTERVAL away); if polling were still
    # active, this would trigger at least one more coordinator refresh.
    future = (
        dt_util.utcnow()
        + ADAPTIVE_MAX_INTERVAL
        + ADAPTIVE_MIN_INTERVAL
        + timedelta(minutes=5)
    )
    with freeze_time(future):
        async_fire_time_changed(hass, future)
        await hass.async_block_till_done()

    assert call_count == 0

    await _teardown(hass, entry)



async def test_polling_disabled_also_disables_taf_polling(hass, aioclient_mock):
    """The per-entry polling toggle must cover the TAF coordinator too."""
    entry = await _setup_lflc(hass, aioclient_mock, pref_disable_polling=True)
    taf_coordinator = hass.data[DOMAIN]["taf"][entry.entry_id]["LFLC"]
    assert taf_coordinator.config_entry is entry

    await _teardown(hass, entry)

