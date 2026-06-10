"""Unit tests for MetarParser.

The parser is a pure ``raw METAR string -> dict`` transform. These tests pin
the textual (weather / clouds / trend / runway) and numeric output so both the
AWC and AVWX data paths can rely on a single parser (see issue #3).
"""

import pytest

from custom_components.ha_metar_weather.metar_parser import MetarParser


def parse(raw: str) -> dict:
    return MetarParser(raw).get_parsed_data()


def test_parser_accepts_raw_string():
    """MetarParser is constructed from a raw METAR string, not an object."""
    data = parse("KJFK 121651Z 18010KT 10SM FEW020 22/18 A2992")
    assert data["raw_metar"] == "KJFK 121651Z 18010KT 10SM FEW020 22/18 A2992"


def test_light_rain_weather():
    data = parse("KJFK 121651Z 18010KT 10SM -RA FEW020 BKN040 22/18 A2992")
    assert data["weather"] == "light_rain"


def test_heavy_thunderstorm_rain():
    data = parse("UUEE 121630Z 24008MPS 9999 +TSRA SCT020CB BKN040 18/12 Q1009 NOSIG")
    assert data["weather"] == "heavy_thunderstorm_rain"


def test_shower_rain_descriptor():
    data = parse("EGLL 121620Z 25015KT 9999 SHRA BKN012 14/11 Q1007")
    assert data["weather"] == "showers_rain"


def test_moderate_rain_has_no_intensity_token():
    data = parse("EGLL 121620Z 25015KT 9999 RA BKN012 14/11 Q1007")
    assert data["weather"] == "rain"


def test_no_weather_is_clear():
    data = parse("KLAX 121653Z 26012KT 10SM 24/12 A3001")
    assert data["weather"] == "clear"


def test_cavok_weather():
    data = parse("EGLL 121620Z 25015KT CAVOK 15/08 Q1020")
    # CAVOK means no significant weather -> the weather slug is 'clear'.
    assert data["weather"] == "clear"
    assert data["cavok"] is True


def test_weather_groups_structured():
    data = parse("UUEE 121630Z 24008MPS 9999 +TSRA BKN040 18/12 Q1009 NOSIG")
    groups = data["weather_groups"]
    assert groups == [{
        "intensity": "heavy",
        "descriptor": "thunderstorm",
        "phenomena": ["rain"],
        "recent": False,
        "raw": "+TSRA",
    }]


def test_cloud_coverage_state_is_first_layer():
    data = parse("KJFK 121651Z 18010KT 10SM -RA FEW020 BKN040 22/18 A2992")
    assert data["cloud_coverage_state"] == "few"


def test_cloud_coverage_clear_when_no_layers():
    data = parse("KLAX 121653Z 26012KT 10SM 24/12 A3001")
    assert data["cloud_coverage_state"] == "clear"
    assert data["cloud_coverage_type"] == "none"


def test_cloud_layers_height_and_type():
    data = parse("UUEE 121630Z 24008MPS 9999 +TSRA SCT020CB BKN040 18/12 Q1009 NOSIG")
    layers = data["cloud_layers"]
    assert layers[0]["coverage"] == "scattered"
    assert layers[0]["height"] == 2000
    assert layers[0]["type"] == "cumulonimbus"


def test_trend_nosig():
    data = parse("UUEE 121630Z 24008MPS 9999 BKN040 18/12 Q1009 NOSIG")
    assert data["trend"] == "NOSIG"


def test_trend_tempo_segment():
    data = parse("EGLL 121620Z 25015KT 9999 BKN020 14/11 Q1007 TEMPO 4000 RA BKN012")
    assert data["trend"] is not None
    assert data["trend"].startswith("TEMPO")
    assert "4000" in data["trend"]


def test_trend_none_when_absent():
    data = parse("KLAX 121653Z 26012KT 10SM 24/12 A3001")
    assert data["trend"] is None


