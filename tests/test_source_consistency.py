"""Regression tests for issue #3: AWC and AVWX must produce identical output.

The bug: the AWC (primary) path emitted raw codes ("-RA", "FEW") while the AVWX
(fallback) path emitted parsed prose ("Light Rain", "Few (1-2 oktas)"), so the
sensor state flipped representation depending on which source served the cycle.

The fix: BOTH paths derive every textual field from the same MetarParser fed by
the raw METAR. The AWC path then overlays AWC's authoritative numeric values.
``merge_awc_numerics`` is that overlay step; this module proves the invariant.
"""

import pytest

from custom_components.ha_metar_weather.metar_parser import MetarParser
from custom_components.ha_metar_weather.api_client import merge_awc_numerics
from custom_components.ha_metar_weather.awc_client import AWCApiClient


RAW = "KJFK 121651Z 18010KT 10SM -RA FEW020 BKN040 22/18 A2992"

# What AWC's JSON would give us for the same observation: authoritative numerics
# plus the real station name and observation time. No textual fields.
AWC_META = {
    "raw_metar": RAW,
    "station_name": "John F Kennedy Intl",
    "observation_time": "2026-06-12T16:51:00+00:00",
    "temperature": 22.0,
    "dew_point": 18.0,
    "humidity": 78.0,
    "wind_speed": 18.5,
    "wind_direction": 180.0,
    "wind_gust": None,
    "wind_variable_direction": None,
    "visibility": 16.1,
    "pressure": 1013.0,
}


def test_textual_fields_identical_across_sources():
    """Weather/clouds/trend/runway are byte-identical whatever the source."""
    parsed = MetarParser(RAW).get_parsed_data()
    merged = merge_awc_numerics(parsed, AWC_META)

    for field in (
        "weather",
        "cloud_coverage_state",
        "cloud_coverage_type",
        "cloud_layers",
        "trend",
        "runway_states",
        "cavok",
    ):
        assert merged[field] == parsed[field], f"textual field {field} diverged"

    # And the concrete value the user reported as broken:
    assert merged["weather"] == "Light Rain"
    assert merged["cloud_coverage_state"] == "Few (1-2 oktas)"


def test_numeric_fields_come_from_awc():
    """AWC numerics are authoritative (they handle 6+, hPa/inHg, epoch, etc.)."""
    parsed = MetarParser(RAW).get_parsed_data()
    merged = merge_awc_numerics(parsed, AWC_META)

    assert merged["pressure"] == 1013.0  # AWC value, not the inHg-from-raw value
    assert merged["visibility"] == 16.1
    assert merged["temperature"] == 22.0
    assert merged["humidity"] == 78.0


def test_station_name_and_time_preserved_from_awc():
    parsed = MetarParser(RAW).get_parsed_data()
    merged = merge_awc_numerics(parsed, AWC_META)

    assert merged["station_name"] == "John F Kennedy Intl"
    assert merged["observation_time"] == "2026-06-12T16:51:00+00:00"


def test_missing_awc_numeric_keeps_parser_value():
    """If AWC omits a numeric, the parser's raw-derived value is kept."""
    parsed = MetarParser(RAW).get_parsed_data()
    awc_no_pressure = {k: v for k, v in AWC_META.items() if k != "pressure"}
    merged = merge_awc_numerics(parsed, awc_no_pressure)

    assert merged["pressure"] == parsed["pressure"]


def test_out_of_range_awc_numeric_falls_back_to_parser():
    """A corrupt AWC numeric must not clobber a valid parser-derived value.

    Otherwise the later range check in _validate_and_round would null the field
    and the sensor would go unavailable despite correct data being available.
    """
    parsed = MetarParser(RAW).get_parsed_data()
    bad_awc = dict(AWC_META)
    bad_awc["pressure"] = 5000.0  # absurd; outside VALUE_RANGES (900-1100 hPa)
    merged = merge_awc_numerics(parsed, bad_awc)

    assert merged["pressure"] == parsed["pressure"]
    assert merged["pressure"] != 5000.0


def test_non_numeric_awc_value_falls_back_to_parser():
    parsed = MetarParser(RAW).get_parsed_data()
    bad_awc = dict(AWC_META)
    bad_awc["temperature"] = "garbage"
    merged = merge_awc_numerics(parsed, bad_awc)

    assert merged["temperature"] == parsed["temperature"]


def test_real_awc_path_matches_parser():
    """Exercise the real production path: parse_awc_response -> merge.

    Builds a realistic AWC JSON payload, runs it through the actual
    ``parse_awc_response`` (not a hand-written meta dict), and proves the merged
    result is textually identical to a plain parser run on the same raw METAR.
    """
    awc_json = {
        "icaoId": "UUEE",
        "name": "Sheremetyevo",
        "rawOb": "UUEE 121630Z 24008MPS 9999 +TSRA SCT020CB BKN040 18/12 Q1009 NOSIG",
        "obsTime": 1781000000,
        "temp": 18,
        "dewp": 12,
        "wdir": 240,
        "wspd": 16,
        "visib": "6+",
        "altim": 1009,
    }

    awc_meta = AWCApiClient.parse_awc_response(awc_json)
    assert "weather" not in awc_meta  # textual must not leak from AWC

    parsed = MetarParser(awc_json["rawOb"]).get_parsed_data()
    merged = merge_awc_numerics(parsed, awc_meta)

    for field in (
        "weather",
        "cloud_coverage_state",
        "cloud_coverage_type",
        "trend",
        "runway_states",
        "cavok",
    ):
        assert merged[field] == parsed[field]

    assert merged["weather"] == "Heavy Thunderstorm Rain"
    assert merged["pressure"] == 1009.0
    assert merged["station_name"] == "Sheremetyevo"


def test_merge_does_not_mutate_inputs():
    parsed = MetarParser(RAW).get_parsed_data()
    parsed_before = dict(parsed)
    merge_awc_numerics(parsed, AWC_META)
    assert parsed == parsed_before
