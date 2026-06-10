"""
Constants for the METAR Weather integration.

@license: MIT
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

# Unit conversion factors. Must match HA core's unit_conversion.py exactly,
# or a stored value converted back to its source unit by core drifts off the
# reported one (1 kt stored as 1.9 km/h displayed as "1.03 kn" - issue #7).
KNOTS_TO_KMH: Final[float] = 1.852          # core: 1852 m per NM
MPS_TO_KMH: Final[float] = 3.6
MILES_TO_KM: Final[float] = 1.609344        # core: _MILE_TO_M
INHG_TO_HPA: Final[float] = 33.86388640341  # core: PressureConverter inHg
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

# Internal storage precision. NOT a display precision: values are stored in
# base units (km/h, km, hPa) at near-full precision so that HA's conversion
# back to the unit the report used (kn, SM, inHg, m) reproduces the exact
# reported value. 6 decimals only strips binary float noise. Rounding for
# display happens in the frontend via suggested_display_precision (sensor.py).
NUMERIC_PRECISION: Final[Dict[str, int]] = {
    "temperature": 1,
    "dew_point": 1,
    "wind_speed": 6,
    "wind_gust": 6,
    "visibility": 6,
    "pressure": 6,
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

# METAR code -> canonical, language-independent slug.
#
# These maps are the single source of truth for the machine value of a sensor
# state. The human-readable strings live only in translations/<lang>.json under
# entity.sensor.<key>.state.<slug> and are rendered per user by the HA frontend.
# Slugs are stable across languages and across both data sources (issue #3 / the
# phase-2 localization roadmap in docs/localization-roadmap.md).

# Weather intensity prefixes (moderate intensity has no marker -> no slug).
WEATHER_INTENSITY_CODES: Final[Dict[str, str]] = {
    "-": "light",
    "+": "heavy",
    "VC": "vicinity",
}

# Weather descriptors.
WEATHER_DESCRIPTOR_CODES: Final[Dict[str, str]] = {
    "MI": "shallow",
    "PR": "partial",
    "BC": "patches",
    "DR": "low_drifting",
    "BL": "blowing",
    "SH": "showers",
    "TS": "thunderstorm",
    "FZ": "freezing",
}

# Weather phenomena (precipitation / obscuration / other).
WEATHER_PHENOMENON_CODES: Final[Dict[str, str]] = {
    "DZ": "drizzle",
    "RA": "rain",
    "SN": "snow",
    "SG": "snow_grains",
    "IC": "ice_crystals",
    "PL": "ice_pellets",
    "GR": "hail",
    "GS": "small_hail",
    "UP": "unknown",
    "BR": "mist",
    "FG": "fog",
    "FU": "smoke",
    "VA": "volcanic_ash",
    "DU": "dust",
    "SA": "sand",
    "HZ": "haze",
    "PY": "spray",
    "PO": "dust_whirls",
    "SQ": "squalls",
    "FC": "funnel_cloud",
    "SS": "sandstorm",
    "DS": "duststorm",
}

# Recent (RE-prefixed) weather phenomena that the parser recognises explicitly.
RECENT_WEATHER_CODES: Final[Dict[str, str]] = {
    "RESN": "snow",
    "RERA": "rain",
    "REDZ": "drizzle",
    "RETS": "thunderstorm",
    "REFZRA": "freezing_rain",
    "REPL": "ice_pellets",
    "REGR": "hail",
    "REGS": "small_hail",
    "RESH": "showers",
    "REBLSN": "blowing_snow",
    "REFG": "fog",
}

# Cloud coverage code -> slug.
CLOUD_COVERAGE: Final[Dict[str, str]] = {
    "SKC": "clear_sky",
    "CLR": "clr",
    "NSC": "no_significant",
    "NCD": "ncd",
    "CAVOK": "cavok",
    "FEW": "few",
    "SCT": "scattered",
    "BKN": "broken",
    "OVC": "overcast",
    "VV": "vertical_visibility",
}

# Closed vocabulary for the cloud_coverage_state ENUM sensor. "clear" is emitted
# when no layers are present.
CLOUD_COVERAGE_OPTIONS: Final[list[str]] = [
    "clear",
    "clear_sky",
    "clr",
    "no_significant",
    "ncd",
    "cavok",
    "few",
    "scattered",
    "broken",
    "overcast",
    "vertical_visibility",
]

# Cloud type code -> slug.
CLOUD_TYPES: Final[Dict[str, str]] = {
    "CB": "cumulonimbus",
    "TCU": "towering_cumulus",
    "CI": "cirrus",
    "CS": "cirrostratus",
    "CC": "cirrocumulus",
    "AS": "altostratus",
    "AC": "altocumulus",
    "NS": "nimbostratus",
    "SC": "stratocumulus",
    "ST": "stratus",
    "CU": "cumulus",
}

# Closed vocabulary for the cloud_coverage_type ENUM sensor. "none" when absent.
CLOUD_TYPE_OPTIONS: Final[list[str]] = ["none", *CLOUD_TYPES.values()]

# Runway surface code -> slug.
RUNWAY_SURFACE_CODES: Final[Dict[str, str]] = {
    "0": "clear_and_dry",
    "1": "damp",
    "2": "wet",
    "3": "rime_or_frost",
    "4": "dry_snow",
    "5": "wet_snow",
    "6": "slush",
    "7": "ice",
    "8": "compacted_snow",
    "9": "frozen_ruts",
    "/": "not_reported",
}

# Closed vocabulary for runway surface (plus special raw groups + fallback).
RUNWAY_SURFACE_OPTIONS: Final[list[str]] = [
    *dict.fromkeys(RUNWAY_SURFACE_CODES.values()),
    "snow_closed",
    "cleared",
    "unknown",
]

# Runway coverage code -> slug.
RUNWAY_COVERAGE_CODES: Final[Dict[str, str]] = {
    "0": "cov_0",
    "1": "cov_lt10",
    "2": "cov_11_25",
    "3": "cov_26_50",
    "4": "cov_51_75",
    "5": "cov_26_50",  # Alternative code used in some regions
    "6": "cov_51_75",  # Alternative code used in some regions
    "7": "cov_76_90",
    "8": "cov_91_100",
    "9": "cov_51_100",  # Generic 51%+ coverage
    "/": "not_reported",
}

RUNWAY_COVERAGE_OPTIONS: Final[list[str]] = [
    *dict.fromkeys(RUNWAY_COVERAGE_CODES.values()),
    "unknown",
]

# Report-type ENUM (auto vs manual observation).
REPORT_TYPE_OPTIONS: Final[list[str]] = ["auto", "manual"]

# CAVOK ENUM (Ceiling And Visibility OK).
CAVOK_OPTIONS: Final[list[str]] = ["yes", "no"]

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

# Display precision per *display* unit. HA stores suggested_display_precision
# relative to the suggested unit (core only ratio-adjusts it when the user
# manually overrides the unit), so each unit we may suggest needs its own
# sensible decimals: integer meters/feet, hundredths of inHg (A2992 = 29.92),
# hundredths of a statute mile (common US fractions 1/4SM..3/4SM render
# exactly; the rare 1/8SM and 1/16SM round to 0.12/0.06 mi - the price of
# not showing "10.000 mi" for every clear day).
DISPLAY_PRECISION_BY_UNIT: Final[Dict[str, int]] = {
    UnitOfTemperature.CELSIUS: 1,
    UnitOfTemperature.FAHRENHEIT: 1,
    UnitOfSpeed.KILOMETERS_PER_HOUR: 1,
    UnitOfSpeed.METERS_PER_SECOND: 1,
    UnitOfSpeed.MILES_PER_HOUR: 1,
    UnitOfSpeed.KNOTS: 1,
    UnitOfLength.KILOMETERS: 1,
    UnitOfLength.METERS: 0,
    UnitOfLength.MILES: 2,
    UnitOfLength.FEET: 0,
    UnitOfPressure.HPA: 1,
    UnitOfPressure.INHG: 2,
    UnitOfPressure.MMHG: 1,
}

# Unit option key for "auto" (use HA system)
UNIT_AUTO: Final[str] = "auto"

# Unit option key for "native" (use original METAR/aviation units)
UNIT_NATIVE: Final[str] = "native"

# Fallback for the "native" unit mode, used only while the station's raw METAR
# is not available yet. Once a report exists, utils.detect_native_units() reads
# the units the station itself transmits (KT vs MPS, meters vs SM, Q vs A) and
# overrides these defaults per station.
NATIVE_METAR_UNITS: Final[Dict[str, str]] = {
    "temperature": UnitOfTemperature.CELSIUS,      # METAR always uses Celsius
    "wind_speed": UnitOfSpeed.KNOTS,               # most stations report KT
    "visibility": UnitOfLength.METERS,             # ICAO reports meters; US uses SM
    "pressure": UnitOfPressure.HPA,                # ICAO QNH (Q); US altimeter (A) is inHg
    "altitude": UnitOfLength.FEET,                 # cloud heights always in feet
}
