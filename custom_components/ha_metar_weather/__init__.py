"""
The METAR Weather integration.

@license: MIT
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import asyncio
import re
from asyncio import timeout as async_timeout
from datetime import timedelta, timezone
from typing import Final

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
from .taf_client import TafApiClient
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
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{station}",
            update_interval=update_interval,
        )
        self.client = client
        self.station = station
        self._retry_count = 0
        self._consecutive_failures = 0
        self._accepted_source: str | None = None

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
        _LOGGER.error(
            "Failed for %s after %d attempt(s). Consecutive failures: %d. Error: %s",
            self.station,
            attempts_made,
            self._consecutive_failures,
            last_error
        )
        raise UpdateFailed(f"Error fetching data after {attempts_made} attempt(s): {last_error}") from last_error


class TafDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching TAF data.

    Deliberately kept simpler than MetarDataUpdateCoordinator: with only
    the raw TAF string exposed (no periods/history/trend), the coordinator
    just needs retry-with-backoff and a lightweight staleness guard on
    issue_time so a lagging fetch can't overwrite a newer TAF with an
    older AMD/COR.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: TafApiClient,
        station: str,
        update_interval: timedelta,
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{station}_taf",
            update_interval=update_interval,
        )
        self.client = client
        self.station = station
        self._retry_count = 0
        self._consecutive_failures = 0

    def _reject_stale_taf(self, fetched: dict) -> dict:
        """Keep the held TAF when a fetch yields an older/equal issue_time.

        Mirrors MetarDataUpdateCoordinator._reject_stale_observation, but
        compares issue_time: a TAF is valid until superseded by a newer
        issuance (scheduled or AMD), so an older issue_time is never the
        current forecast. issue_time is AWC's raw string here (not yet
        normalized), so this is a plain string comparison of ISO-ish
        timestamps - good enough since AWC issues them in that form and a
        malformed value simply skips the guard (fetched wins) rather than
        crashing.
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
        """Fetch TAF data from API with retry logic."""
        last_error = None
        attempts_made = 0

        for attempt, delay in enumerate(RETRY_INTERVALS):
            attempts_made = attempt + 1
            try:
                data = await self.client.fetch_data()
                if data:
                    data = self._reject_stale_taf(data)
                    self._consecutive_failures = 0
                    self._retry_count = 0
                    _LOGGER.debug("Updated TAF for %s: %s", self.station, data)
                    return data

                # Station simply has no current TAF (common for smaller
                # airports) - not an error, retrying won't help.
                _LOGGER.debug("No TAF available for %s", self.station)
                return None

            except Exception as err:
                last_error = err
                self._retry_count = attempt + 1
                _LOGGER.warning(
                    "TAF attempt %d/%d failed for %s: %s. Retrying in %ds...",
                    attempt + 1,
                    len(RETRY_INTERVALS),
                    self.station,
                    err,
                    delay,
                )
                if attempt < len(RETRY_INTERVALS) - 1:
                    await asyncio.sleep(delay)

        self._consecutive_failures += 1
        _LOGGER.error(
            "TAF fetch failed for %s after %d attempt(s). Error: %s",
            self.station,
            attempts_made,
            last_error,
        )
        raise UpdateFailed(
            f"Error fetching TAF after {attempts_made} attempt(s): {last_error}"
        ) from last_error


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
    # A station without a current TAF (common for smaller airports) is
    # skipped rather than failing the whole config entry - it simply gets
    # no TAF sensor.
    taf_coordinators: dict[str, TafDataUpdateCoordinator] = {}
    for station in stations:
        station_upper = station.upper()
        try:
            taf_client = TafApiClient(hass, station_upper)
            taf_coordinator = TafDataUpdateCoordinator(
                hass,
                taf_client,
                station_upper,
                DEFAULT_TAF_SCAN_INTERVAL,
            )
            await taf_coordinator.async_config_entry_first_refresh()

            if taf_coordinator.data:
                taf_coordinators[station_upper] = taf_coordinator
            else:
                _LOGGER.info(
                    "No TAF available for station %s; skipping TAF sensor",
                    station_upper,
                )
        except Exception as err:
            _LOGGER.warning(
                "Error setting up TAF for station %s: %s", station_upper, err
            )
            continue

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
