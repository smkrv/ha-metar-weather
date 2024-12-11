"""
Storage handling for HA METAR Weather.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from .const import DOMAIN, STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

class MetarHistoryStorage:
    """Class to handle storage of METAR history data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the storage."""
        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: Dict[str, List[Dict]] = {}

    async def async_load(self) -> None:
        """Load data from storage."""
        stored = await self.store.async_load()
        if stored:
            self._data = stored
        else:
            self._data = {}

        # Cleanup old data on load
        await self._async_cleanup_old_data()

    async def async_save(self) -> None:
        """Save data to storage."""
        await self.store.async_save(self._data)

    async def async_add_record(self, station: str, record: Dict) -> None:
        """Add a new METAR record for a station."""
        if station not in self._data:
            self._data[station] = []

        # Add timestamp if not present
        if "timestamp" not in record:
            record["timestamp"] = datetime.utcnow().isoformat()

        self._data[station].append(record)

        # Cleanup old data after adding new
        await self._async_cleanup_old_data()
        await self.async_save()

    async def _async_cleanup_old_data(self) -> None:
        """Remove data older than 24 hours."""
        now = datetime.utcnow()
        cutoff = now - timedelta(days=1)

        for station in self._data:
            self._data[station] = [
                record for record in self._data[station]
                if datetime.fromisoformat(record["timestamp"]) > cutoff
            ]

    def get_station_history(self, station: str) -> List[Dict]:
        """Get historical data for a station."""
        return self._data.get(station, [])

    def get_last_record(self, station: str) -> Optional[Dict]:
        """Get the most recent record for a station."""
        station_data = self._data.get(station, [])
        return station_data[-1] if station_data else None
