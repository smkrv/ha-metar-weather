"""
Constants for the HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""

from __future__ import annotations

import json
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Dict, Final, Tuple

from homeassistant.const import (
    UnitOfTemperature,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    CONF_UNIT_SYSTEM_METRIC,
    CONF_UNIT_SYSTEM_IMPERIAL,
)


class TrendState(StrEnum):
    """Enumeration for trend states."""

    STABLE = "stable"
    RISING = "rising"
    FALLING = "falling"
    # Wind direction specific trends
    VEERING = "veering"  # clockwise shift
    BACKING = "backing"  # counter-clockwise shift

# Core constants
DOMAIN: Final[str] = "ha_metar_weather"
CONF_ICAO: Final[str] = "icao"
CONF_TERMS_ACCEPTED: Final[str] = "terms_accepted"
CONF_STATIONS: Final[str] = "stations"

# Unit configuration keys
CONF_TEMP_UNIT: Final[str] = "temperature_unit"
CONF_WIND_SPEED_UNIT: Final[str] = "wind_speed_unit"
CONF_VISIBILITY_UNIT: Final[str] = "visibility_unit"
CONF_PRESSURE_UNIT: Final[str] = "pressure_unit"
CONF_ALTITUDE_UNIT: Final[str] = "altitude_unit"

# Custom units
DEGREE: Final[str] = "°"
PERCENTAGE: Final[str] = "%"

# Version - read from manifest.json to avoid duplication
def _get_version() -> str:
    """Read version from manifest.json."""
    try:
        manifest_path = Path(__file__).parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        return manifest.get("version", "0.0.0")
    except (FileNotFoundError, json.JSONDecodeError):
        return "0.0.0"

VERSION: Final[str] = _get_version()

# Default settings
DEFAULT_NAME: Final[str] = "METAR Weather"
DEFAULT_SCAN_INTERVAL: Final[timedelta] = timedelta(minutes=30)

# Storage settings
STORAGE_KEY: Final[str] = f"{DOMAIN}.history"

# Unit conversion factors
KNOTS_TO_KMH: Final[float] = 1.852
MPS_TO_KMH: Final[float] = 3.6
MILES_TO_KM: Final[float] = 1.60934
INHG_TO_HPA: Final[float] = 33.8639
FEET_TO_METERS: Final[float] = 0.3048

# Visibility constants
# Default value for excellent visibility (10+ SM, P6SM, etc.)
DEFAULT_EXCELLENT_VISIBILITY_KM: Final[float] = 16.0
STORAGE_VERSION: Final[int] = 1
MAX_RECORDS_PER_STATION: Final[int] = 200
MAX_HISTORY_DISPLAY: Final[int] = 24  # Number of historical records to show in attributes

# Error handling
RETRY_INTERVALS: Final[tuple[int, ...]] = (2, 5, 10, 30)

# API configuration
AWC_API_BASE_URL: Final[str] = "https://aviationweather.gov/api/data/metar"
AWC_API_TIMEOUT: Final[int] = 30  # seconds
AVWX_TIMEOUT: Final[int] = 30  # seconds

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
    },
    "cloud_coverage_height": {
        CONF_UNIT_SYSTEM_METRIC: UnitOfLength.METERS,
        CONF_UNIT_SYSTEM_IMPERIAL: UnitOfLength.FEET
    }
}

# Fixed units that don't change based on system preferences
FIXED_UNITS: Final[Dict[str, str]] = {
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
# Note: wind_speed matches parser's 200 kt limit, wind_gust matches 300 kt limit
VALUE_RANGES: Final[Dict[str, Tuple[float, float]]] = {
    "temperature": (-100.0, 60.0),    # °C
    "dew_point": (-100.0, 60.0),      # °C
    "wind_speed": (0.0, 370.0),       # km/h (200 kt max from parser)
    "wind_gust": (0.0, 556.0),        # km/h (300 kt max from parser)
    "visibility": (0.0, 100.0),       # km (updated to allow real visibility values)
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
    "NCD": "No clouds detected",
    "CAVOK": "Ceiling and visibility OK",
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
    "0": "Clear and dry (0%)",
    "1": "Less than 10%",
    "2": "11-25%",
    "3": "26-50%",
    "4": "51-75%",
    "5": "26-50%",  # Alternative code used in some regions
    "6": "51-75%",  # Alternative code used in some regions
    "7": "76-90%",
    "8": "91-100%",
    "9": "51-100%",  # Generic 51%+ coverage
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

# Available units for user selection
AVAILABLE_TEMP_UNITS: Final[list[str]] = [
    UnitOfTemperature.CELSIUS,
    UnitOfTemperature.FAHRENHEIT,
]

AVAILABLE_WIND_SPEED_UNITS: Final[list[str]] = [
    UnitOfSpeed.KILOMETERS_PER_HOUR,
    UnitOfSpeed.METERS_PER_SECOND,
    UnitOfSpeed.MILES_PER_HOUR,
    UnitOfSpeed.KNOTS,
]

AVAILABLE_VISIBILITY_UNITS: Final[list[str]] = [
    UnitOfLength.KILOMETERS,
    UnitOfLength.METERS,
    UnitOfLength.MILES,
    UnitOfLength.FEET,
]

AVAILABLE_PRESSURE_UNITS: Final[list[str]] = [
    UnitOfPressure.HPA,
    UnitOfPressure.INHG,
    UnitOfPressure.MMHG,
    # Note: MBAR is equivalent to HPA (1 mbar = 1 hPa)
]

AVAILABLE_ALTITUDE_UNITS: Final[list[str]] = [
    UnitOfLength.FEET,
    UnitOfLength.METERS,
]

# Default units (matching aviation standards)
DEFAULT_TEMP_UNIT: Final[str] = UnitOfTemperature.CELSIUS
DEFAULT_WIND_SPEED_UNIT: Final[str] = UnitOfSpeed.KNOTS
DEFAULT_VISIBILITY_UNIT: Final[str] = UnitOfLength.KILOMETERS
DEFAULT_PRESSURE_UNIT: Final[str] = UnitOfPressure.HPA
DEFAULT_ALTITUDE_UNIT: Final[str] = UnitOfLength.FEET

# Unit option key for "auto" (use HA system)
UNIT_AUTO: Final[str] = "auto"

# Unit option key for "native" (use original METAR/aviation units)
UNIT_NATIVE: Final[str] = "native"

# Native METAR units mapping (standard aviation units)
# These are the units typically used in METAR reports
NATIVE_METAR_UNITS: Final[Dict[str, str]] = {
    "temperature": UnitOfTemperature.CELSIUS,      # METAR always uses Celsius
    "wind_speed": UnitOfSpeed.KNOTS,               # METAR uses knots (KT) or m/s (MPS)
    "visibility": UnitOfLength.MILES,              # US METAR uses statute miles (SM)
    "pressure": UnitOfPressure.HPA,                # ICAO uses hPa (QNH), US uses inHg (A)
    "altitude": UnitOfLength.FEET,                 # Cloud heights always in feet
}
