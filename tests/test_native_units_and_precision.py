"""Tests for true-native unit detection and round-trip display precision.

Issue #7 follow-up: a report of 09001KT (exactly 1 knot) was displayed as
"1.03 kn". The integration stores values in base units (km/h, km, hPa); the
old code rounded the converted value to 1 decimal at parse time, so HA's
conversion back to the unit the report used could no longer reproduce the
reported number (1 kt -> 1.9 km/h -> 1.026 kn). Values are now stored at
near-full precision and rounding happens only at display time, so the
round-trip must be exact.

Also covers detect_native_units(): the "Native (METAR)" display mode follows
the units the station itself transmits (KT vs MPS, meters vs SM, Q vs A).
"""

import pytest

from homeassistant.util.unit_conversion import (
    DistanceConverter,
    PressureConverter,
    SpeedConverter,
)

from custom_components.ha_metar_weather.awc_client import AWCApiClient
from custom_components.ha_metar_weather.metar_parser import MetarParser
from custom_components.ha_metar_weather.sensor import SENSOR_TYPES
from custom_components.ha_metar_weather.utils import detect_native_units


RAW_LFLC = (
    "METAR LFLC 100600Z AUTO 06003KT 020V130 9999 FEW046 BKN058 OVC074 "
    "14/08 Q1020 TEMPO FEW045TCU BKN050 BECMG 31010KT"
)
RAW_KJFK = "METAR KJFK 100551Z 22006KT 10SM SCT250 18/14 A3002 RMK AO2 SLP166"
RAW_UUEE = "METAR UUEE 100600Z 28003MPS 240V330 CAVOK 25/13 Q1013 NOSIG"
RAW_NICKDUINO = (
    "METAR LFLC 100100Z AUTO 09001KT 9999 FEW066 BKN110 OVC130 12/08 Q1020 NOSIG"
)


# --- detect_native_units ------------------------------------------------------


def test_detect_icao_station():
    units = detect_native_units(RAW_LFLC)
    assert units["wind_speed"] == "kn"
    assert units["visibility"] == "m"
    assert units["pressure"] == "hPa"
    assert units["temperature"] == "°C"
    assert units["altitude"] == "ft"


def test_detect_us_station():
    units = detect_native_units(RAW_KJFK)
    assert units["wind_speed"] == "kn"
    assert units["visibility"] == "mi"
    assert units["pressure"] == "inHg"


def test_detect_mps_station_with_cavok():
    units = detect_native_units(RAW_UUEE)
    assert units["wind_speed"] == "m/s"
    assert units["visibility"] == "m"
    assert units["pressure"] == "hPa"


def test_detect_fallback_when_no_report():
    for raw in (None, ""):
        units = detect_native_units(raw)
        assert units["wind_speed"] == "kn"
        assert units["visibility"] == "m"
        assert units["pressure"] == "hPa"


def test_detect_vrb_and_gust_wind_groups():
    assert detect_native_units("METAR XXXX 100600Z VRB03KT 9999 Q1013")[
        "wind_speed"
    ] == "kn"
    assert detect_native_units("METAR XXXX 100600Z VRB03G15MPS 9999 Q1013")[
        "wind_speed"
    ] == "m/s"
    assert detect_native_units("METAR XXXX 100600Z 00000KT 9999 Q1013")[
        "wind_speed"
    ] == "kn"


def test_detect_fractional_and_prefixed_sm():
    assert detect_native_units("METAR KXXX 100600Z 09005KT M1/4SM FG 10/10 A2992")[
        "visibility"
    ] == "mi"
    assert detect_native_units("METAR KXXX 100600Z 09005KT P6SM 10/05 A2992")[
        "visibility"
    ] == "mi"


def test_detect_directional_meter_visibility():
    assert detect_native_units("METAR XXXX 100600Z 09005KT 3000NE 10/05 Q1013")[
        "visibility"
    ] == "m"
    assert detect_native_units("METAR XXXX 100600Z 09005KT 0800NDV 10/05 Q1013")[
        "visibility"
    ] == "m"


