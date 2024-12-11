"""
Constants for the HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""

from datetime import timedelta
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
)

DOMAIN = "ha_metar_weather"
CONF_ICAO = "icao"
CONF_TERMS_ACCEPTED = "terms_accepted"
CONF_STATIONS = "stations"

DEFAULT_NAME = "METAR Weather"
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
RANDOM_MINUTES_MIN = 10
RANDOM_MINUTES_MAX = 15

STORAGE_KEY = f"{DOMAIN}.history"
STORAGE_VERSION = 1

# Error retry intervals in minutes
RETRY_INTERVALS = [3, 6, 12, 60]

# ICAO code validation
ICAO_REGEX = "^[A-Z0-9]{4}$"

# Attributes
ATTR_LAST_UPDATE = "last_update"
ATTR_STATION_NAME = "station_name"
ATTR_RAW_METAR = "raw_metar"
ATTR_HISTORICAL_DATA = "historical_data"

# Units (using new constants)
UNIT_TEMPERATURE = UnitOfTemperature.CELSIUS
UNIT_LENGTH = UnitOfLength.METERS
UNIT_PRESSURE = UnitOfPressure.HPA
UNIT_SPEED = UnitOfSpeed.METERS_PER_SECOND
