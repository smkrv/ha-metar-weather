"""
Storage handling for HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from datetime import timedelta
import logging
from typing import Optional, Any
import asyncio
from copy import deepcopy

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.debounce import Debouncer
from homeassistant.util import dt as dt_util
from .const import (
    STORAGE_KEY,
    STORAGE_VERSION,
    MAX_RECORDS_PER_STATION,
)

_LOGGER = logging.getLogger(__name__)

class MetarStorageError(Exception):
    """Exception for storage related errors."""

class MetarHistoryStorage:
    """Class to handle storage of METAR history data."""

    # Cleanup every N records instead of on each record
    CLEANUP_INTERVAL = 10

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the storage."""
        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._records_since_cleanup = 0
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=1.0,
            immediate=False,
            function=self._async_save_data,
        )

    async def async_load(self) -> None:
        """Load data from storage."""
        try:
            stored = await self.store.async_load()
            if stored:
                self._data = self._validate_stored_data(stored)
            else:
                self._data = {}

            # Cleanup old data on load
            await self._async_cleanup_old_data()
        except asyncio.CancelledError:
            raise  # Don't suppress cancellation
        except Exception as err:
            _LOGGER.error("Error loading storage data: %s", err)
            self._data = {}

    def _validate_stored_data(self, stored: Any) -> dict[str, list[dict[str, Any]]]:
        """Validate and clean stored data."""
        if not isinstance(stored, dict):
            _LOGGER.warning("Invalid stored data format, resetting")
            return {}

        validated_data = {}
        for station, records in stored.items():
            if not isinstance(records, list):
                continue

            valid_records = []
            for record in records:
                if not isinstance(record, dict):
                    continue

                try:
                    # Ensure timestamp is in UTC
                    timestamp = record.get("timestamp")
                    if timestamp:
                        dt = dt_util.parse_datetime(timestamp)
                        if dt is None:
                            continue  # Skip invalid timestamp
                        dt = dt_util.as_utc(dt)
                        record["timestamp"] = dt.isoformat()
                    else:
                        continue  # Skip records without timestamp

                    valid_records.append(record)
                except (ValueError, TypeError) as err:
                    _LOGGER.debug("Invalid record for station %s: %s", station, err)
                    continue

            if valid_records:
                validated_data[station] = valid_records

        return validated_data

    async def async_save(self) -> None:
        """Schedule saving data with debouncing."""
        await self._debouncer.async_call()

    async def _async_save_data(self) -> None:
        """Actually save the data."""
        async with self._lock:
            try:
                data_to_save = deepcopy(self._data)
                await self.store.async_save(data_to_save)
            except asyncio.CancelledError:
                raise  # Don't suppress cancellation
            except Exception as err:
                _LOGGER.error("Error saving storage data: %s", err)
                raise MetarStorageError(f"Failed to save data: {err}") from err

    async def async_add_record(self, station: str, record: dict[str, Any]) -> None:
        """Add a new METAR record for a station."""
        async with self._lock:
            try:
                if station not in self._data:
                    self._data[station] = []

                # Check record limit
                if len(self._data[station]) >= MAX_RECORDS_PER_STATION:
                    self._data[station] = self._data[station][-(MAX_RECORDS_PER_STATION-1):]

                record_copy = deepcopy(record)
                # Use observation_time from METAR if available for accurate historical data
                # Fall back to current time if not present
                if "observation_time" in record_copy and record_copy["observation_time"]:
                    record_copy["timestamp"] = record_copy["observation_time"]
                else:
                    record_copy["timestamp"] = dt_util.utcnow().isoformat()
                self._data[station].append(record_copy)

                # Periodic cleanup instead of on every record
                self._records_since_cleanup += 1
                if self._records_since_cleanup >= self.CLEANUP_INTERVAL:
                    self._cleanup_old_data_sync()
                    self._records_since_cleanup = 0

            except asyncio.CancelledError:
                raise  # Don't suppress cancellation
            except Exception as err:
                _LOGGER.error("Error adding record: %s", err)
                raise MetarStorageError(f"Failed to add record: {err}") from err

        # Save outside lock to prevent blocking other operations
        try:
            await self.async_save()
        except asyncio.CancelledError:
            raise  # Don't suppress cancellation
        except Exception as err:
            # Log but don't raise - data is in memory, will be saved on next successful attempt
            _LOGGER.warning("Failed to save storage (data in memory): %s", err)

    def _cleanup_old_data_sync(self) -> None:
        """Remove data older than 24 hours (synchronous, must be called within lock)."""
        now = dt_util.utcnow()
        cutoff = now - timedelta(days=1)

        for station in list(self._data.keys()):
            try:
                filtered_records = []
                for record in self._data[station]:
                    try:
                        timestamp = record.get("timestamp")
                        if not timestamp:
                            continue
                        dt = dt_util.parse_datetime(timestamp)
                        if dt is None:
                            continue
                        dt = dt_util.as_utc(dt)
                        if dt > cutoff:
                            filtered_records.append(record)
                    except (ValueError, KeyError) as err:
                        _LOGGER.debug("Invalid record during cleanup: %s", err)
                        continue

                if filtered_records:
                    self._data[station] = filtered_records
                else:
                    del self._data[station]

            except Exception as err:
                _LOGGER.error("Error cleaning up data for station %s: %s", station, err)
                # Keep existing data rather than wiping it on error
                # Data will be cleaned up on next successful attempt

    async def _async_cleanup_old_data(self) -> None:
        """Remove data older than 24 hours."""
        async with self._lock:
            self._cleanup_old_data_sync()

    async def async_get_station_history(self, station: str, key: str) -> list[Any]:
        """Get historical data for a specific key of a station.

        Returns copies of values to prevent external modifications.
        For primitive types (int, float, str, bool, None), returns values directly.
        For complex types (list, dict), returns deep copies.
        Thread-safe via lock.
        """
        async with self._lock:
            try:
                records = self._data.get(station, [])
                history = []
                for record in records:
                    if isinstance(record, dict) and key in record:
                        value = record[key]
                        # Primitive types don't need deepcopy
                        if isinstance(value, (int, float, str, bool, type(None))):
                            history.append(value)
                        else:
                            # Complex types need deepcopy for safety
                            history.append(deepcopy(value))
                return history
            except Exception as err:
                _LOGGER.error("Error getting history for station %s and key %s: %s", station, key, err)
                return []

    def get_station_history(self, station: str, key: str) -> list[Any]:
        """Synchronous version - gets snapshot of current data.

        WARNING: This method is not fully thread-safe. The slice operation
        creates a shallow copy but is not atomic. For guaranteed thread-safe
        access in async context, prefer async_get_station_history().

        This method is intended for use in synchronous property getters
        where async is not available (e.g., extra_state_attributes).

        Returns copies of values to prevent external modifications.
        For primitive types (int, float, str, bool, None), returns values directly.
        For complex types (list, dict), returns deep copies.
        """
        try:
            # Get reference and immediately create snapshot via slice
            # Slice [:] creates a shallow copy without iteration, minimizing race window
            station_data = self._data.get(station)
            if station_data is None:
                return []
            records = station_data[:]  # Shallow copy snapshot (not truly atomic)
            history = []
            for record in records:
                if isinstance(record, dict) and key in record:
                    value = record[key]
                    # Primitive types don't need deepcopy
                    if isinstance(value, (int, float, str, bool, type(None))):
                        history.append(value)
                    else:
                        # Complex types need deepcopy for safety
                        history.append(deepcopy(value))
            return history
        except Exception as err:
            _LOGGER.error("Error getting history for station %s and key %s: %s", station, key, err)
            return []

    async def async_get_all_station_records(self, station: str) -> list[dict[str, Any]]:
        """Get all historical records for a station (async, thread-safe)."""
        async with self._lock:
            try:
                records = self._data.get(station, [])
                return deepcopy(records)
            except Exception as err:
                _LOGGER.error("Error getting records for station %s: %s", station, err)
                return []

    def get_all_station_records(self, station: str) -> list[dict[str, Any]]:
        """Synchronous version - gets snapshot of current data."""
        try:
            station_data = self._data.get(station)
            if station_data is None:
                return []
            records = station_data[:]  # Shallow copy snapshot (not truly atomic)
            return deepcopy(records)
        except Exception as err:
            _LOGGER.error("Error getting records for station %s: %s", station, err)
            return []

    async def async_get_last_record(self, station: str) -> Optional[dict[str, Any]]:
        """Get the most recent record for a station (async, thread-safe)."""
        async with self._lock:
            try:
                records = self._data.get(station, [])
                if records:
                    return deepcopy(records[-1]) if isinstance(records[-1], dict) else None
                return None
            except Exception as err:
                _LOGGER.error("Error getting last record for station %s: %s", station, err)
                return None

    def get_last_record(self, station: str) -> Optional[dict[str, Any]]:
        """Synchronous version - gets snapshot of current data."""
        try:
            station_data = self._data.get(station)
            if station_data is None or not station_data:
                return None
            # Direct access to last element (no iteration)
            last = station_data[-1]
            return deepcopy(last) if isinstance(last, dict) else None
        except Exception as err:
            _LOGGER.error("Error getting last record for station %s: %s", station, err)
            return None

    async def async_clear_station(self, station: str) -> None:
        """Clear all history for a specific station."""
        async with self._lock:
            try:
                if station in self._data:
                    del self._data[station]
            except asyncio.CancelledError:
                raise  # Don't suppress cancellation
            except Exception as err:
                _LOGGER.error("Error clearing station %s: %s", station, err)
                raise MetarStorageError(f"Failed to clear station: {err}") from err

        await self.async_save()

    async def async_clear_key_history(self, station: str, key: str) -> None:
        """Clear history for a specific key of a station.

        Removes the specified key from all records, keeping other data intact.
        Records that become empty (except timestamp) are preserved for timeline continuity.
        """
        async with self._lock:
            try:
                if station in self._data:
                    # Remove the key from each record, not the entire record
                    self._data[station] = [
                        {k: v for k, v in record.items() if k != key}
                        for record in self._data[station]
                    ]
                    _LOGGER.debug("Cleared key %s from all records in station %s", key, station)
            except asyncio.CancelledError:
                raise  # Don't suppress cancellation
            except Exception as err:
                _LOGGER.error("Error clearing key history: %s", err)
                raise MetarStorageError(f"Failed to clear key history: {err}") from err

        await self.async_save()

    async def async_clear_all(self) -> None:
        """Clear all stored data."""
        async with self._lock:
            try:
                self._data = {}
            except asyncio.CancelledError:
                raise  # Don't suppress cancellation
            except Exception as err:
                _LOGGER.error("Error clearing all data: %s", err)
                raise MetarStorageError(f"Failed to clear all data: {err}") from err

        await self.async_save()

    async def async_cleanup(self) -> None:
        """Public cleanup method for graceful shutdown.

        Performs final save and cancels pending debouncer to prevent writes after unload.
        """
        if self._debouncer:
            # Cancel pending debounced calls first
            self._debouncer.async_cancel()

            # Perform final save to ensure no data loss
            try:
                await self._async_save_data()
                _LOGGER.debug("Storage final save completed on cleanup")
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning("Failed to save data on cleanup: %s", err)

            _LOGGER.debug("Storage cleanup completed")
