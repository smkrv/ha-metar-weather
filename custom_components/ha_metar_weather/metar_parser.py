"""
Parser for the HA METAR Weather integration.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from .const import (
    CLOUD_COVERAGE,
    CLOUD_TYPES,
    WEATHER_PHENOMENA,
    RUNWAY_SURFACE_CODES,
    RUNWAY_COVERAGE_CODES,
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class CloudLayer:
    """Represents a cloud layer in METAR."""
    coverage: str
    height: Optional[int]
    type: Optional[str] = None

    def __str__(self) -> str:
        """Return string representation of cloud layer."""
        parts = [self.coverage]
        if self.height is not None:
            parts.append(f"{self.height}ft")
        if self.type:
            parts.append(self.type)
        return " ".join(parts)

@dataclass
class RunwayState:
    """Represents runway state in METAR."""
    surface: str
    coverage: str
    depth: int
    friction: float
    raw: str

    def __str__(self) -> str:
        """Return string representation of runway state."""
        return (f"Surface: {self.surface}, Coverage: {self.coverage}, "
                f"Depth: {self.depth}mm, Friction: {self.friction}")

class MetarParser:
    """Parser for METAR data."""

    CLOUD_COVERAGE = CLOUD_COVERAGE
    CLOUD_TYPES = CLOUD_TYPES
    WEATHER_PHENOMENA = WEATHER_PHENOMENA
    RUNWAY_SURFACE_CODES = RUNWAY_SURFACE_CODES
    RUNWAY_COVERAGE_CODES = RUNWAY_COVERAGE_CODES

    def __init__(self, metar_data: Any):
        """Initialize parser with METAR data."""
        self.metar = metar_data
        self.raw_metar = getattr(metar_data, 'raw', '')
        _LOGGER.debug("Initializing METAR parser with data: %s", self.raw_metar)

    def parse_cloud_layers(self) -> List[CloudLayer]:
        """Parse cloud information from METAR."""
        layers = []
        try:
            # Search for string parts containing cloud information
            parts = self.raw_metar.split()
            for part in parts:
                if any(part.startswith(prefix) for prefix in ['FEW', 'SCT', 'BKN', 'OVC']):
                    coverage_code = part[:3]
                    coverage = self.CLOUD_COVERAGE.get(coverage_code, coverage_code)

                    # Extract height (next 3 digits after code)
                    height = None
                    if len(part) >= 6 and part[3:6].isdigit():
                        height = int(part[3:6]) * 100  # Multiply by 100 to get feet

                    # Determine cloud type (if present)
                    cloud_type = None
                    if len(part) > 6:
                        type_code = part[6:]
                        cloud_type = self.CLOUD_TYPES.get(type_code)

                    layer = CloudLayer(
                        coverage=coverage,
                        height=height,
                        type=cloud_type
                    )
                    layers.append(layer)
                    _LOGGER.debug("Parsed cloud layer: %s at %s feet", coverage, height)

            return layers
        except Exception as err:
            _LOGGER.error("Error parsing cloud layers: %s", err)
            return []

    def parse_runway_states(self) -> Dict[str, RunwayState]:
        """Parse runway states from METAR."""
        runway_states = {}

        try:
            # Handle both standard format (R24L/123456) and special formats (R24L/CLRD62)
            matches = re.finditer(r'R(\d{2}[LCR]?)/([A-Z]{4}\d{2}|\d{6})', self.raw_metar)
            for match in matches:
                runway = match.group(1)
                conditions = match.group(2)

                if conditions.startswith('CLRD'):
                    # Special case for CLRD format (Clear and dry runway)
                    friction_code = conditions[4:6]
                    state = RunwayState(
                        surface="Clear and dry",
                        coverage="0%",
                        depth=0,
                        friction=int(friction_code)/100,
                        raw=conditions
                    )
                else:
                    # Standard 6-digit format
                    state = RunwayState(
                        surface=self.RUNWAY_SURFACE_CODES.get(conditions[0], "Unknown"),
                        coverage=self.RUNWAY_COVERAGE_CODES.get(conditions[1], "Unknown"),
                        depth=int(conditions[2:4]),
                        friction=int(conditions[4:6])/100,
                        raw=conditions
                    )

                runway_states[runway] = state
                _LOGGER.debug("Parsed runway state for %s: %s", runway, state)

            return runway_states

        except Exception as err:
            _LOGGER.error("Error parsing runway states: %s", err)
            return {}

    def parse_weather(self) -> str:
        """Parse weather conditions."""
        try:
            if getattr(self.metar, 'cavok', False):
                return "CAVOK"

            weather_codes = []
            parts = self.raw_metar.split()

            # Complex weather phenomena can consist of multiple parts
            for part in parts:
                # Skip known non-weather codes
                if (part.endswith('KT') or part.endswith('MPS') or
                    '/' in part or part.startswith('Q') or
                    part.startswith('R') or part.isdigit() or
                    part in ['NOSIG', 'CAVOK']):
                    continue

                weather = ''
                intensity = ''
                descriptor = ''

                # Check intensity
                if part.startswith(('-', '+')):
                    intensity = self.WEATHER_PHENOMENA.get(part[0], '')
                    part = part[1:]
                elif part.startswith('VC'):
                    intensity = self.WEATHER_PHENOMENA['VC']
                    part = part[2:]

                # Check descriptors (2 letters)
                if len(part) >= 2:
                    desc = part[:2]
                    if desc in self.WEATHER_PHENOMENA:
                        descriptor = self.WEATHER_PHENOMENA[desc]
                        part = part[2:]

                # Check main phenomenon
                if part in self.WEATHER_PHENOMENA:
                    weather = self.WEATHER_PHENOMENA[part]

                # Assemble full weather description
                if any([intensity, descriptor, weather]):
                    full_weather = ' '.join(filter(None, [intensity, descriptor, weather]))
                    if full_weather:
                        weather_codes.append(full_weather)

            # Handle special cases
            if 'RESN' in parts:
                weather_codes.append('Recent Snow')
            if 'RETS' in parts:
                weather_codes.append('Recent Thunderstorm')
            if 'RERA' in parts:
                weather_codes.append('Recent Rain')

            _LOGGER.debug(
                "Parsed weather phenomena: %s from METAR: %s",
                weather_codes,
                self.raw_metar
            )

            return ', '.join(weather_codes) if weather_codes else "Clear"

        except Exception as err:
            _LOGGER.error("Error parsing weather conditions: %s", err)
            return "Clear"

    def parse_trend(self) -> Optional[str]:
        """Parse trend information."""
        try:
            trend_parts = []

            # Check for NOSIG (No Significant Change) in raw METAR
            if 'NOSIG' in self.raw_metar:
                return "No significant change"

            if hasattr(self.metar, 'tempo'):
                trend_parts.append(f"TEMPO {self.metar.tempo}")
            if hasattr(self.metar, 'trend'):
                trend_parts.append(f"TREND {self.metar.trend}")
            if hasattr(self.metar, 'becoming'):
                trend_parts.append(f"BECMG {self.metar.becoming}")

            return " | ".join(trend_parts) if trend_parts else None

        except Exception as err:
            _LOGGER.error("Error parsing trend information: %s", err)
            return None

    def _extract_numeric_value(self, value: Any) -> Optional[float]:
        """Extract numeric value from METAR number objects."""
        _LOGGER.debug("Extracting numeric value from: %s", value)

        try:
            if hasattr(value, 'value'):
                val = value.value
                # For visibility in meters, convert to appropriate units
                if hasattr(value, 'units'):
                    if value.units == 'm':  # if value is in meters
                        return float(val)  # keep in meters
                return float(val)

            if isinstance(value, str):
                if value.startswith('M'):
                    return -float(value[1:])
                return float(value)

            if isinstance(value, (int, float)):
                return float(value)

            return None

        except (ValueError, TypeError) as err:
            _LOGGER.error("Error extracting numeric value: %s (%s)", value, err)
            return None

    def parse_cloud_coverage(self) -> str:
        """Parse cloud coverage state."""
        try:
            clouds = self.parse_cloud_layers()
            if not clouds:
                return "Clear"
            return clouds[0].coverage
        except Exception as err:
            _LOGGER.error("Error parsing cloud coverage: %s", err)
            return "Clear"

    def parse_cloud_height(self) -> Optional[int]:
        """Parse cloud height."""
        try:
            clouds = self.parse_cloud_layers()
            if not clouds:
                return None
            return clouds[0].height
        except Exception as err:
            _LOGGER.error("Error parsing cloud height: %s", err)
            return None

    def parse_cloud_type(self) -> str:
        """Parse cloud type."""
        try:
            clouds = self.parse_cloud_layers()
            if not clouds or not clouds[0].type:
                return "N/A"
            return clouds[0].type
        except Exception as err:
            _LOGGER.error("Error parsing cloud type: %s", err)
            return "N/A"

    def get_parsed_data(self) -> Dict[str, Any]:
        """Return complete parsed METAR data."""
        raw_parts = self.raw_metar.split()

        # Determine CAVOK status
        cavok = "CAVOK" in self.raw_metar

        # Parse wind data
        wind_data = self._parse_wind(raw_parts)

        # Parse temperature and dew point
        temp, dew = self._parse_temp_dew(raw_parts)

        # Parse pressure
        pressure = self._parse_pressure(raw_parts)

        # Calculate humidity
        humidity = self._calculate_humidity(temp, dew)

        # Parse cloud data
        cloud_layers = self.parse_cloud_layers()

        # Process visibility
        visibility = None
        if cavok:
            visibility = 10.0  # CAVOK means 10 km visibility
        else:
            # Find the wind part index to start looking for visibility after it
            wind_index = -1
            for i, part in enumerate(raw_parts):
                if part.endswith('KT') or part.endswith('MPS'):
                    wind_index = i
                    break

            # Look for visibility after wind part
            if wind_index >= 0:
                for i, part in enumerate(raw_parts[wind_index + 1:], start=wind_index + 1):
                    # Skip variable wind direction (e.g., 180V240)
                    if re.match(r'^\d{3}V\d{3}$', part):
                        continue

                    # Check for 4-digit visibility in meters (e.g., 9999, 7000, 0800)
                    if re.match(r'^\d{4}$', part):
                        vis_meters = int(part)
                        if vis_meters == 9999:
                            visibility = 10.0  # 9999 means 10 km or more
                        else:
                            visibility = vis_meters / 1000  # Convert meters to kilometers
                        _LOGGER.debug("Parsed visibility: %s meters = %s km", vis_meters, visibility)
                        break

                    # Check for visibility with NDV (no directional variation) suffix
                    ndv_match = re.match(r'^(\d{4})NDV$', part)
                    if ndv_match:
                        vis_meters = int(ndv_match.group(1))
                        if vis_meters == 9999:
                            visibility = 10.0
                        else:
                            visibility = vis_meters / 1000
                        _LOGGER.debug("Parsed NDV visibility: %s meters = %s km", vis_meters, visibility)
                        break

                    # Stop at cloud, temperature, or pressure parts
                    if (part.startswith(('FEW', 'SCT', 'BKN', 'OVC', 'SKC', 'CLR', 'NSC', 'VV')) or
                        '/' in part or part.startswith('Q') or part.startswith('A')):
                        break

        # Parse weather phenomena (excluding TEMPO)
        weather_conditions = []
        tempo_index = len(raw_parts)
        if 'TEMPO' in raw_parts:
            tempo_index = raw_parts.index('TEMPO')

        for part in raw_parts[:tempo_index]:
            if part in self.WEATHER_PHENOMENA:
                weather_conditions.append(self.WEATHER_PHENOMENA[part])
            elif part.startswith('+') or part.startswith('-'):
                if part[1:] in self.WEATHER_PHENOMENA:
                    weather_conditions.append(self.WEATHER_PHENOMENA[part[1:]])

        data = {
            "raw_metar": self.raw_metar,
            "cloud_layers": cloud_layers,
            "cloud_coverage_state": self.parse_cloud_coverage(),
            "cloud_coverage_height": self.parse_cloud_height(),
            "cloud_coverage_type": self.parse_cloud_type(),
            "weather": ", ".join(weather_conditions) if weather_conditions else "Clear",
            "trend": self.parse_trend(),
            "runway_states": {rwy: state.__dict__ for rwy, state in self.parse_runway_states().items()},
            "temperature": temp,
            "dew_point": dew,
            "humidity": humidity,
            "wind_speed": wind_data["speed"],
            "wind_direction": wind_data["direction"],
            "wind_gust": wind_data["gust"],
            "wind_variable_direction": wind_data["variable"],
            "visibility": visibility,
            "pressure": pressure,
            "cavok": cavok,
            "auto": getattr(self.metar, 'auto', False),
        }

        _LOGGER.debug("Parsed METAR data: %s", data)
        return data

    def _validate_wind_speed(self, speed: Optional[float]) -> Optional[float]:
        """Validate wind speed value."""
        if speed is None:
            return None
        if speed < 0 or speed > 400:
            _LOGGER.warning("Invalid wind speed value: %s km/h", speed)
            return None
        return speed

    def _parse_wind(self, raw_parts: List[str]) -> Dict[str, Optional[Union[float, str]]]:
        """Parse wind information from METAR."""
        result: Dict[str, Optional[Union[float, str]]] = {
            "speed": None,
            "direction": None,
            "gust": None,
            "variable": None
        }

        try:
            for part in raw_parts:
                # Parse main wind information (direction and speed)
                if 'KT' in part:
                    # Handle VRB (variable) wind direction: VRB03KT, VRB03G10KT
                    vrb_match = re.match(r'VRB(\d{2,3})(?:G(\d{2,3}))?KT', part)
                    if vrb_match:
                        speed_kt = int(vrb_match.group(1))

                        # Variable wind direction - set to None but mark as variable
                        result["direction"] = None
                        result["variable"] = "VRB"

                        # Validate wind speed
                        if 0 <= speed_kt <= 200:  # reasonable maximum for knots
                            result["speed"] = round(speed_kt * 1.852, 1)
                        else:
                            _LOGGER.warning("Invalid wind speed: %s kt", speed_kt)
                            continue

                        if vrb_match.group(2):
                            gust_kt = int(vrb_match.group(2))
                            if 0 <= gust_kt <= 300:  # reasonable maximum for gusts
                                result["gust"] = round(gust_kt * 1.852, 1)
                            else:
                                _LOGGER.warning("Invalid wind gust: %s kt", gust_kt)

                        _LOGGER.debug(
                            "Parsed VRB KT wind: variable direction at %s kt (%s km/h)",
                            speed_kt,
                            result["speed"]
                        )
                        continue

                    # Handle standard wind direction: 13008KT, 13008G15KT
                    match = re.match(r'(\d{3})(\d{2,3})(?:G(\d{2,3}))?KT', part)
                    if match:
                        direction = int(match.group(1))
                        speed_kt = int(match.group(2))

                        # Validate wind direction
                        if 0 <= direction <= 360:
                            result["direction"] = float(direction)
                        else:
                            _LOGGER.warning("Invalid wind direction: %s°", direction)
                            continue

                        # Validate wind speed
                        if 0 <= speed_kt <= 200:  # reasonable maximum for knots
                            result["speed"] = round(speed_kt * 1.852, 1)
                        else:
                            _LOGGER.warning("Invalid wind speed: %s kt", speed_kt)
                            continue

                        if match.group(3):
                            gust_kt = int(match.group(3))
                            if 0 <= gust_kt <= 300:  # reasonable maximum for gusts
                                result["gust"] = round(gust_kt * 1.852, 1)
                            else:
                                _LOGGER.warning("Invalid wind gust: %s kt", gust_kt)

                        _LOGGER.debug(
                            "Parsed KT wind: %s° at %s kt (%s km/h)",
                            direction,
                            speed_kt,
                            result["speed"]
                        )

                elif 'MPS' in part:
                    # Handle VRB (variable) wind direction: VRB03MPS, VRB03G10MPS
                    vrb_match = re.match(r'VRB(\d{2,3})(?:G(\d{2,3}))?MPS', part)
                    if vrb_match:
                        speed_ms = int(vrb_match.group(1))

                        # Variable wind direction - set to None but mark as variable
                        result["direction"] = None
                        result["variable"] = "VRB"

                        # Validate wind speed
                        if 0 <= speed_ms <= 100:  # reasonable maximum for m/s
                            result["speed"] = round(speed_ms * 3.6, 1)
                        else:
                            _LOGGER.warning("Invalid wind speed: %s m/s", speed_ms)
                            continue

                        if vrb_match.group(2):
                            gust_ms = int(vrb_match.group(2))
                            if 0 <= gust_ms <= 150:  # reasonable maximum for gusts in m/s
                                result["gust"] = round(gust_ms * 3.6, 1)
                            else:
                                _LOGGER.warning("Invalid wind gust: %s m/s", gust_ms)

                        _LOGGER.debug(
                            "Parsed VRB MPS wind: variable direction at %s m/s (%s km/h)",
                            speed_ms,
                            result["speed"]
                        )
                        continue

                    # Handle standard wind direction: 13008MPS, 13008G15MPS
                    match = re.match(r'(\d{3})(\d{2,3})(?:G(\d{2,3}))?MPS', part)
                    if match:
                        direction = int(match.group(1))
                        speed_ms = int(match.group(2))

                        # Validate wind direction
                        if 0 <= direction <= 360:
                            result["direction"] = float(direction)
                        else:
                            _LOGGER.warning("Invalid wind direction: %s°", direction)
                            continue

                        # Validate wind speed
                        if 0 <= speed_ms <= 100:  # reasonable maximum for m/s
                            result["speed"] = round(speed_ms * 3.6, 1)
                        else:
                            _LOGGER.warning("Invalid wind speed: %s m/s", speed_ms)
                            continue

                        if match.group(3):
                            gust_ms = int(match.group(3))
                            if 0 <= gust_ms <= 150:  # reasonable maximum for gusts in m/s
                                result["gust"] = round(gust_ms * 3.6, 1)
                            else:
                                _LOGGER.warning("Invalid wind gust: %s m/s", gust_ms)

                        _LOGGER.debug(
                            "Parsed MPS wind: %s° at %s m/s (%s km/h)",
                            direction,
                            speed_ms,
                            result["speed"]
                        )

                # Parse variable wind direction
                elif 'V' in part and len(part) == 7:  # format: 180V240
                    match = re.match(r'(\d{3})V(\d{3})', part)
                    if match:
                        start_dir = int(match.group(1))
                        end_dir = int(match.group(2))
                        
                        # Validate directions
                        if 0 <= start_dir <= 360 and 0 <= end_dir <= 360:
                            result["variable"] = f"{start_dir:03d}°-{end_dir:03d}°"
                            _LOGGER.debug("Parsed variable wind direction: %s", result["variable"])
                        else:
                            _LOGGER.warning("Invalid variable wind directions: %s-%s", start_dir, end_dir)

        except (ValueError, TypeError) as err:
            _LOGGER.error("Error parsing wind data: %s", err)
        except Exception as err:
            _LOGGER.error("Unexpected error parsing wind data: %s", err)

        return result

    def _parse_temp_dew(self, raw_parts: List[str]) -> tuple[Optional[float], Optional[float]]:
        """Parse temperature and dew point."""
        try:
            for part in raw_parts:
                # Temperature/dew point format: 04/02, M05/M10, 15/M02
                if '/' in part:
                    parts = part.split('/')
                    # Must have exactly 2 parts for temp/dew
                    if len(parts) != 2:
                        continue

                    temp_str, dew_str = parts

                    # Check if this looks like temp/dew (starts with digit or M for minus)
                    if not (temp_str and (temp_str[0].isdigit() or temp_str[0] == 'M')):
                        continue
                    if not (dew_str and (dew_str[0].isdigit() or dew_str[0] == 'M')):
                        continue

                    # Skip visibility parts like 1200/0800 (4-digit numbers)
                    if len(temp_str) > 3 or len(dew_str) > 3:
                        continue

                    temp_val = float(temp_str.replace('M', '-'))
                    dew_val = float(dew_str.replace('M', '-'))

                    # Validate value ranges
                    if not -100 <= temp_val <= 60:
                        _LOGGER.warning("Temperature %s°C outside valid range", temp_val)
                        return None, None
                    if not -100 <= dew_val <= 60:
                        _LOGGER.warning("Dew point %s°C outside valid range", dew_val)
                        return None, None

                    return temp_val, dew_val
            return None, None
        except Exception as err:
            _LOGGER.error("Error parsing temperature/dew point: %s", err)
            return None, None

    def _parse_pressure(self, raw_parts: List[str]) -> Optional[float]:
        """Parse pressure information.

        Handles both QNH (hPa) and altimeter (inHg) formats:
        - Q1013 = 1013 hPa
        - A3012 = 30.12 inHg (converted to hPa)
        """
        for part in raw_parts:
            # European format: Q followed by pressure in hPa
            if part.startswith('Q') and len(part) >= 4:
                try:
                    return float(part[1:])
                except ValueError:
                    continue

            # American format: A followed by pressure in inHg (e.g., A3012 = 30.12 inHg)
            if part.startswith('A') and len(part) == 5:
                try:
                    inhg = float(part[1:]) / 100  # A3012 -> 30.12
                    # Convert inHg to hPa (1 inHg = 33.8639 hPa)
                    hpa = round(inhg * 33.8639, 1)
                    _LOGGER.debug("Parsed A pressure: %s inHg = %s hPa", inhg, hpa)
                    return hpa
                except ValueError:
                    continue

        return None

    def _calculate_humidity(self, temp: Optional[float], dew: Optional[float]) -> Optional[float]:
        """Calculate relative humidity from temperature and dew point."""
        if temp is None or dew is None:
            return None
        try:
            e = 6.11 * 10.0**(7.5 * dew / (237.7 + dew))
            es = 6.11 * 10.0**(7.5 * temp / (237.7 + temp))
            return round((e / es) * 100, 1)
        except Exception as err:
            _LOGGER.error("Error calculating humidity: %s", err)
            return None
