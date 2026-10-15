"""
The METAR Weather integration.

@license: MIT
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import asyncio
import random
import re
from asyncio import timeout as async_timeout
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Final

import voluptuous as vol

from homeassistant.util import dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
)
from homeassistant.const import Platform
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.exceptions import ServiceValidationError

from .api_client import MetarApiClient
from .taf_client import AWCTafApiClient, AWCTafApiError
from .storage import MetarHistoryStorage
from .const import (
    DOMAIN,
    CONF_STATIONS,
    CONF_TEMP_UNIT,
    CONF_WIND_SPEED_UNIT,
    CONF_VISIBILITY_UNIT,
    CONF_PRESSURE_UNIT,
    CONF_ALTITUDE_UNIT,
    UNIT_AUTO,
    DEFAULT_WIND_SPEED_UNIT,
    DEFAULT_ALTITUDE_UNIT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TAF_SCAN_INTERVAL,
    FUTURE_OBSERVATION_TOLERANCE,
    RETRY_INTERVALS,
    ADAPTIVE_INTERVAL_MARGIN,
    ADAPTIVE_MARGIN_MIN,
    ADAPTIVE_MARGIN_MAX,
    ADAPTIVE_JITTER_SECONDS,
    ADAPTIVE_MIN_INTERVAL,
    ADAPTIVE_MAX_INTERVAL,
    ADAPTIVE_LEARNED_INTERVAL_SAMPLES,
    ADAPTIVE_DELTA_MIN,
    ADAPTIVE_DELTA_MAX,
    OBS_STALE_RETRY_INTERVALS,
    ICAO_REGEX,
)

# hass.data[DOMAIN] keys that are not a {station: coordinator} map for a
# METAR config entry - both the update_station/clear_history services below
# and async_unload_entry's "any entries left?" check must skip these.
_NON_ENTRY_DATA_KEYS: Final[frozenset[str]] = frozenset({"storage", "taf"})

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the METAR Weather component."""
    hass.data.setdefault(DOMAIN, {})

    try:
        async with async_timeout(30):
            storage = MetarHistoryStorage(hass)
            await storage.async_load()
            hass.data[DOMAIN]["storage"] = storage
            _LOGGER.debug("Storage initialized successfully.")
    except asyncio.CancelledError:
        raise  # Don't suppress task cancellation
    except Exception as err:
        _LOGGER.error("Failed to initialize storage: %s", err)
        return False

    _async_register_services(hass)

    return True


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent).

    Called from both async_setup and async_setup_entry: an options-flow
    change reloads the entry, and unloading the last entry removes the
    services - but async_setup does not run again on reload, so entry setup
    must be able to bring them back.
    """
    async def async_update_station(call: ServiceCall) -> None:
        """Handle forced update service call."""
        station = call.data["station"].upper()

        # Validate ICAO format
        if not re.match(ICAO_REGEX, station):
            raise ServiceValidationError(
                f"Invalid ICAO code format: {station}",
                translation_domain=DOMAIN,
                translation_key="invalid_icao_format",
                translation_placeholders={"station": station},
            )

        # Search for the station across all config entries
        # Use list() to prevent RuntimeError if dict changes during iteration
        for entry_id, entry_data in list(hass.data[DOMAIN].items()):
            if entry_id in _NON_ENTRY_DATA_KEYS:
                continue
            if isinstance(entry_data, dict):
                coordinator = entry_data.get(station)
                if coordinator:
                    await coordinator.async_request_refresh()
                    # Refresh the station's TAF as well - "update this
                    # station" means all of its data, not just METAR.
                    taf_coordinator = (
                        hass.data[DOMAIN].get("taf", {}).get(entry_id, {}).get(station)
                    )
                    if taf_coordinator:
                        await taf_coordinator.async_request_refresh()
                    _LOGGER.info("Forced update for station %s completed", station)
                    return

        raise ServiceValidationError(
            f"Station {station} not found in any config entry",
            translation_domain=DOMAIN,
            translation_key="station_not_found",
            translation_placeholders={"station": station},
        )

    async def async_clear_history(call: ServiceCall) -> None:
        """Handle clear history service call."""
        station = call.data["station"].upper()

        # Validate ICAO format
        if not re.match(ICAO_REGEX, station):
            raise ServiceValidationError(
                f"Invalid ICAO code format: {station}",
                translation_domain=DOMAIN,
                translation_key="invalid_icao_format",
                translation_placeholders={"station": station},
            )

        storage: MetarHistoryStorage = hass.data[DOMAIN].get("storage")

        if not storage:
            raise ServiceValidationError(
                "Storage not initialized",
                translation_domain=DOMAIN,
                translation_key="storage_not_initialized",
                translation_placeholders={},
            )

        # Check if station exists in any config entry
        # Use list() to prevent RuntimeError if dict changes during iteration
        station_found = False
        for entry_id, entry_data in list(hass.data[DOMAIN].items()):
            if entry_id in _NON_ENTRY_DATA_KEYS:
                continue
            if isinstance(entry_data, dict) and station in entry_data:
                station_found = True
                break

        if station_found:
            try:
                async with async_timeout(10):
                    await storage.async_clear_station(station)
                    _LOGGER.info("Cleared history for station %s", station)
            except asyncio.CancelledError:
                raise  # Don't suppress task cancellation
            except asyncio.TimeoutError:
                # Timeout is a real error - inform the user via exception
                _LOGGER.error("Timeout clearing history for %s", station)
                raise ServiceValidationError(
                    f"Timeout clearing history for {station}",
                    translation_domain=DOMAIN,
                    translation_key="clear_history_timeout",
                    translation_placeholders={"station": station},
                )
            except Exception as err:
                # Storage errors should be reported to the user
                _LOGGER.error("Error clearing history for %s: %s", station, err)
                raise ServiceValidationError(
                    f"Failed to clear history for {station}: {err}",
                    translation_domain=DOMAIN,
                    translation_key="clear_history_failed",
                    translation_placeholders={"station": station, "error": str(err)},
                )
        else:
            raise ServiceValidationError(
                f"Station {station} is not configured",
                translation_domain=DOMAIN,
                translation_key="station_not_configured",
                translation_placeholders={"station": station},
            )

    # Only register services if not already registered
    if not hass.services.has_service(DOMAIN, "update_station"):
        hass.services.async_register(
            DOMAIN,
            "update_station",
            async_update_station,
            schema=vol.Schema({
                vol.Required("station"): str,
            })
        )

    if not hass.services.has_service(DOMAIN, "clear_history"):
        hass.services.async_register(
            DOMAIN,
            "clear_history",
            async_clear_history,
            schema=vol.Schema({
                vol.Required("station"): str,
            })
        )


class MetarDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching METAR data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MetarApiClient,
        station: str,
        update_interval: timedelta,
        config_entry: ConfigEntry | None = None,
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{station}",
            update_interval=update_interval,
        )
        self.client = client
        self.station = station
        self._retry_count = 0
        self._consecutive_failures = 0
        self._accepted_source: str | None = None
        self._interval_samples: deque[timedelta] = deque(
            maxlen=ADAPTIVE_LEARNED_INTERVAL_SAMPLES
        )
        self._margin_samples: deque[timedelta] = deque(
            maxlen=ADAPTIVE_LEARNED_INTERVAL_SAMPLES
        )
        # Last observation_time seen from any report (METAR or SPECI) -
        # drives the "is this actually new data" / retry-backoff check and
        # the anchor point for the next scheduled fetch.
        self._last_observation_time: datetime | None = None
        # Last observation_time specifically from a METAR (not a SPECI) -
        # the only thing cadence learning (_interval_samples) is allowed to
        # diff against, so an off-grid SPECI never drags the learned median
        # off the station's real routine rhythm.
        self._last_metar_time: datetime | None = None
        self._stale_retry_count = 0

    @property
    def accepted_source(self) -> str | None:
        """Source of the data currently held.

        ``client.last_source`` names the source of the *last fetch*, which
        may have been rejected as stale; this names the source whose data
        the sensors actually display.
        """
        return self._accepted_source

    def _reject_stale_observation(self, fetched: dict) -> dict:
        """Keep the held data when a fetch yields an older observation.

        A source can serve a report for an already-superseded cycle - a
        re-filed COR of an old observation, or a lagging mirror (issue #16).
        Observation time only moves forward, so a strictly older report is a
        correction to history, never the current weather. A report with the
        *same* observation time passes through: a COR of the current cycle
        must update the values. Covers both the AWC and the AVWX path.
        """
        held = self.data
        if not held:
            return fetched
        held_time = dt_util.parse_datetime(held.get("observation_time") or "")
        fetched_time = dt_util.parse_datetime(
            fetched.get("observation_time") or ""
        )
        if held_time is None or fetched_time is None:
            return fetched
        if held_time.tzinfo is None:
            held_time = held_time.replace(tzinfo=timezone.utc)
        if fetched_time.tzinfo is None:
            fetched_time = fetched_time.replace(tzinfo=timezone.utc)
        if held_time > dt_util.utcnow() + FUTURE_OBSERVATION_TOLERANCE:
            # A future-dated report (mis-keyed DDHHMM group) must not become
            # a high-water mark that rejects genuine reports until the clock
            # catches up. Only reachable via the AVWX path or when a future
            # report was the sole candidate; take the fetched report.
            _LOGGER.warning(
                "Held observation time %s for %s is implausibly in the "
                "future; accepting the fetched report",
                held_time.isoformat(),
                self.station,
            )
            return fetched
        if fetched_time < held_time:
            _LOGGER.warning(
                "Ignoring stale report for %s: observation time %s is older "
                "than the held %s; keeping current data",
                self.station,
                fetched_time.isoformat(),
                held_time.isoformat(),
            )
            return held
        return fetched

    def _learned_interval_raw(self) -> timedelta:
        """Station's typical native reporting cadence, no margin.

        Median of the observed METAR-to-METAR deltas (deque of the last
        ADAPTIVE_LEARNED_INTERVAL_SAMPLES), smoothing over a single late/
        early outlier. Falls back to DEFAULT_SCAN_INTERVAL until enough
        history exists to trust a median.
        """
        if len(self._interval_samples) < 2:
            return DEFAULT_SCAN_INTERVAL
        samples = sorted(self._interval_samples)
        return samples[len(samples) // 2]

    def _learned_margin(self) -> timedelta:
        """The station's real publication lag, learned from receiptTime.

        p90 of the observed (receiptTime - obsTime) samples, clamped to
        [ADAPTIVE_MARGIN_MIN, ADAPTIVE_MARGIN_MAX]. Falls back to the fixed
        ADAPTIVE_INTERVAL_MARGIN until at least one sample exists - which,
        on the AVWX path (no receiptTime there), is always.
        """
        if not self._margin_samples:
            return ADAPTIVE_INTERVAL_MARGIN
        samples = sorted(self._margin_samples)
        index = max(0, min(len(samples) - 1, int(len(samples) * 0.9)))
        p90 = samples[index]
        return max(ADAPTIVE_MARGIN_MIN, min(p90, ADAPTIVE_MARGIN_MAX))

    def _learned_interval(self) -> timedelta:
        """Scheduling interval: native cadence plus the learned publish-delay margin."""
        return self._learned_interval_raw() + self._learned_margin()

    def _record_margin_sample(self, data: dict, obs_time: datetime) -> None:
        """Track a station's real publication lag (receiptTime - obsTime).

        No-op whenever receipt_time is absent (always true on the AVWX
        path), which is exactly what leaves _learned_margin() on the fixed
        fallback for that path.
        """
        receipt_time = dt_util.parse_datetime(data.get("receipt_time") or "")
        if receipt_time is None:
            return
        if receipt_time.tzinfo is None:
            receipt_time = receipt_time.replace(tzinfo=timezone.utc)
        lag = receipt_time - obs_time
        if timedelta(0) <= lag <= ADAPTIVE_MARGIN_MAX * 2:
            # Sanity bound: a negative or wildly large lag is a clock skew
            # or parsing anomaly, not a real publication delay.
            self._margin_samples.append(lag)

    def _compute_next_update_interval(self, data: dict) -> timedelta:
        """Schedule the next fetch from this station's own cadence.

        Replaces the flat DEFAULT_SCAN_INTERVAL with a per-station learned
        rhythm: after a new observation, wait until shortly after the next
        one is expected (obs_time + learned interval + jitter). If the
        expected observation hasn't shown up yet (observation_time
        unchanged from the previous fetch), retry after a short, bounded
        backoff (OBS_STALE_RETRY_INTERVALS). Once those retries are
        exhausted, anchor to the station's *next* native release slot
        instead of drifting from "now" - capped at DEFAULT_SCAN_INTERVAL so
        a station whose publication lag runs long still gets checked within
        one normal cycle rather than a whole missed one.

        Cadence and margin are learned only from METAR-to-METAR deltas and
        AWC's receiptTime: AWC serves SPECIs in the same feed, and an
        off-grid SPECI (or a same-cycle COR, which yields a zero delta)
        would otherwise drag the learned median off the station's real
        routine rhythm.
        """
        obs_time = dt_util.parse_datetime(data.get("observation_time") or "")
        if obs_time is None:
            # Can't reason about cadence without an observation time -
            # keep the fixed default rather than guessing.
            self._stale_retry_count = 0
            return DEFAULT_SCAN_INTERVAL

        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)

        now = dt_util.utcnow()

        if (
            self._last_observation_time is not None
            and obs_time == self._last_observation_time
        ):
            # Same report as last time - the next one hasn't been
            # published yet.
            #
            # The next routine report is due at the last routine METAR plus
            # the learned interval (a SPECI doesn't move the routine grid).
            # If that slot is still ahead of us (restart with a seeded
            # report, SPECI boost check, manual update), the report isn't
            # "late" - wait for the slot instead of burning retries.
            slot = (self._last_metar_time or obs_time) + self._learned_interval()
            if now < slot:
                jitter = timedelta(seconds=random.randint(*ADAPTIVE_JITTER_SECONDS))
                self._stale_retry_count = 0
                return max(
                    ADAPTIVE_MIN_INTERVAL,
                    min(slot + jitter - now, ADAPTIVE_MAX_INTERVAL),
                )
            # Overdue by more than the largest plausible publication lag:
            # the station is silent (or its feed is down). Short retries
            # would only hammer it, so go straight to the normal cycle.
            if now - slot > ADAPTIVE_MARGIN_MAX:
                self._stale_retry_count = 0
                return DEFAULT_SCAN_INTERVAL
            if self._stale_retry_count < len(OBS_STALE_RETRY_INTERVALS):
                delay = OBS_STALE_RETRY_INTERVALS[self._stale_retry_count]
                self._stale_retry_count += 1
                _LOGGER.debug(
                    "%s: observation unchanged, retrying in %s (attempt %d/%d)",
                    self.station,
                    delay,
                    self._stale_retry_count,
                    len(OBS_STALE_RETRY_INTERVALS),
                )
                return delay
            # Short retries exhausted - the expected report is unusually
            # late. Anchor to the station's *next* native release slot
            # instead of drifting from "now", but cap the wait at
            # DEFAULT_SCAN_INTERVAL: the anchor alone would leave a station
            # whose publication lag exceeds margin + one retry cycle
            # without a check for a full learned cycle, worse than today's
            # flat-interval behavior.
            self._stale_retry_count = 0
            raw_interval = self._learned_interval_raw()
            fallback_target = obs_time + raw_interval + self._learned_interval()
            anchor_delay = fallback_target - now
            if anchor_delay < ADAPTIVE_MIN_INTERVAL:
                # Slot already in the past: a 5-minute clamp would just
                # restart the retry chain; use the normal cycle instead.
                delay = DEFAULT_SCAN_INTERVAL
            else:
                delay = min(anchor_delay, DEFAULT_SCAN_INTERVAL)
            _LOGGER.debug(
                "%s: observation still unchanged after %d retries, "
                "anchoring to next native release slot at %s (capped at %s)",
                self.station,
                len(OBS_STALE_RETRY_INTERVALS),
                fallback_target.isoformat(),
                DEFAULT_SCAN_INTERVAL,
            )
            return max(ADAPTIVE_MIN_INTERVAL, min(delay, ADAPTIVE_MAX_INTERVAL))

        # New observation - schedule the next fetch relative to it
        # regardless of report type. Only a METAR feeds the learned
        # cadence/margin themselves; a SPECI still updates the sensors and
        # still anchors the *next* check, it just isn't trusted as a
        # sample of the station's routine rhythm.
        # Only an explicit "METAR" is trusted as a routine report. A SPECI
        # is off-grid; an untyped report (AVWX has no metarType) can't be
        # told apart from a SPECI, so it is never used as a cadence sample
        # (same rule as the storage seeding: never guess).
        report_type = (data.get("metar_type") or "").upper()
        is_metar = report_type == "METAR"
        is_speci = report_type == "SPECI"
        if is_metar:
            if self._last_metar_time is not None:
                delta = obs_time - self._last_metar_time
                if ADAPTIVE_DELTA_MIN <= delta <= ADAPTIVE_DELTA_MAX:
                    self._interval_samples.append(delta)
            self._last_metar_time = obs_time
            self._record_margin_sample(data, obs_time)

        self._last_observation_time = obs_time
        self._stale_retry_count = 0

        interval = self._learned_interval()
        jitter = timedelta(seconds=random.randint(*ADAPTIVE_JITTER_SECONDS))
        # A SPECI doesn't shift the routine release grid: keep anchoring on
        # the last routine METAR so the next routine report isn't fetched
        # a SPECI-offset late.
        anchor = obs_time
        if is_speci and self._last_metar_time is not None:
            anchor = self._last_metar_time
        target = anchor + interval + jitter
        delay = target - now
        return max(ADAPTIVE_MIN_INTERVAL, min(delay, ADAPTIVE_MAX_INTERVAL))

    async def async_seed_from_storage(self, storage) -> None:
        """Recover the learned cadence/margin from stored history at setup.

        MetarHistoryStorage keeps up to 24h of records carrying
        observation_time (and, from this version on, metar_type/
        receipt_time), so the adaptive schedule doesn't fall back to the
        flat default for the first two cycles after every restart. Records
        from before this field existed have no metar_type and are skipped
        outright, never guessed at. Best-effort: any failure here just
        means seeding didn't happen, not a setup failure.
        """
        if storage is None:
            return
        try:
            records = await storage.async_get_all_station_records(self.station)
        except Exception as err:
            _LOGGER.debug(
                "Could not seed cadence for %s from storage: %s", self.station, err
            )
            return

        metar_times: list[datetime] = []
        seen: set[datetime] = set()
        for record in records:
            if not isinstance(record, dict) or record.get("metar_type") != "METAR":
                continue
            obs = dt_util.parse_datetime(record.get("observation_time") or "")
            if obs is None:
                continue
            if obs.tzinfo is None:
                obs = obs.replace(tzinfo=timezone.utc)
            # History appends on every fetch, so the same report can be
            # stored repeatedly - count each observation once, or the
            # margin samples would be N copies of one publication delay.
            if obs in seen:
                continue
            seen.add(obs)
            metar_times.append(obs)

            receipt = dt_util.parse_datetime(record.get("receipt_time") or "")
            if receipt is not None:
                if receipt.tzinfo is None:
                    receipt = receipt.replace(tzinfo=timezone.utc)
                lag = receipt - obs
                if timedelta(0) <= lag <= ADAPTIVE_MARGIN_MAX * 2:
                    self._margin_samples.append(lag)

        metar_times.sort()
        for earlier, later in zip(metar_times, metar_times[1:]):
            delta = later - earlier
            if ADAPTIVE_DELTA_MIN <= delta <= ADAPTIVE_DELTA_MAX:
                self._interval_samples.append(delta)

        if metar_times:
            self._last_metar_time = metar_times[-1]
            self._last_observation_time = metar_times[-1]
            _LOGGER.debug(
                "%s: seeded cadence from storage - %d METAR samples, "
                "%d interval samples, %d margin samples",
                self.station,
                len(metar_times),
                len(self._interval_samples),
                len(self._margin_samples),
            )

    async def _async_update_data(self):
        """Fetch data from API with retry logic."""
        last_error = None
        attempts_made = 0

        # Try fetching with exponential backoff
        for attempt, delay in enumerate(RETRY_INTERVALS):
            attempts_made = attempt + 1
            try:
                data = await self.client.fetch_data()
                if data:
                    accepted = self._reject_stale_observation(data)
                    if accepted is data:
                        self._accepted_source = self.client.last_source
                    data = accepted
                    # Reset failure counter on success
                    self._consecutive_failures = 0
                    self._retry_count = 0

                    # Save to storage for historical data
                    storage = self.hass.data[DOMAIN].get("storage")
                    if storage:
                        try:
                            await storage.async_add_record(self.station, data)
                        except Exception as storage_err:
                            _LOGGER.warning(
                                "Failed to save history for %s: %s",
                                self.station,
                                storage_err
                            )
                    else:
                        _LOGGER.warning(
                            "Storage not initialized, historical data for %s will not be saved",
                            self.station
                        )

                    self.update_interval = self._compute_next_update_interval(data)
                    _LOGGER.debug("Updated data for %s: %s", self.station, data)
                    return data

                # No data but no error - API works but station has no data
                # Retrying won't help, so break early
                last_error = Exception(f"No data received for station {self.station}")
                break

            except Exception as err:
                last_error = err
                self._retry_count = attempt + 1
                _LOGGER.warning(
                    "Attempt %d/%d failed for %s: %s. Retrying in %ds...",
                    attempt + 1,
                    len(RETRY_INTERVALS),
                    self.station,
                    err,
                    delay
                )

                # Wait before retry (except on last attempt)
                if attempt < len(RETRY_INTERVALS) - 1:
                    await asyncio.sleep(delay)

        # All retries exhausted or early break
        self._consecutive_failures += 1
        # Core reschedules from update_interval after a failed refresh too
        # (_schedule_refresh runs regardless of outcome), so a long learned
        # interval left in place here would postpone recovery by as much -
        # an hour, for an hourly station - instead of the usual 30 minutes.
        self.update_interval = DEFAULT_SCAN_INTERVAL
        _LOGGER.error(
            "Failed for %s after %d attempt(s). Consecutive failures: %d. Error: %s",
            self.station,
            attempts_made,
            self._consecutive_failures,
            last_error
        )
        raise UpdateFailed(f"Error fetching data after {attempts_made} attempt(s): {last_error}") from last_error


class TafDataUpdateCoordinator(DataUpdateCoordinator["dict[str, Any] | None"]):
    """Class to manage fetching TAF data.

    Deliberately simpler than MetarDataUpdateCoordinator: no
    retry-with-backoff (the METAR retry loop sleeps up to 17s, which is
    justified for the primary data but not for a forecast that refreshes
    hourly and self-heals on the next cycle), just a staleness guard on
    issue_time so a lagging fetch can't overwrite a newer TAF with an
    older one.

    data is None while the station has no current TAF (a successful fetch:
    smaller airports often don't issue TAFs). Sensor availability must
    therefore be coordinator-level only - see TafSensor.available.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: AWCTafApiClient,
        station: str,
        config_entry: ConfigEntry | None = None,
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{station}_taf",
            update_interval=DEFAULT_TAF_SCAN_INTERVAL,
        )
        self.client = client
        self.station = station

    def _reject_stale_taf(self, fetched: dict) -> dict:
        """Keep the held TAF when a fetch yields an older issue_time.

        Mirrors MetarDataUpdateCoordinator._reject_stale_observation, but
        compares issue_time: a TAF is valid until superseded by a newer
        issuance (scheduled or AMD), so an older issue_time is never the
        current forecast. issue_time is an aware datetime parsed by
        taf_client.parse_issue_time (None when unparseable, which simply
        skips the guard - fetched wins - rather than crashing).
        """
        held = self.data
        if not held:
            return fetched
        held_time = held.get("issue_time")
        fetched_time = fetched.get("issue_time")
        if not held_time or not fetched_time:
            return fetched
        if fetched_time < held_time:
            _LOGGER.warning(
                "Ignoring stale TAF for %s: issue time %s is older than "
                "the held %s; keeping current data",
                self.station,
                fetched_time,
                held_time,
            )
            return held
        return fetched

    async def _async_update_data(self):
        """Fetch the current TAF; a single attempt per refresh."""
        try:
            fetched = await self.client.fetch_taf(self.station)
        except AWCTafApiError as err:
            raise UpdateFailed(f"Error fetching TAF: {err}") from err

        if fetched is None:
            # Station simply has no current TAF - a valid, successful
            # result. The sensor shows "unknown", not "unavailable".
            _LOGGER.debug("No current TAF for %s", self.station)
            return None

        fetched = self._reject_stale_taf(fetched)
        _LOGGER.debug("Updated TAF for %s: %s", self.station, fetched)
        return fetched


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up METAR Weather from a config entry."""
    # Ensure storage is initialized (handles reload case where async_setup isn't called again)
    if "storage" not in hass.data.get(DOMAIN, {}):
        _LOGGER.debug("Storage not found, initializing (possible reload scenario)")
        hass.data.setdefault(DOMAIN, {})
        try:
            async with async_timeout(30):
                storage = MetarHistoryStorage(hass)
                await storage.async_load()
                hass.data[DOMAIN]["storage"] = storage
                _LOGGER.debug("Storage initialized in async_setup_entry")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.error("Failed to initialize storage in setup_entry: %s", err)
            # Continue without storage - sensors will work but no history

    # Unloading the last entry removes the services; an options-flow reload
    # re-enters here without re-running async_setup, so re-register.
    _async_register_services(hass)

    # Validate stations list exists and is not empty
    stations = entry.data.get(CONF_STATIONS, [])
    if not stations:
        _LOGGER.error("No stations configured for entry %s", entry.entry_id)
        return False

    coordinators: dict[str, MetarDataUpdateCoordinator] = {}

    for station in stations:
        station_upper = station.upper()
        try:
            client = MetarApiClient(hass, station_upper)

            coordinator = MetarDataUpdateCoordinator(
                hass,
                client,
                station_upper,
                DEFAULT_SCAN_INTERVAL,
                config_entry=entry,
            )

            # Recover the learned cadence/margin from stored history before
            # the first fetch, so adaptive polling doesn't start cold on
            # every restart.
            await coordinator.async_seed_from_storage(
                hass.data[DOMAIN].get("storage")
            )

            # This will fetch data once during setup
            await coordinator.async_config_entry_first_refresh()

            if not coordinator.data:
                _LOGGER.error("No initial data received for station %s", station_upper)
                continue

            coordinators[station_upper] = coordinator
            _LOGGER.debug(
                "Coordinator setup complete for %s with data: %s",
                station_upper,
                coordinator.data,
            )

        except Exception as err:
            _LOGGER.error("Error setting up station %s: %s", station_upper, err)
            continue

    if not coordinators:
        return False

    hass.data[DOMAIN][entry.entry_id] = coordinators

    # TAF coordinators live in a separate namespace (hass.data[DOMAIN]["taf"])
    # rather than mixed into `coordinators` above, so the existing
    # update_station/clear_history services and the METAR sensor setup keep
    # iterating a pure {station: MetarDataUpdateCoordinator} map unchanged.
    # Every METAR station gets a TAF coordinator unconditionally: a station
    # without a current TAF (common for smaller airports) keeps its entity
    # at "unknown" and picks the forecast up whenever one appears. The
    # first fetch runs as an entry-scoped background task so a slow or
    # failing TAF endpoint can't delay METAR setup; the coordinator's own
    # hourly schedule takes over once the sensor subscribes.
    taf_client = AWCTafApiClient(hass)
    taf_coordinators: dict[str, TafDataUpdateCoordinator] = {}
    for station_upper in coordinators:
        taf_coordinator = TafDataUpdateCoordinator(
            hass, taf_client, station_upper, config_entry=entry
        )
        taf_coordinators[station_upper] = taf_coordinator
        entry.async_create_background_task(
            hass,
            taf_coordinator.async_refresh(),
            name=f"{DOMAIN}_{station_upper}_taf_first_refresh",
        )

    hass.data[DOMAIN].setdefault("taf", {})[entry.entry_id] = taf_coordinators

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Uses Home Assistant's built-in reload mechanism for proper state management.
    """
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].get("taf", {}).pop(entry.entry_id, None)

        # Check if this was the last config entry (only bookkeeping keys remain)
        remaining_entries = [
            key for key in hass.data[DOMAIN].keys()
            if key not in _NON_ENTRY_DATA_KEYS
        ]

        if not remaining_entries:
            # Last entry unloaded - cleanup storage and unregister services
            _LOGGER.debug("Last config entry unloaded, cleaning up services and storage")

            # Unregister services
            if hass.services.has_service(DOMAIN, "update_station"):
                hass.services.async_remove(DOMAIN, "update_station")
            if hass.services.has_service(DOMAIN, "clear_history"):
                hass.services.async_remove(DOMAIN, "clear_history")

            # Cleanup storage (cancel pending debouncer) before removing
            storage = hass.data[DOMAIN].get("storage")
            if storage:
                await storage.async_cleanup()

            # Remove storage reference (storage object will be garbage collected)
            hass.data[DOMAIN].pop("storage", None)
            hass.data[DOMAIN].pop("taf", None)

            # Clear domain data entirely if empty
            if not hass.data[DOMAIN]:
                hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        new_data = {**config_entry.data}

        # Add default unit settings for v1 -> v2 migration
        new_data.setdefault(CONF_TEMP_UNIT, UNIT_AUTO)
        new_data.setdefault(CONF_WIND_SPEED_UNIT, DEFAULT_WIND_SPEED_UNIT)
        new_data.setdefault(CONF_VISIBILITY_UNIT, UNIT_AUTO)
        new_data.setdefault(CONF_PRESSURE_UNIT, UNIT_AUTO)
        new_data.setdefault(CONF_ALTITUDE_UNIT, DEFAULT_ALTITUDE_UNIT)

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=2
        )
        _LOGGER.info("Migration to version 2 successful")

    return True
