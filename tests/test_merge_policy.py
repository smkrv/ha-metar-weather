"""Regression tests for issue #8: AWC's quantized numerics must not clobber
exact values derived from the raw METAR string.

AWC's JSON reports visibility in statute miles, capped and quantized ("6+"),
winds in whole knots (lossy for MPS stations) and altimeter as int hPa (lossy
for US A-group reports). The raw METAR carries the exact values, so the parser
wins whenever it produced one; AWC fills in only when the parser found nothing.
Temperature and dew point stay AWC-first: AWC is never worse than the whole
degrees of the main group and may carry T-group decimals the parser does not
read.
"""

import pytest

from custom_components.ha_metar_weather.metar_parser import MetarParser
from custom_components.ha_metar_weather.api_client import merge_awc_numerics
from custom_components.ha_metar_weather.awc_client import AWCApiClient
from custom_components.ha_metar_weather.utils import calculate_humidity


def _merge(awc_json: dict) -> dict:
    """Run the real production path: parse_awc_response -> parser -> merge."""
    awc_meta = AWCApiClient.parse_awc_response(awc_json)
    parsed = MetarParser(awc_json["rawOb"]).get_parsed_data()
    return merge_awc_numerics(parsed, awc_meta)


# The exact observation from issue #8 (LFLC, 2026-06-09 19:30Z).
LFLC_JSON = {
    "icaoId": "LFLC",
    "name": "Clermont-Ferrand/Auvergne",
    "rawOb": "METAR LFLC 091930Z AUTO 02003KT 9999 BKN062 16/06 Q1020 NOSIG",
    "obsTime": 1781033400,
    "temp": 16,
    "dewp": 6,
    "wdir": 20,
    "wspd": 3,
    "visib": "6+",
    "altim": 1020,
}


def test_issue_8_9999_meters_is_10_km():
    """Raw 9999 means 10 km; AWC's "6+" (9.7 km) must not overwrite it."""
    merged = _merge(LFLC_JSON)
    assert merged["visibility"] == 10.0


def test_cavok_visibility_not_degraded_by_awc():
    """CAVOK implies >= 10 km; AWC still sends visib "6+" for such stations."""
    merged = _merge(
        {
            **LFLC_JSON,
            "rawOb": "METAR LFLC 091930Z AUTO 02003KT CAVOK 16/06 Q1020 NOSIG",
        }
    )
    assert merged["visibility"] == 10.0


def test_awc_visibility_used_when_raw_has_none():
    """Some AUTO reports omit the visibility group; AWC then fills the gap."""
    merged = _merge(
        {
            **LFLC_JSON,
            "rawOb": "METAR LFLC 091930Z AUTO 02003KT 16/06 Q1020 NOSIG",
        }
    )
    # AWC "6+" -> 6 SM -> 9.656064 km (full precision), better than nothing
    assert merged["visibility"] == pytest.approx(9.656064, abs=1e-9)


def test_mps_wind_not_quantized_to_whole_knots():
    """AWC converts 8 m/s to 16 kt (29.6 km/h); the raw value is 28.8 km/h."""
    merged = _merge(
        {
            "icaoId": "UUEE",
            "name": "Sheremetyevo",
            "rawOb": "UUEE 121630Z 24008MPS 9999 SCT020 18/12 Q1009 NOSIG",
            "obsTime": 1781000000,
            "temp": 18,
            "dewp": 12,
            "wdir": 240,
            "wspd": 16,
            "visib": "6+",
            "altim": 1009,
        }
    )
    assert merged["wind_speed"] == 28.8  # 8 m/s * 3.6, not 16 kt * 1.852


def test_us_altimeter_keeps_inhg_precision():
    """A2992 = 29.92 inHg; AWC's int altim (1013 hPa) loses the hundredths."""
    merged = _merge(
        {
            "icaoId": "KJFK",
            "name": "John F Kennedy Intl",
            "rawOb": "KJFK 121651Z 18010KT 10SM FEW020 22/18 A2992",
            "obsTime": 1781000000,
            "temp": 22,
            "dewp": 18,
            "wdir": 180,
            "wspd": 10,
            "visib": "10+",
            "altim": 1013,
        }
    )
    # 29.92 inHg at full precision; converting back must yield 29.92 exactly,
    # while AWC's int hPa would give 29.91 (issue #7 display round-trip).
    assert merged["pressure"] == pytest.approx(1013.2074, abs=1e-3)
    assert merged["pressure"] != 1013.0


def test_temperature_and_dew_point_stay_awc_first():
    """AWC may carry T-group decimals the raw main group lacks."""
    merged = _merge(
        {
            **LFLC_JSON,
            "temp": 16.4,
            "dewp": 6.2,
        }
    )
    assert merged["temperature"] == 16.4
    assert merged["dew_point"] == 6.2


def test_humidity_recomputed_from_merged_pair():
    """Humidity must match whichever temp/dew pair won the merge."""
    merged = _merge({**LFLC_JSON, "temp": 16.4, "dewp": 6.2})
    assert merged["humidity"] == calculate_humidity(16.4, 6.2)


def test_north_wind_direction_zero_survives_awc_parsing():
    """wdir=0 with wind blowing is a valid direction, not a missing one."""
    awc_meta = AWCApiClient.parse_awc_response({**LFLC_JSON, "wdir": 0})
    assert awc_meta["wind_direction"] == 0.0


def test_calm_wind_direction_stays_none():
    """Calm (00000KT): AWC sends wdir=0/wspd=0, but direction has no meaning.

    The parser deliberately yields None; the AWC fallback must not turn calm
    into a "north wind", or the AWC and AVWX paths diverge (issue #3).
    """
    merged = _merge(
        {
            **LFLC_JSON,
            "rawOb": "METAR LFLC 091930Z AUTO 00000KT 9999 BKN062 16/06 Q1020 NOSIG",
            "wdir": 0,
            "wspd": 0,
        }
    )
    assert merged["wind_direction"] is None
    assert merged["wind_speed"] == 0.0


def test_unusable_parser_value_falls_back_to_awc():
    """A garbled Q-group (Q10133 -> 10133 hPa) fails the later range check;
    the valid AWC altimeter must fill in instead of the field going None."""
    merged = _merge(
        {
            **LFLC_JSON,
            "rawOb": "METAR LFLC 091930Z AUTO 02003KT 9999 BKN062 16/06 Q10133 NOSIG",
        }
    )
    assert merged["pressure"] == 1020.0
