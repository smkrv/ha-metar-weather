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
    WEATHER_INTENSITY_CODES,
    WEATHER_DESCRIPTOR_CODES,
    WEATHER_PHENOMENON_CODES,
    RECENT_WEATHER_CODES,
    RUNWAY_SURFACE_CODES,
    RUNWAY_COVERAGE_CODES,
    KNOTS_TO_KMH,
    MPS_TO_KMH,
    INHG_TO_HPA,
    MILES_TO_KM,
)
from .utils import calculate_humidity, parse_runway_states_from_raw

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
    friction: Optional[float]
    raw: str

    def __str__(self) -> str:
        """Return string representation of runway state."""
        friction_str = f"{self.friction}" if self.friction is not None else "N/A"
        return (f"Surface: {self.surface}, Coverage: {self.coverage}, "
                f"Depth: {self.depth}mm, Friction: {friction_str}")

class MetarParser:
    """Parser for METAR data."""

    CLOUD_COVERAGE = CLOUD_COVERAGE
    CLOUD_TYPES = CLOUD_TYPES
    WEATHER_INTENSITY_CODES = WEATHER_INTENSITY_CODES
    WEATHER_DESCRIPTOR_CODES = WEATHER_DESCRIPTOR_CODES
    WEATHER_PHENOMENON_CODES = WEATHER_PHENOMENON_CODES
    RUNWAY_SURFACE_CODES = RUNWAY_SURFACE_CODES
    RUNWAY_COVERAGE_CODES = RUNWAY_COVERAGE_CODES

    def __init__(self, raw_metar: str):
        """Initialize parser with a raw METAR string.

        The parser is a pure ``raw -> dict`` transform. Both data sources (AWC
        and AVWX) feed it the raw METAR so they produce identical textual output
        (see issue #3). Source-specific extras (the real station name, AWC's
        authoritative numerics) are layered in by the api_client afterwards.
        """
        self.raw_metar = raw_metar or ""
        # Caches for expensive parsing operations
        self._cloud_layers_cache: Optional[List[CloudLayer]] = None
        self._runway_states_cache: Optional[Dict[str, RunwayState]] = None
        if not self.raw_metar:
            _LOGGER.warning("Empty raw METAR string received, parsing may be incomplete")
        else:
            _LOGGER.debug("Initializing METAR parser with data: %s", self.raw_metar)

    def parse_cloud_layers(self) -> List[CloudLayer]:
        """Parse cloud information from METAR.

        Results are cached to avoid repeated parsing.
        Only parses current conditions - stops before trend/forecast sections
        (TEMPO, BECMG, FM, PROB30, PROB40, NOSIG, RMK).
        """
        if self._cloud_layers_cache is not None:
            return self._cloud_layers_cache

        layers = []
        try:
            # Search for string parts containing cloud information
            parts = self.raw_metar.split()
            for part in parts:
                # Stop at trend/forecast sections - these are not current conditions
                if part in ('TEMPO', 'BECMG', 'FM', 'PROB30', 'PROB40', 'NOSIG', 'RMK'):
                    break
                # Standard cloud layers: FEW, SCT, BKN, OVC
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

                # Clear sky indicators: SKC, CLR, NSC, NCD, CAVOK
                elif part in ['SKC', 'CLR', 'NSC', 'NCD', 'CAVOK']:
                    coverage = self.CLOUD_COVERAGE.get(part, part)
                    layer = CloudLayer(coverage=coverage, height=None, type=None)
                    layers.append(layer)
                    _LOGGER.debug("Parsed clear sky indicator: %s", part)

                # Vertical Visibility (VV): used for fog/obscuration (e.g., VV002 = 200ft, VV/// = undefined)
                elif part.startswith('VV'):
                    height_str = part[2:5] if len(part) >= 5 else part[2:]
                    # Skip malformed VV data (e.g., just "VV" with no value)
                    if not height_str:
                        _LOGGER.debug("Skipping malformed VV data: %s", part)
                        continue
                    if height_str == '///':
                        # VV/// means vertical visibility cannot be determined
                        layer = CloudLayer(
                            coverage="vertical_visibility",
                            height=None,
                            type=None
                        )
                        layers.append(layer)
                        _LOGGER.debug("Parsed vertical visibility: undefined (VV///)")
                    elif height_str.isdigit():
                        height = int(height_str) * 100  # VV002 = 200 feet
                        layer = CloudLayer(
                            coverage="vertical_visibility",
                            height=height,
                            type=None
                        )
                        layers.append(layer)
                        _LOGGER.debug("Parsed vertical visibility: %s feet", height)

            self._cloud_layers_cache = layers
            return layers
        except Exception as err:
            _LOGGER.error("Error parsing cloud layers: %s", err)
            return []

    def parse_runway_states(self) -> Dict[str, RunwayState]:
        """Parse runway states from METAR.

        Uses shared utility function from utils.py for consistency with AWC client.
        Results are cached to avoid repeated parsing.

        Handles multiple formats:
        - Standard: R24L/123456 (surface/coverage/depth/friction)
        - CLRD: R24L/CLRD62 or R24L/CLRD// (cleared runway)
        - SNOCLO: R24/SNOCLO (runway closed due to snow)
        """
        if self._runway_states_cache is not None:
            return self._runway_states_cache

        # Use shared parsing function and convert to RunwayState dataclasses
        raw_states = parse_runway_states_from_raw(self.raw_metar)
        self._runway_states_cache = {
            runway: RunwayState(
                surface=state["surface"],
                coverage=state["coverage"],
                depth=state["depth"],
                friction=state["friction"],
                raw=state["raw"]
            )
            for runway, state in raw_states.items()
        }
        return self._runway_states_cache

    def parse_weather_groups(self) -> List[Dict[str, Any]]:
        """Parse weather phenomena into structured groups of canonical slugs.

        Each group is ``{"intensity": slug|None, "descriptor": slug|None,
        "phenomena": [slug, ...], "recent": bool, "raw": str}``. Current-condition
        groups come first, recent (RE-prefixed) groups last. CAVOK yields no
        groups (no significant weather).
        """
        groups: List[Dict[str, Any]] = []
        try:
            parts = self.raw_metar.split()

            if "CAVOK" in parts:
                return []

            for original_part in parts:
                # Stop at remarks / trend sections (not current conditions).
                if original_part in ('RMK', 'TEMPO', 'BECMG', 'FM', 'PROB30', 'PROB40'):
                    break

                # Skip non-weather tokens. Runway groups (R24L/550362) are caught
                # by the '/' check; do NOT skip a leading 'R' (RA = rain).
                if (original_part.endswith('KT') or original_part.endswith('MPS') or
                        '/' in original_part or original_part.startswith('Q') or
                        original_part.isdigit() or
                        original_part in ('NOSIG', 'CAVOK')):
                    continue
                if (original_part.startswith('A') and len(original_part) == 5 and
                        original_part[1:].isdigit()):
                    continue
                if original_part in ('TL', 'AT', 'SKC', 'CLR', 'NSC', 'NCD', 'AUTO', 'COR'):
                    continue

                group = self._parse_weather_group(original_part)
                if group and group not in groups:
                    groups.append(group)

            # Recent weather (RE-prefixed) - exact token match.
            for code, slug in RECENT_WEATHER_CODES.items():
                if code in parts:
                    groups.append({
                        "intensity": None,
                        "descriptor": None,
                        "phenomena": [slug],
                        "recent": True,
                        "raw": code,
                    })

            _LOGGER.debug("Parsed weather groups: %s from METAR: %s", groups, self.raw_metar)
            return groups

        except Exception as err:
            _LOGGER.error("Error parsing weather conditions: %s", err)
            return []

    def _parse_weather_group(self, part: str) -> Optional[Dict[str, Any]]:
        """Parse a single weather group token into canonical slugs."""
        intensity: Optional[str] = None
        descriptor: Optional[str] = None
        phenomena: List[str] = []

        remaining = part
        if remaining.startswith(('-', '+')):
            intensity = self.WEATHER_INTENSITY_CODES.get(remaining[0])
            remaining = remaining[1:]
        elif remaining.startswith('VC'):
            intensity = self.WEATHER_INTENSITY_CODES.get('VC')
            remaining = remaining[2:]

        while len(remaining) >= 2:
            code = remaining[:2]
            if code in self.WEATHER_DESCRIPTOR_CODES:
                descriptor = self.WEATHER_DESCRIPTOR_CODES[code]
                remaining = remaining[2:]
            elif code in self.WEATHER_PHENOMENON_CODES:
                phenomena.append(self.WEATHER_PHENOMENON_CODES[code])
                remaining = remaining[2:]
            else:
                # Unknown trailing code - stop parsing this group.
                break

        if not (intensity or descriptor or phenomena):
            return None

        return {
            "intensity": intensity,
            "descriptor": descriptor,
            "phenomena": phenomena,
            "recent": False,
            "raw": part,
        }

    def parse_weather(self) -> str:
        """Canonical weather slug for the sensor state.

        Composes intensity / descriptor / phenomena slugs in a fixed order joined
        by '_' (e.g. 'heavy_thunderstorm_rain'); 'clear' when there is no weather.
        Multiple groups are joined by '_'; recent groups are prefixed 'recent'.
        The frontend localizes this slug via translations/<lang>.json; unknown
        combinations render as the raw slug (no crash - the sensor is not an ENUM).
        """
        tokens: List[str] = []
        for group in self.parse_weather_groups():
            if group.get("recent"):
                tokens.append("recent")
            if group.get("intensity"):
                tokens.append(group["intensity"])
            if group.get("descriptor"):
                tokens.append(group["descriptor"])
            tokens.extend(group.get("phenomena", []))
        return "_".join(tokens) if tokens else "clear"

    def parse_trend(self) -> Optional[str]:
        """Parse the trend/forecast group from the raw METAR.

        Trend is free-form forecast text, so it is returned verbatim from the
        raw string (NOSIG, or the TEMPO/BECMG segment up to any RMK section).
        """
        try:
            # Trend groups appear before any RMK section; drop remarks first so a
            # TEMPO/BECMG token inside RMK is not mistaken for a trend.
            body = re.split(r'\bRMK\b', self.raw_metar)[0]

            # NOSIG (No Significant Change) - kept as the raw, language-neutral code.
            if 'NOSIG' in body:
                return "NOSIG"

            # TEMPO / BECMG forecast segment - return from the keyword to the end
            match = re.search(r'\b(?:TEMPO|BECMG)\b', body)
            if not match:
                return None

            segment = body[match.start():].strip()
            return segment or None

        except Exception as err:
            _LOGGER.error("Error parsing trend information: %s", err)
            return None

    def parse_cloud_coverage(self) -> str:
        """Parse cloud coverage state as a slug ('clear' when no layers)."""
        try:
            clouds = self.parse_cloud_layers()
            if not clouds:
                return "clear"
            return clouds[0].coverage
        except Exception as err:
            _LOGGER.error("Error parsing cloud coverage: %s", err)
            return "clear"

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
        """Parse cloud type as a slug ('none' when absent)."""
        try:
            clouds = self.parse_cloud_layers()
            if not clouds or not clouds[0].type:
                return "none"
            return clouds[0].type
        except Exception as err:
            _LOGGER.error("Error parsing cloud type: %s", err)
            return "none"

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

            # If no wind found, start searching from position 2 (after station code and time)
            # METAR format: ICAO TIME [WIND] VISIBILITY ...
            if wind_index < 0:
                wind_index = 1  # Skip station code, assume visibility starts after position 1
                _LOGGER.debug("No wind found in METAR, starting visibility search from position 2")

            # Look for visibility after wind part (visibility comes within first 2-3 parts after wind)
            if wind_index >= 0:
                # Limit search to prevent matching unrelated 4-digit numbers later in METAR
                max_visibility_search = min(wind_index + 4, len(raw_parts))

                for idx, part in enumerate(raw_parts[wind_index + 1:max_visibility_search]):
                    # Skip variable wind direction (e.g., 180V240)
                    if re.match(r'^\d{3}V\d{3}$', part):
                        continue

                    # Skip runway conditions (e.g., R24L/..., R09/...)
                    if part.startswith('R') and '/' in part:
                        continue

                    # Check for 4-digit visibility in meters (e.g., 9999, 7000, 0800)
                    # Valid visibility range: 0000-9999 meters
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

                    # Check for visibility with direction (e.g., 3000NE, 1500S, 0800SW)
                    dir_match = re.match(r'^(\d{4})([NSEW]{1,2})$', part)
                    if dir_match:
                        vis_meters = int(dir_match.group(1))
                        direction = dir_match.group(2)
                        if vis_meters == 9999:
                            visibility = 10.0
                        else:
                            visibility = vis_meters / 1000
                        _LOGGER.debug("Parsed directional visibility: %s meters %s = %s km",
                                    vis_meters, direction, visibility)
                        break

                    # Check for SM (statute miles) format - US METAR (e.g., 10SM, 3SM, P6SM)
                    sm_match = re.match(r'^P?(\d+)SM$', part)
                    if sm_match:
                        vis_miles = float(sm_match.group(1))
                        visibility = round(vis_miles * MILES_TO_KM, 1)
                        _LOGGER.debug("Parsed SM visibility: %s SM = %s km", vis_miles, visibility)
                        break

                    # Check for fractional SM format (e.g., 1/2SM, M1/4SM, 3/4SM).
                    # M prefix = "less than"; report the boundary value.
                    # Also handles mixed fractions where previous part is whole number
                    frac_sm_match = re.match(r'^M?(\d+)/(\d+)SM$', part)
                    if frac_sm_match:
                        numerator = float(frac_sm_match.group(1))
                        denominator = float(frac_sm_match.group(2))
                        if denominator > 0:
                            vis_miles = numerator / denominator

                            # Check if previous part was a whole number (mixed fraction like "1 1/2SM")
                            # idx from enumerate is safe, unlike .index() which could raise ValueError
                            if idx > 0:
                                prev_part = raw_parts[wind_index + 1 + idx - 1]
                                # Previous part must be a standalone single digit (1-9)
                                # Not a runway code, wind, or other METAR element
                                if (prev_part.isdigit() and
                                    len(prev_part) <= 2 and
                                    not prev_part.startswith('R')):
                                    vis_miles += float(prev_part)
                                    _LOGGER.debug("Parsed mixed fractional SM visibility: %s %s/%s SM = %s km",
                                                prev_part, int(numerator), int(denominator), vis_miles)

                            visibility = round(vis_miles * MILES_TO_KM, 1)
                            if vis_miles == numerator / denominator:
                                _LOGGER.debug("Parsed fractional SM visibility: %s/%s SM = %s km",
                                            int(numerator), int(denominator), visibility)
                        break

                    # Stop at cloud, temperature, or pressure parts
                    if (part.startswith(('FEW', 'SCT', 'BKN', 'OVC', 'SKC', 'CLR', 'NSC', 'VV')) or
                        '/' in part or part.startswith('Q') or part.startswith('A')):
                        break

        # Parse weather phenomena using the proper method that handles intensity
        weather_description = self.parse_weather()

        # The raw string only yields the ICAO code as the station name. The real
        # airport name (when the data source provides one) is layered in by the
        # api_client after parsing.
        station_name = None
        if self.raw_metar:
            parts = self.raw_metar.split()
            if parts:
                icao = parts[0]
                if len(icao) == 4 and icao.isalnum():
                    station_name = icao

        data = {
            "raw_metar": self.raw_metar,
            "station_name": station_name,  # May be None for AVWX fallback
            # Convert CloudLayer objects to dicts for consistency with AWC client
            "cloud_layers": [
                {"coverage": l.coverage, "height": l.height, "type": l.type}
                for l in cloud_layers
            ],
            "cloud_coverage_state": self.parse_cloud_coverage(),
            "cloud_coverage_height": self.parse_cloud_height(),
            "cloud_coverage_type": self.parse_cloud_type(),
            "weather": weather_description,
            "weather_groups": self.parse_weather_groups(),
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
            # Parse AUTO from raw METAR (AVWX doesn't have .auto attribute)
            "auto": "AUTO" in self.raw_metar,
        }

        _LOGGER.debug("Parsed METAR data: %s", data)
        return data

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
                            result["speed"] = round(speed_kt * KNOTS_TO_KMH, 1)
                        else:
                            _LOGGER.warning("Invalid wind speed: %s kt", speed_kt)
                            continue

                        if vrb_match.group(2):
                            gust_kt = int(vrb_match.group(2))
                            if 0 <= gust_kt <= 300:  # reasonable maximum for gusts
                                result["gust"] = round(gust_kt * KNOTS_TO_KMH, 1)
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

                        # Handle calm wind (00000KT) - direction has no meaning
                        if speed_kt == 0 and direction == 0:
                            result["direction"] = None
                            result["speed"] = 0.0
                            _LOGGER.debug("Parsed calm wind: 00000KT")
                            continue

                        # Validate wind direction
                        if 0 <= direction <= 360:
                            result["direction"] = float(direction)
                        else:
                            _LOGGER.warning("Invalid wind direction: %s°", direction)
                            continue

                        # Validate wind speed
                        if 0 <= speed_kt <= 200:  # reasonable maximum for knots
                            result["speed"] = round(speed_kt * KNOTS_TO_KMH, 1)
                        else:
                            _LOGGER.warning("Invalid wind speed: %s kt", speed_kt)
                            continue

                        if match.group(3):
                            gust_kt = int(match.group(3))
                            if 0 <= gust_kt <= 300:  # reasonable maximum for gusts
                                result["gust"] = round(gust_kt * KNOTS_TO_KMH, 1)
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
                            result["speed"] = round(speed_ms * MPS_TO_KMH, 1)
                        else:
                            _LOGGER.warning("Invalid wind speed: %s m/s", speed_ms)
                            continue

                        if vrb_match.group(2):
                            gust_ms = int(vrb_match.group(2))
                            if 0 <= gust_ms <= 150:  # reasonable maximum for gusts in m/s
                                result["gust"] = round(gust_ms * MPS_TO_KMH, 1)
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

                        # Handle calm wind (00000MPS) - direction has no meaning
                        if speed_ms == 0 and direction == 0:
                            result["direction"] = None
                            result["speed"] = 0.0
                            _LOGGER.debug("Parsed calm wind: 00000MPS")
                            continue

                        # Validate wind direction
                        if 0 <= direction <= 360:
                            result["direction"] = float(direction)
                        else:
                            _LOGGER.warning("Invalid wind direction: %s°", direction)
                            continue

                        # Validate wind speed
                        if 0 <= speed_ms <= 100:  # reasonable maximum for m/s
                            result["speed"] = round(speed_ms * MPS_TO_KMH, 1)
                        else:
                            _LOGGER.warning("Invalid wind speed: %s m/s", speed_ms)
                            continue

                        if match.group(3):
                            gust_ms = int(match.group(3))
                            if 0 <= gust_ms <= 150:  # reasonable maximum for gusts in m/s
                                result["gust"] = round(gust_ms * MPS_TO_KMH, 1)
                            else:
                                _LOGGER.warning("Invalid wind gust: %s m/s", gust_ms)

                        _LOGGER.debug(
                            "Parsed MPS wind: %s° at %s m/s (%s km/h)",
                            direction,
                            speed_ms,
                            result["speed"]
                        )

                # Parse variable wind direction (format: 180V240 or 10V90)
                elif 'V' in part and 5 <= len(part) <= 7:
                    match = re.match(r'(\d{2,3})V(\d{2,3})', part)
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

                    try:
                        temp_val = float(temp_str.replace('M', '-'))
                        dew_val = float(dew_str.replace('M', '-'))
                    except ValueError:
                        # Token merely looked like temp/dew: fractional
                        # visibility "1/2SM" splits to "1"/"2SM". Keep
                        # scanning for the real group.
                        continue

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
                    # Convert inHg to hPa
                    hpa = round(inhg * INHG_TO_HPA, 1)
                    _LOGGER.debug("Parsed A pressure: %s inHg = %s hPa", inhg, hpa)
                    return hpa
                except ValueError:
                    continue

        return None

    def _calculate_humidity(self, temp: Optional[float], dew: Optional[float]) -> Optional[float]:
        """Calculate relative humidity from temperature and dew point.

        Delegates to shared utility function for consistency with AWC client.
        """
        return calculate_humidity(temp, dew)