def test_trend_ignores_tempo_inside_rmk():
    """TEMPO/BECMG appearing inside the RMK section is not a trend group."""
    data = parse("KJFK 121651Z 18010KT 10SM BKN040 22/18 A2992 RMK AO2 TEMPO TOKEN")
    assert data["trend"] is None


def test_numeric_temperature_dew():
    data = parse("KJFK 121651Z 18010KT 10SM FEW020 22/18 A2992")
    assert data["temperature"] == pytest.approx(22.0)
    assert data["dew_point"] == pytest.approx(18.0)


def test_numeric_pressure_inhg_to_hpa():
    data = parse("KJFK 121651Z 18010KT 10SM FEW020 22/18 A2992")
    # A2992 = 29.92 inHg -> hPa
    assert data["pressure"] == pytest.approx(1013.2, abs=0.1)


def test_numeric_pressure_qnh():
    data = parse("UUEE 121630Z 24008MPS 9999 BKN040 18/12 Q1009 NOSIG")
    assert data["pressure"] == pytest.approx(1009.0)


def test_numeric_wind_knots_to_kmh():
    data = parse("KJFK 121651Z 18010KT 10SM FEW020 22/18 A2992")
    assert data["wind_direction"] == pytest.approx(180.0)
    # 10 kt * 1.852
    assert data["wind_speed"] == pytest.approx(18.5, abs=0.1)


def test_visibility_statute_miles():
    data = parse("KJFK 121651Z 18010KT 10SM FEW020 22/18 A2992")
    # 10 SM * 1.60934
    assert data["visibility"] == pytest.approx(16.1, abs=0.1)


def test_runway_state_parsed():
    data = parse("UUEE 121630Z 24008MPS 9999 BKN040 18/12 Q1009 R06R/290060 NOSIG")
    runways = data["runway_states"]
    assert "06R" in runways
    assert runways["06R"]["surface"] == "wet"
    assert runways["06R"]["coverage"] == "cov_51_100"
    assert runways["06R"]["friction"] == pytest.approx(0.6)


def test_station_name_falls_back_to_icao():
    """With only a raw string, the parser yields the ICAO as the name.

    The real airport name is layered in by the api_client from the source.
    """
    data = parse("KJFK 121651Z 18010KT 10SM FEW020 22/18 A2992")
    assert data["station_name"] == "KJFK"


def test_temp_dew_survives_fractional_visibility_token():
    """Regression: "1/2SM" splits to "1"/"2SM" and used to abort the whole
    temp/dew scan via ValueError, losing the real 12/12 group."""
    data = parse("KLAX 121651Z 18005KT 1/2SM FG 12/12 A3001")
    assert data["temperature"] == pytest.approx(12.0)
    assert data["dew_point"] == pytest.approx(12.0)


def test_temp_dew_survives_less_than_fraction_token():
    data = parse("KLAX 121651Z 18005KT M1/4SM FG 12/12 A3001")
    assert data["temperature"] == pytest.approx(12.0)
    assert data["dew_point"] == pytest.approx(12.0)


def test_visibility_less_than_fraction():
    """M1/4SM means "less than 1/4 SM"; report the boundary value."""
    data = parse("KLAX 121651Z 18005KT M1/4SM FG 12/12 A3001")
    assert data["visibility"] == pytest.approx(0.4, abs=0.05)


def test_visibility_p6sm():
    data = parse("KJFK 121651Z 18010KT P6SM FEW020 22/18 A2992")
    assert data["visibility"] == pytest.approx(9.7, abs=0.1)


def test_visibility_9999_is_10_km():
    data = parse("UUEE 121630Z 24008MPS 9999 BKN040 18/12 Q1009 NOSIG")
    assert data["visibility"] == pytest.approx(10.0)


def test_wind_mps_exact_kmh():
    """8 m/s = 28.8 km/h exactly; must not be quantized through knots."""
    data = parse("UUEE 121630Z 24008MPS 9999 BKN040 18/12 Q1009 NOSIG")
    assert data["wind_speed"] == pytest.approx(28.8)
