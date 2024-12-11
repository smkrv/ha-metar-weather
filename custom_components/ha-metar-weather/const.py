"""
Constants for the HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@author: SMKRV
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from datetime import timedelta
import voluptuous as vol

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

# Validation schema for ICAO code
ICAO_REGEX = "^[A-Z0-9]{4}$"
ICAO_SCHEMA = vol.Schema(vol.Match(ICAO_REGEX))

ATTR_LAST_UPDATE = "last_update"
ATTR_METAR_DATA = "metar_data"
