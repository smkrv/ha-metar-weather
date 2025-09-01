"""
Storage handling for HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from datetime import timedelta
import logging
from typing import Dict, List, Optional, Any
import threading
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

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the storage."""
        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=1.0,
            immediate=False,
            function=self._save_data,
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
            self._cleanup_old_data()
        except Exception as err:
            _LOGGER.error("Error loading storage data: %s", err)
            self._data = {}

    def _validate_stored_data(self, stored: Any) -> Dict[str, List[Dict[str, Any]]]:
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

    def _save_data(self) -> None:
        """Actually save the data."""
        with self._lock:
            try:
                data_to_save = deepcopy(self._data)
                self.hass.async_create_task(self.store.async_save(data_to_save))
            except Exception as err:
                _LOGGER.error("Error saving storage data: %s", err)
                raise MetarStorageError(f"Failed to save data: {err}") from err

    async def async_add_record(self, station: str, record: Dict[str, Any]) -> None:
        """Add a new METAR record for a station."""
        with self._lock:
            try:
                if station not in self._data:
                    self._data[station] = []

                # Проверка лимита
                if len(self._data[station]) >= MAX_RECORDS_PER_STATION:
                    self._data[station] = self._data[station][-(MAX_RECORDS_PER_STATION-1):]

                record_copy = deepcopy(record)
                record_copy["timestamp"] = dt_util.utcnow().isoformat()
                self._data[station].append(record_copy)

            except Exception as err:
                _LOGGER.error("Error adding record: %s", err)
                raise MetarStorageError(f"Failed to add record: {err}") from err

        # Cleanup old data after adding new record
        self._cleanup_old_data()
        await self.async_save()

    def _cleanup_old_data(self) -> None:
        """Remove data older than 24 hours."""
        with self._lock:
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
                    self._data[station] = []

    def get_station_history(self, station: str, key: str) -> List[Any]:
        """Get historical data for a specific key of a station."""
        with self._lock:
            try:
                records = deepcopy(self._data.get(station, []))
                # Filter data for the specified key
                history = [
                    record[key]
                    for record in records
                    if key in record
                ]
                return history
            except Exception as err:
                _LOGGER.error("Error getting history for station %s and key %s: %s", station, key, err)
                return []

    def get_all_station_records(self, station: str) -> List[Dict[str, Any]]:
        """Get all historical records for a station."""
        with self._lock:
            try:
                records = deepcopy(self._data.get(station, []))
                return records
            except Exception as err:
                _LOGGER.error("Error getting records for station %s: %s", station, err)
                return []

    def get_last_record(self, station: str) -> Optional[Dict[str, Any]]:
        """Get the most recent record for a station."""
        try:
            records = self.get_all_station_records(station)
            return deepcopy(records[-1]) if records else None
        except Exception as err:
            _LOGGER.error("Error getting last record for station %s: %s", station, err)
            return None

    async def async_clear_station(self, station: str) -> None:
        """Clear all history for a specific station."""
        with self._lock:
            try:
                if station in self._data:
                    del self._data[station]
            except Exception as err:
                _LOGGER.error("Error clearing station %s: %s", station, err)
                raise MetarStorageError(f"Failed to clear station: {err}") from err

        await self.async_save()

    async def async_clear_key_history(self, station: str, key: str) -> None:
        """Clear history for a specific key of a station."""
        with self._lock:
            try:
                if station in self._data:
                    self._data[station] = [
                        record for record in self._data[station]
                        if key not in record
                    ]
                    await self.async_save()
                    _LOGGER.debug("Cleared history for key %s in station %s", key, station)
            except Exception as err:
                _LOGGER.error("Error clearing key history: %s", err)
                raise MetarStorageError(f"Failed to clear key history: {err}") from err

    async def async_clear_all(self) -> None:
        """Clear all stored data."""
        with self._lock:
            try:
                self._data = {}
            except Exception as err:
                _LOGGER.error("Error clearing all data: %s", err)
                raise MetarStorageError(f"Failed to clear all data: {err}") from err

        await self.async_save()
