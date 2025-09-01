"""
Constants for the HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""

from __future__ import annotations

import os
import json
import logging
from datetime import timedelta
from typing import Dict, Final, Tuple, Any

from homeassistant.const import (
    UnitOfTemperature,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    CONF_UNIT_SYSTEM_METRIC,
    CONF_UNIT_SYSTEM_IMPERIAL,
)

_LOGGER = logging.getLogger(__name__)

# Core constants
DOMAIN: Final[str] = "ha_metar_weather"
CONF_ICAO: Final[str] = "icao"
CONF_TERMS_ACCEPTED: Final[str] = "terms_accepted"
CONF_STATIONS: Final[str] = "stations"

# Custom units
DEGREE: Final[str] = "°"
PERCENTAGE: Final[str] = "%"

# Version management
MANIFEST_PATH: Final[str] = os.path.join(os.path.dirname(__file__), "manifest.json")
try:
    with open(MANIFEST_PATH) as manifest_file:
        manifest = json.load(manifest_file)
        VERSION: Final[str] = manifest.get("version", "unknown")
except (FileNotFoundError, json.JSONDecodeError, Exception) as err:
    VERSION = "unknown"
    _LOGGER.error("Error reading manifest.json: %s", err)

# Default settings
DEFAULT_NAME: Final[str] = "METAR Weather"
DEFAULT_SCAN_INTERVAL: Final[timedelta] = timedelta(minutes=30)
RANDOM_MINUTES_MIN: Final[int] = 5
RANDOM_MINUTES_MAX: Final[int] = 10

# Storage settings
STORAGE_KEY: Final[str] = f"{DOMAIN}.history"
STORAGE_VERSION: Final[int] = 1
MAX_RECORDS_PER_STATION = 200

# Error handling
RETRY_INTERVALS: Final[tuple[int, ...]] = (2, 5, 10, 30)

# Validation
ICAO_REGEX: Final[str] = r"^[A-Z0-9]{4}$"

# Attributes
ATTR_LAST_UPDATE: Final[str] = "last_update"
ATTR_STATION_NAME: Final[str] = "station_name"
ATTR_RAW_METAR: Final[str] = "raw_metar"
ATTR_HISTORICAL_DATA: Final[str] = "historical_data"
ATTR_TREND: Final[str] = "trend"
ATTR_REMARKS: Final[str] = "remarks"
ATTR_WIND_GUST: Final[str] = "wind_gust"
ATTR_WIND_VARIABLE_DIRECTION: Final[str] = "wind_variable_direction"

# Unit mappings
UNIT_MAPPINGS: Final[Dict[str, Dict[str, str]]] = {
    "temperature": {
        CONF_UNIT_SYSTEM_METRIC: UnitOfTemperature.CELSIUS,
        CONF_UNIT_SYSTEM_IMPERIAL: UnitOfTemperature.FAHRENHEIT
    },
    "pressure": {
        CONF_UNIT_SYSTEM_METRIC: UnitOfPressure.HPA,
        CONF_UNIT_SYSTEM_IMPERIAL: UnitOfPressure.INHG
    },
    "wind_speed": {
        CONF_UNIT_SYSTEM_METRIC: UnitOfSpeed.KILOMETERS_PER_HOUR,
        CONF_UNIT_SYSTEM_IMPERIAL: UnitOfSpeed.MILES_PER_HOUR
    },
    "visibility": {
        CONF_UNIT_SYSTEM_METRIC: UnitOfLength.KILOMETERS,
        CONF_UNIT_SYSTEM_IMPERIAL: UnitOfLength.MILES
    },
    "wind_gust": {
        CONF_UNIT_SYSTEM_METRIC: UnitOfSpeed.KILOMETERS_PER_HOUR,
        CONF_UNIT_SYSTEM_IMPERIAL: UnitOfSpeed.MILES_PER_HOUR
    }
}

# Fixed units that don't change based on system preferences
FIXED_UNITS: Final[Dict[str, str]] = {
    "cloud_coverage_height": UnitOfLength.FEET,
    "wind_direction": DEGREE,
    "humidity": PERCENTAGE,
}

# Numeric precision for different measurements
NUMERIC_PRECISION: Final[Dict[str, int]] = {
    "temperature": 1,
    "dew_point": 1,
    "wind_speed": 1,
    "wind_gust": 1,
    "visibility": 1,
    "pressure": 1,
    "humidity": 1,
    "cloud_coverage_height": 0
}

# Valid value ranges for measurements
VALUE_RANGES: Final[Dict[str, Tuple[float, float]]] = {
    "temperature": (-100.0, 60.0),    # °C
    "dew_point": (-100.0, 60.0),      # °C
    "wind_speed": (0.0, 400.0),       # km/h
    "wind_gust": (0.0, 500.0),        # km/h
    "visibility": (0.0, 20.0),        # km
    "pressure": (900.0, 1100.0),      # hPa
    "humidity": (0.0, 100.0),         # %
    "cloud_coverage_height": (0.0, 50000.0)  # feet
}

# Weather codes and descriptions
WEATHER_PHENOMENA: Final[Dict[str, str]] = {
    # Intensity
    '-': 'Light',
    '+': 'Heavy',
    'VC': 'Vicinity',

    # Descriptors
    'MI': 'Shallow',
    'PR': 'Partial',
    'BC': 'Patches',
    'DR': 'Low Drifting',
    'BL': 'Blowing',
    'SH': 'Shower',
    'TS': 'Thunderstorm',
    'FZ': 'Freezing',

    # Precipitation
    'DZ': 'Drizzle',
    'RA': 'Rain',
    'SN': 'Snow',
    'SG': 'Snow Grains',
    'IC': 'Ice Crystals',
    'PL': 'Ice Pellets',
    'GR': 'Hail',
    'GS': 'Small Hail',
    'UP': 'Unknown Precipitation',

    # Obscuration
    'BR': 'Mist',
    'FG': 'Fog',
    'FU': 'Smoke',
    'VA': 'Volcanic Ash',
    'DU': 'Widespread Dust',
    'SA': 'Sand',
    'HZ': 'Haze',
    'PY': 'Spray',

    # Other
    'PO': 'Dust/Sand Whirls',
    'SQ': 'Squalls',
    'FC': 'Funnel Cloud',
    'SS': 'Sandstorm',
    'DS': 'Duststorm'
}

# Cloud coverage descriptions
CLOUD_COVERAGE: Final[Dict[str, str]] = {
    "SKC": "Clear sky",
    "CLR": "No clouds below 12,000ft",
    "NSC": "No significant clouds",
    "FEW": "Few (1-2 oktas)",
    "SCT": "Scattered (3-4 oktas)",
    "BKN": "Broken (5-7 oktas)",
    "OVC": "Overcast (8 oktas)",
    "VV": "Vertical visibility"
}

# Cloud types
CLOUD_TYPES: Final[Dict[str, str]] = {
    "CB": "Cumulonimbus",
    "TCU": "Towering Cumulus",
    "CI": "Cirrus",
    "CS": "Cirrostratus",
    "CC": "Cirrocumulus",
    "AS": "Altostratus",
    "AC": "Altocumulus",
    "NS": "Nimbostratus",
    "SC": "Stratocumulus",
    "ST": "Stratus",
    "CU": "Cumulus"
}

# Runway condition codes
RUNWAY_SURFACE_CODES: Final[Dict[str, str]] = {
    "0": "Clear and dry",
    "1": "Damp",
    "2": "Wet or water patches",
    "3": "Rime or frost",
    "4": "Dry snow",
    "5": "Wet snow",
    "6": "Slush",
    "7": "Ice",
    "8": "Compacted snow",
    "9": "Frozen ruts or ridges",
    "/": "Not reported"
}

RUNWAY_COVERAGE_CODES: Final[Dict[str, str]] = {
    "1": "Less than 10%",
    "2": "11-25%",
    "5": "26-50%",
    "9": "51-100%",
    "/": "Not reported"
}

# Unit display formats
UNIT_FORMATS: Final[Dict[str, str]] = {
    UnitOfTemperature.CELSIUS: "°C",
    UnitOfTemperature.FAHRENHEIT: "°F",
    UnitOfLength.KILOMETERS: "km",
    UnitOfLength.MILES: "mi",
    UnitOfLength.METERS: "m",
    UnitOfLength.FEET: "ft",
    UnitOfPressure.HPA: "hPa",
    UnitOfPressure.INHG: "inHg",
    UnitOfPressure.MMHG: "mmHg",
    UnitOfSpeed.METERS_PER_SECOND: "m/s",
    UnitOfSpeed.MILES_PER_HOUR: "mph",
    UnitOfSpeed.KILOMETERS_PER_HOUR: "km/h",
    UnitOfSpeed.KNOTS: "kt",
}
