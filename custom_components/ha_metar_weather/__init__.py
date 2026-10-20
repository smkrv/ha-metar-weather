"""
The METAR Weather integration.

@license: MIT
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import asyncio
import math
import re
import zlib
from asyncio import timeout as async_timeout
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
    ADAPTIVE_OFFSET_SPAN_SECONDS,
    ADAPTIVE_HISTORY_SIZE,
    ADAPTIVE_CHRONIC_LAG_CYCLES,
    ADAPTIVE_MIN_INTERVAL,
    ADAPTIVE_MAX_INTERVAL,
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
        # Routine METARs the station published, learned from the history
        # inside each AWC response: observation time -> publication lag
        # (receiptTime - obsTime, None when unknown). Cadence and margin
        # are derived from this, never from our own polling, so a report
        # we fetched late cannot masquerade as the station's rhythm.
        self._routine_log: dict[datetime, timedelta | None] = {}
        # Last observation_time seen from any report (METAR or SPECI) -
        # drives the "is this actually new data" / retry-backoff check.
        self._last_observation_time: datetime | None = None
        # Newest routine METAR (not a SPECI): the origin of the polling grid.
        self._last_metar_time: datetime | None = None
        self._stale_retry_count = 0
        # Retry chains that ended without the report, in a row; at
        # ADAPTIVE_CHRONIC_LAG_CYCLES the station is polled flat until a
        # report is published within the margin again.
        self._exhausted_cycles = 0
        self._exhaust_pending = False
        self._chronic_lag = False
        # Stable per-install offset on the station's grid (see const.py).
        entry_id = str(getattr(config_entry, "entry_id", "") or "")
        self._offset = timedelta(
            seconds=zlib.crc32(f"{entry_id}:{station}".encode())
            % ADAPTIVE_OFFSET_SPAN_SECONDS
        )

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

    def _learned_cadence(self) -> timedelta:
        """Station's native reporting cadence, no margin.

        Lower median of the deltas between consecutive routine METARs the
        station published (15-90 min band; AWC's own history, so a report
        this install fetched late or skipped cannot distort it). The lower
        median errs towards the shorter cadence. Falls back to
        DEFAULT_SCAN_INTERVAL while no delta is known.
        """
        times = sorted(self._routine_log)
        deltas = sorted(
            later - earlier
            for earlier, later in zip(times, times[1:])
            if ADAPTIVE_DELTA_MIN <= later - earlier <= ADAPTIVE_DELTA_MAX
        )
        if not deltas:
            return DEFAULT_SCAN_INTERVAL
        return deltas[(len(deltas) - 1) // 2]

    def _learned_margin(self) -> timedelta:
        """Publication lag to wait after an observation: p90 of the known
        lags (nearest rank), clamped to [ADAPTIVE_MARGIN_MIN,
        ADAPTIVE_MARGIN_MAX]. ADAPTIVE_INTERVAL_MARGIN until one is known
        (always on the AVWX path, which has no receiptTime).
        """
        lags = sorted(lag for lag in self._routine_log.values() if lag is not None)
        if not lags:
            return ADAPTIVE_INTERVAL_MARGIN
        p90 = lags[max(0, math.ceil(len(lags) * 0.9) - 1)]
        return max(ADAPTIVE_MARGIN_MIN, min(p90, ADAPTIVE_MARGIN_MAX))

    def _learn_routine_reports(
        self, entries: list[tuple[datetime, datetime | None]]
    ) -> None:
        """Merge (obs_time, receipt_time) pairs of routine METARs."""
        for obs, receipt in entries:
            if obs.tzinfo is None:
                obs = obs.replace(tzinfo=timezone.utc)
            lag = None
            if receipt is not None:
                if receipt.tzinfo is None:
                    receipt = receipt.replace(tzinfo=timezone.utc)
                candidate = receipt - obs
                # A negative or wildly large lag is clock skew or a parsing
                # anomaly, not a real publication delay.
                if timedelta(0) <= candidate <= ADAPTIVE_MARGIN_MAX * 2:
                    lag = candidate
            if self._routine_log.get(obs) is None:
                self._routine_log[obs] = lag
        for stale in sorted(self._routine_log)[:-ADAPTIVE_HISTORY_SIZE]:
            del self._routine_log[stale]
        if self._routine_log:
            self._last_metar_time = max(self._routine_log)

    def _grid_delay(self, origin: datetime, now: datetime) -> timedelta:
        """Delay to the next point of the station's own polling grid.

        origin = last routine METAR + margin; step = cadence split into
        equal parts of at most ADAPTIVE_MAX_INTERVAL (30 -> 30, 60 -> 30,
        20 -> 20); target = origin + k * step + offset for the smallest k
        that lies at least ADAPTIVE_MIN_INTERVAL ahead. The offset goes on
        *after* the step, so it is never trimmed away.
        """
        cadence = self._learned_cadence()
        parts = max(1, math.ceil(cadence / ADAPTIVE_MAX_INTERVAL))
        step = cadence / parts
        base = origin + self._learned_margin() + self._offset
        floor = now + ADAPTIVE_MIN_INTERVAL
        k = 0 if base >= floor else -((base - floor) // step)
        return base + k * step - now

    def _compute_next_update_interval(
        self,
        data: dict,
        history: list[tuple[datetime, datetime | None]] | None = None,
    ) -> timedelta:
        """Schedule the next fetch on the station's own polling grid.

        The station is polled at least every DEFAULT_SCAN_INTERVAL; the
        grid only shifts the phase of that cycle so a fetch lands just
        after publication (an hourly station keeps a mid-cycle check, so a
        SPECI is not superseded unseen). Every branch - new report, slot
        still ahead, silent station, retry exhaustion - targets a point of
        that grid plus the install's stable offset, so installs stay spread.
        Short stale retries (OBS_STALE_RETRY_INTERVALS) bridge a report
        that is a little late; after ADAPTIVE_CHRONIC_LAG_CYCLES exhausted
        chains in a row the station is polled flat until a report is
        published within the margin again.

        Cadence and lag come from ``history`` - the routine METARs inside
        the AWC response - and a typed METAR in ``data``. An untyped report
        (AVWX) never feeds them, and never moves the grid origin.
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

        entries = list(history or [])
        report_type = (data.get("metar_type") or "").upper()
        receipt = dt_util.parse_datetime(data.get("receipt_time") or "")
        if report_type == "METAR":
            entries.append((obs_time, receipt))
        self._learn_routine_reports(entries)
        # A SPECI or untyped report never moves the origin.
        origin = self._last_metar_time or obs_time

        if (
            self._last_observation_time is not None
            and obs_time == self._last_observation_time
        ):
            # Same report as last time - the next one hasn't been
            # published yet. If its slot is still ahead of us (restart,
            # mid-cycle check of an hourly station, manual update) the
            # report isn't late; if it is overdue by more than the largest
            # plausible lag the station is silent (or its feed is down).
            # Both wait for the next grid point instead of burning retries.
            slot = origin + self._learned_cadence() + self._learned_margin()
            if now < slot or now - slot > ADAPTIVE_MARGIN_MAX:
                self._stale_retry_count = 0
                return self._grid_delay(origin, now)
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
            # Retries exhausted: the report is unusually late.
            self._stale_retry_count = 0
            self._exhaust_pending = True
            self._exhausted_cycles += 1
            if self._exhausted_cycles >= ADAPTIVE_CHRONIC_LAG_CYCLES:
                if not self._chronic_lag:
                    _LOGGER.debug(
                        "%s: %d exhausted retry cycles in a row, polling "
                        "flat until a report arrives within the margin",
                        self.station,
                        self._exhausted_cycles,
                    )
                self._chronic_lag = True
            if self._chronic_lag:
                return DEFAULT_SCAN_INTERVAL
            return self._grid_delay(origin, now)

        # New observation.
        self._last_observation_time = obs_time
        self._stale_retry_count = 0
        if self._exhaust_pending:
            self._exhaust_pending = False
        else:
            self._exhausted_cycles = 0
        # Recovery needs a known lag (AWC receiptTime), judged on the first
        # publication of this report - not on when this install noticed it.
        known_lag = self._routine_log.get(obs_time)
        if known_lag is not None and known_lag <= ADAPTIVE_MARGIN_MAX:
            self._exhausted_cycles = 0
            self._chronic_lag = False
        if self._chronic_lag:
            return DEFAULT_SCAN_INTERVAL
        return self._grid_delay(origin, now)

    async def _async_update_data(self):
        """Fetch data from API with retry logic."""
        last_error = None
        attempts_made = 0
        fetched: dict | None = None

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

                    fetched = data
                    break

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

        if fetched is not None:
            # Scheduling runs outside the fetch retry loop: a bug in it must
            # not be retried (sleeps included) as if the fetch had failed.
            try:
                history = getattr(self.client, "routine_history", None)
                self.update_interval = self._compute_next_update_interval(
                    fetched, history if isinstance(history, list) else None
                )
            except Exception:  # noqa: BLE001 - never lose fresh data to scheduling
                _LOGGER.exception(
                    "Adaptive scheduling failed for %s; using the default interval",
                    self.station,
                )
                self.update_interval = DEFAULT_SCAN_INTERVAL
            _LOGGER.debug("Updated data for %s: %s", self.station, fetched)
            return fetched

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
