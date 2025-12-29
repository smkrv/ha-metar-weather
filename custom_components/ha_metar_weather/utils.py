"""
Utility functions for HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from .const import RUNWAY_SURFACE_CODES, RUNWAY_COVERAGE_CODES, ICAO_REGEX

_LOGGER = logging.getLogger(__name__)


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
                    "surface": "Snow closed",
                    "coverage": "100%",
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
                    "surface": "Clear and dry",
                    "coverage": "0%",
                    "depth": 0,
                    "friction": friction,
                    "raw": conditions
                }
            elif len(conditions) >= 4 and conditions[:4].isalpha():
                # Handle 4-letter codes like SNOW55, SAND55, etc.
                # These are non-standard but used in some regions
                surface_code = conditions[:4]
                friction_code = conditions[4:6] if len(conditions) >= 6 else '//'
                if friction_code == '//':
                    friction = None
                else:
                    try:
                        friction = int(friction_code) / 100
                    except ValueError:
                        friction = None
                state = {
                    "surface": surface_code.capitalize(),  # e.g., "SNOW" -> "Snow"
                    "coverage": "Unknown",  # Not specified in 4-letter format
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
                    "surface": RUNWAY_SURFACE_CODES.get(conditions[0], "Unknown"),
                    "coverage": RUNWAY_COVERAGE_CODES.get(conditions[1], "Unknown"),
                    "depth": depth,
                    "friction": friction,
                    "raw": conditions
                }

            runway_states[runway] = state
            _LOGGER.debug("Parsed runway state for %s: %s", runway, state)

    except Exception as err:
        _LOGGER.warning("Error parsing runway states from raw METAR: %s", err)

    return runway_states