def test_detect_missing_visibility_uses_pressure_group_region():
    # No visibility group at all: the pressure group style decides the region.
    assert detect_native_units("METAR KXXX 100600Z 09005KT 10/05 A2992")[
        "visibility"
    ] == "mi"
    assert detect_native_units("METAR XXXX 100600Z 09005KT 10/05 Q1013")[
        "visibility"
    ] == "m"


def test_detect_ignores_trend_section():
    # The BECMG group carries a KT wind even for an MPS station; only the body
    # before TEMPO/BECMG/RMK may decide.
    raw = "METAR UUEE 100600Z 28003MPS 9999 25/13 Q1013 BECMG 31010KT"
    assert detect_native_units(raw)["wind_speed"] == "m/s"

    # An SM token inside RMK must not turn an ICAO station into a US one.
    raw = "METAR LFLC 100600Z 06003KT 9999 14/08 Q1020 RMK VIS 2SM RWY27"
    assert detect_native_units(raw)["visibility"] == "m"


def test_detect_does_not_mistake_time_or_variable_wind_for_visibility():
    # 100600Z and 020V130 both contain 4-digit runs; neither is a visibility.
    raw = "METAR LFLC 100600Z 06003KT 020V130 14/08 Q1020"
    assert detect_native_units(raw)["visibility"] == "m"  # via Q-group region


def test_detect_wind_unit_from_slash_placeholders():
    """AUTO stations with a failed wind sensor still transmit the unit suffix."""
    assert detect_native_units("ULLI 101230Z /////MPS 6000 BKN020 10/08 Q1009")[
        "wind_speed"
    ] == "m/s"
    assert detect_native_units("METAR XXXX 100600Z /////KT 9999 10/05 Q1013")[
        "wind_speed"
    ] == "kn"
    assert detect_native_units("ULLI 101230Z ///08MPS 6000 BKN020 10/08 Q1009")[
        "wind_speed"
    ] == "m/s"


# --- round-trip precision: stored base unit -> report unit --------------------


def test_one_knot_round_trips_exactly():
    """Regression for the "1.03 kn" report in issue #7."""
    parsed = MetarParser(RAW_NICKDUINO).get_parsed_data()
    assert parsed["wind_speed"] == pytest.approx(1.852, abs=1e-9)
    back = SpeedConverter.convert(parsed["wind_speed"], "km/h", "kn")
    assert back == pytest.approx(1.0, abs=1e-9)


def test_knots_round_trip_across_range():
    for kt in (1, 3, 6, 12, 27, 99, 145):
        raw = f"METAR LFLC 100600Z 090{kt:02d}KT 9999 14/08 Q1020"
        parsed = MetarParser(raw).get_parsed_data()
        back = SpeedConverter.convert(parsed["wind_speed"], "km/h", "kn")
        assert back == pytest.approx(kt, abs=1e-9), f"{kt} kt"


def test_mps_round_trips_exactly():
    parsed = MetarParser(RAW_UUEE).get_parsed_data()
    back = SpeedConverter.convert(parsed["wind_speed"], "km/h", "m/s")
    assert back == pytest.approx(3.0, abs=1e-9)


def test_statute_miles_round_trip_exactly():
    parsed = MetarParser(RAW_KJFK).get_parsed_data()
    assert parsed["visibility"] == pytest.approx(16.09344, abs=1e-9)
    back = DistanceConverter.convert(parsed["visibility"], "km", "mi")
    assert back == pytest.approx(10.0, abs=1e-9)


def test_fractional_sm_round_trips_exactly():
    raw = "METAR KXXX 100600Z 09005KT M1/4SM FG 10/10 A2992"
    parsed = MetarParser(raw).get_parsed_data()
    back = DistanceConverter.convert(parsed["visibility"], "km", "mi")
    assert back == pytest.approx(0.25, abs=1e-9)


def test_us_altimeter_round_trips_to_inhg():
    parsed = MetarParser(RAW_KJFK).get_parsed_data()
    back = PressureConverter.convert(parsed["pressure"], "hPa", "inHg")
    assert back == pytest.approx(30.02, abs=1e-6)


