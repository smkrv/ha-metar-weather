"""
Utility functions for METAR Weather integration.

@license: MIT
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from homeassistant.const import UnitOfLength, UnitOfPressure, UnitOfSpeed

from .const import (
    RUNWAY_SURFACE_CODES,
    RUNWAY_COVERAGE_CODES,
    ICAO_REGEX,
    NATIVE_METAR_UNITS,
)

_LOGGER = logging.getLogger(__name__)

# Wind group: 24008KT, VRB03G15MPS, 00000KT; AUTO stations with a failed wind
# sensor transmit slash placeholders (/////KT, ///08MPS) - the unit suffix is
# still meaningful for unit detection.
_WIND_GROUP_RE = re.compile(
    r"(?:VRB|/{3}|\d{3})(?:\d{2,3}|/{2,3})(?:G(?:\d{2,3}|/{2,3}))?(KT|MPS)$"
)
# Visibility in meters (ICAO): 9999, 0800NDV, 3000NE; CAVOK handled separately.
_VIS_METERS_RE = re.compile(r"\d{4}(?:NDV|[NSEW]{1,2})?$")
# Visibility in statute miles (North America): 10SM, P6SM, M1/4SM, 1/2SM.
_VIS_SM_RE = re.compile(r"[PM]?\d+(?:/\d+)?SM$")


def detect_native_units(raw_metar: Optional[str]) -> Dict[str, str]:
    """Units the station itself uses in its METAR reports.

    "Native (METAR)" display mode follows the units of the actual report, which
    differ by region: wind in KT or MPS, visibility in meters (ICAO) or statute
    miles (US/Canada), pressure as Q-group (hPa) or A-group (inHg). Temperature
    is always Celsius and cloud heights are always feet. A station's format is
    stable, so one report is enough. Falls back to NATIVE_METAR_UNITS for any
    group missing from the report (or when no report is available yet).
    """
    units = dict(NATIVE_METAR_UNITS)
    if not raw_metar:
        return units

    # Trend/remark sections may repeat groups in other formats; use the body.
    body = re.split(r"\b(?:RMK|TEMPO|BECMG)\b", raw_metar)[0]
    tokens = body.split()

    pressure_unit = None
    for token in tokens:
        if wind := _WIND_GROUP_RE.fullmatch(token):
            units["wind_speed"] = (
                UnitOfSpeed.KNOTS
                if wind.group(1) == "KT"
                else UnitOfSpeed.METERS_PER_SECOND
            )
            break
    else:
        _LOGGER.debug(
            "No wind group recognized in %r; native wind unit falls back to %s",
            raw_metar,
            units["wind_speed"],
        )
    for token in tokens:
        if re.fullmatch(r"Q\d{4}", token):
            pressure_unit = UnitOfPressure.HPA
            break
        if re.fullmatch(r"A\d{4}", token):
            pressure_unit = UnitOfPressure.INHG
            break
    if pressure_unit:
        units["pressure"] = pressure_unit

    for token in tokens:
        if token == "CAVOK" or _VIS_METERS_RE.fullmatch(token):
            units["visibility"] = UnitOfLength.METERS
            break
        if _VIS_SM_RE.fullmatch(token):
            units["visibility"] = UnitOfLength.MILES
            break
    else:
        # No visibility group at all: the pressure group style is a reliable
        # regional proxy (A-group stations are the ones reporting SM).
        if pressure_unit == UnitOfPressure.INHG:
            units["visibility"] = UnitOfLength.MILES
        elif pressure_unit == UnitOfPressure.HPA:
            units["visibility"] = UnitOfLength.METERS
        else:
            _LOGGER.debug(
                "No visibility or pressure group recognized in %r; native "
                "visibility unit falls back to %s",
                raw_metar,
                units["visibility"],
            )

    return units


def validate_icao_format(icao: str) -> bool:
    """Validate ICAO airport code format.

    Args:
        icao: ICAO airport code (e.g., "KJFK", "EGLL")

    Returns:
        True if format is valid (4 alphanumeric characters)
    """
    if not icao:
        return False
    return bool(re.match(ICAO_REGEX, icao.upper()))


def calculate_humidity(temp: Optional[float], dew: Optional[float]) -> Optional[float]:
    """Calculate relative humidity from temperature and dew point using Magnus formula.

    Args:
        temp: Temperature in Celsius
        dew: Dew point in Celsius

    Returns:
        Relative humidity as percentage (0-100), or None if calculation fails
    """
    if temp is None or dew is None:
        return None

    try:
        # Guard against division by zero (temp/dew near -237.7°C is unrealistic)
        if (237.7 + temp) <= 0.1 or (237.7 + dew) <= 0.1:
            return None

        # Magnus formula for humidity calculation
        e = 6.11 * 10.0 ** (7.5 * dew / (237.7 + dew))
        es = 6.11 * 10.0 ** (7.5 * temp / (237.7 + temp))

        if es <= 0:
            return None

        humidity = round((e / es) * 100, 1)
        # Clamp to valid range
        return max(0.0, min(100.0, humidity))

    except (ZeroDivisionError, ValueError, OverflowError) as err:
        _LOGGER.debug("Error calculating humidity: %s", err)
        return None


def parse_runway_states_from_raw(raw_metar: str) -> Dict[str, Dict[str, Any]]:
    """Parse runway states from raw METAR string.

    Shared utility function for both AWC and AVWX parsers.

    Handles formats:
    - Standard: R24L/123456 (surface/coverage/depth/friction)
    - CLRD: R24L/CLRD62 or R24L/CLRD// (cleared runway)
    - SNOCLO: R24/SNOCLO (runway closed due to snow)

    Args:
        raw_metar: Raw METAR string

    Returns:
        Dictionary of runway states keyed by runway identifier
    """
    runway_states: Dict[str, Dict[str, Any]] = {}

    try:
        matches = re.finditer(
            r'R(\d{2}[LCR]?)/(SNOCLO|CLRD[/\d]{2}|[A-Z]{4}[/\d]{2}|\d{6}|\d{4}//)',
            raw_metar
        )
        for match in matches:
            runway = match.group(1)
            conditions = match.group(2)

            if conditions == 'SNOCLO':
                state = {
                    "surface": "snow_closed",
                    "coverage": "cov_91_100",
                    "depth": 0,
                    "friction": None,
                    "raw": conditions
                }
            elif conditions.startswith('CLRD'):
                friction_code = conditions[4:6]
                if friction_code == '//':
                    friction = None
                else:
                    try:
                        friction = int(friction_code) / 100
                    except ValueError:
                        friction = None
                state = {
                    "surface": "cleared",
                    "coverage": "cov_0",
                    "depth": 0,
                    "friction": friction,
                    "raw": conditions
                }
            elif len(conditions) >= 4 and conditions[:4].isalpha():
                # Non-standard 4-letter codes (SNOW55, SAND55, ...) used in some
                # regions. Not in the standard vocabulary -> map to 'unknown';
                # the original code is preserved in "raw".
                friction_code = conditions[4:6] if len(conditions) >= 6 else '//'
                if friction_code == '//':
                    friction = None
                else:
                    try:
                        friction = int(friction_code) / 100
                    except ValueError:
                        friction = None
                state = {
                    "surface": "unknown",
                    "coverage": "unknown",
                    "depth": 0,
                    "friction": friction,
                    "raw": conditions
                }
            else:
                # Standard 6-digit format or format with //
                friction_code = conditions[4:6] if len(conditions) >= 6 else '//'
                if friction_code == '//':
                    friction = None
                else:
                    try:
                        friction = int(friction_code) / 100
                    except ValueError:
                        friction = None

                depth_code = conditions[2:4] if len(conditions) >= 4 else '//'
                if depth_code == '//':
                    depth = 0
                else:
                    try:
                        depth = int(depth_code)
                    except ValueError:
                        depth = 0

                state = {
                    "surface": RUNWAY_SURFACE_CODES.get(conditions[0], "unknown"),
                    "coverage": RUNWAY_COVERAGE_CODES.get(conditions[1], "unknown"),
                    "depth": depth,
                    "friction": friction,
                    "raw": conditions
                }

            runway_states[runway] = state
            _LOGGER.debug("Parsed runway state for %s: %s", runway, state)

    except Exception as err:
        _LOGGER.warning("Error parsing runway states from raw METAR: %s", err)

    return runway_states