def test_meter_visibility_round_trips_to_meters():
    raw = "METAR LFLC 100600Z 06003KT 0800 FG 10/09 Q1020"
    parsed = MetarParser(raw).get_parsed_data()
    back = DistanceConverter.convert(parsed["visibility"], "km", "m")
    assert back == pytest.approx(800.0, abs=1e-9)


def test_gust_round_trips_exactly():
    parsed = MetarParser(
        "METAR KJFK 100551Z 22012G25KT 10SM SCT250 18/14 A3002"
    ).get_parsed_data()
    assert SpeedConverter.convert(parsed["wind_speed"], "km/h", "kn") == pytest.approx(
        12.0, abs=1e-9
    )
    assert SpeedConverter.convert(parsed["wind_gust"], "km/h", "kn") == pytest.approx(
        25.0, abs=1e-9
    )


def test_vrb_wind_round_trips_exactly():
    parsed = MetarParser(
        "METAR LFLC 100600Z VRB03KT 9999 14/08 Q1020"
    ).get_parsed_data()
    assert parsed["wind_variable_direction"] == "VRB"
    assert SpeedConverter.convert(parsed["wind_speed"], "km/h", "kn") == pytest.approx(
        3.0, abs=1e-9
    )


def test_mps_gust_round_trips_exactly():
    parsed = MetarParser(
        "METAR UUEE 100600Z 28005G10MPS 9999 25/13 Q1013"
    ).get_parsed_data()
    assert SpeedConverter.convert(parsed["wind_gust"], "km/h", "m/s") == pytest.approx(
        10.0, abs=1e-9
    )


# --- trend section must not leak into current conditions -----------------------


def test_trend_wind_does_not_overwrite_observation():
    """BECMG 31010KT is a forecast; the real wind is 06003KT (caught live)."""
    parsed = MetarParser(RAW_LFLC).get_parsed_data()
    assert SpeedConverter.convert(parsed["wind_speed"], "km/h", "kn") == pytest.approx(
        3.0, abs=1e-9
    )
    assert parsed["wind_direction"] == 60.0


def test_trend_cavok_does_not_wipe_current_weather():
    """BECMG CAVOK forecasts improvement; it is raining NOW."""
    parsed = MetarParser(
        "METAR EGLL 101220Z 25010KT 4000 -RA BKN010 12/10 Q1008 BECMG CAVOK"
    ).get_parsed_data()
    assert parsed["cavok"] is False
    assert parsed["visibility"] == pytest.approx(4.0, abs=1e-9)
    assert parsed["weather"] == "light_rain"
    assert parsed["weather_groups"]


def test_awc_numerics_round_trip():
    """The AWC overlay path must preserve precision exactly like the parser."""
    awc = AWCApiClient.parse_awc_response(
        {
            "rawOb": RAW_NICKDUINO,
            "name": "Clermont-Ferrand",
            "obsTime": 1768003200,
            "temp": 12,
            "dewp": 8,
            "wdir": 90,
            "wspd": 1,
            "visib": "6+",
            "altim": 1020,
        }
    )
    assert SpeedConverter.convert(awc["wind_speed"], "km/h", "kn") == pytest.approx(
        1.0, abs=1e-9
    )
    # AWC "6+" is quantized; the merge policy prefers the parser's exact 9999,
    # but the fallback value itself must still round-trip to 6 SM.
    assert DistanceConverter.convert(awc["visibility"], "km", "mi") == pytest.approx(
        6.0, abs=1e-9
    )


# --- display precision is suggested, not baked into the value -----------------


def test_measurement_sensors_suggest_display_precision():
    expected = {
        "temperature": 1,
        "dew_point": 1,
        "wind_speed": 1,
        "wind_gust": 1,
        "wind_direction": 0,
        "visibility": 1,
        "pressure": 1,
        "humidity": 1,
        "cloud_coverage_height": 0,
    }
    by_key = {d.key: d for d in SENSOR_TYPES}
    for key, precision in expected.items():
        assert by_key[key].suggested_display_precision == precision, key
