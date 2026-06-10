"""Tests for the cloud_layers composite state (issues #11 and #12).

Issue #11: a clear-sky report (CLR/SKC/NSC/NCD/CAVOK, also VV///) produced
"clr Noneft" - the formatter appended a None height. Issue #12: the state was
built from raw English slugs ("scattered 7500ft") which HA's frontend cannot
translate, so French/German/Russian installs saw English. The state is now
composed server-side from the integration's own translation entries
(entity.sensor.cloud_layers.state); these tests cover the pure formatter and
the parser layers that feed it.
"""

import json
from pathlib import Path

from custom_components.ha_metar_weather.metar_parser import MetarParser
from custom_components.ha_metar_weather.sensor import format_cloud_layers

TRANSLATIONS = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "ha_metar_weather"
    / "translations"
)


def _names(lang: str) -> dict[str, str]:
    """Per-layer names exactly as async_cloud_layer_names() would build them."""
    data = json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))
    sensor = data["entity"]["sensor"]
    names = dict(sensor["cloud_layers"]["state"])
    for slug, text in sensor["cloud_coverage_type"]["state"].items():
        names.setdefault(slug, text)
    return names


def _layers(raw: str) -> list[dict]:
    return MetarParser(raw).get_parsed_data()["cloud_layers"]


# --- issue #11: heightless layers must not render "Noneft" --------------------


def test_clr_layer_renders_without_height():
    layers = _layers("METAR KAUS 101153Z 18007KT 10SM CLR 26/19 A3001")
    state = format_cloud_layers(layers, _names("en"))
    assert state == "No clouds below 12,000 ft"
    assert "None" not in state


def test_cavok_renders_without_height():
    layers = _layers("METAR UUEE 100600Z 28003MPS CAVOK 25/13 Q1013 NOSIG")
    state = format_cloud_layers(layers, _names("en"))
    assert state == "Ceiling and visibility OK"


def test_undefined_vertical_visibility_renders_without_height():
    layers = _layers("METAR EDDF 100620Z 24003KT 0150 R25R/0900N FG VV/// 11/11 Q1025")
    state = format_cloud_layers(layers, _names("en"))
    assert state == "Vertical visibility"


def test_vertical_visibility_with_height_keeps_height():
    layers = _layers("METAR EDDF 100620Z 24003KT 0150 FG VV002 11/11 Q1025")
    assert format_cloud_layers(layers, _names("en")) == "Vertical visibility 200ft"


def test_no_sky_group_yields_none_not_clear():
    """A report with no sky-condition group has no cloud data - claiming
    "Clear" would be wrong (stations reporting clear sky send CLR/SKC/etc.)."""
    assert format_cloud_layers([], _names("en")) is None
    assert format_cloud_layers(None, _names("fr")) is None
    layers = _layers("METAR LFRC 101200Z AUTO 27010KT 9999 12/08 Q1015")
    assert format_cloud_layers(layers, _names("en")) is None


# --- AUTO slash placeholders (failed/partial ceilometer) -----------------------


def test_slash_group_with_cb_reports_convection():
    """'//////CB' means a cumulonimbus was detected with amount/base unknown -
    dropping it rendered 'Clear' while a CB sat overhead."""
    layers = _layers("METAR LFGJ 101900Z AUTO 19005KT 9999 //////CB 24/15 Q1014")
    assert format_cloud_layers(layers, _names("en")) == "Unknown (Cumulonimbus)"
    assert format_cloud_layers(layers, _names("fr")) == "Inconnu (Cumulonimbus)"


def test_slash_group_with_height_keeps_height():
    layers = _layers("METAR LFGJ 101900Z AUTO 19005KT 9999 ///015/// 24/15 Q1014")
    assert format_cloud_layers(layers, _names("en")) == "Unknown 1500ft"


def test_all_slash_group_reports_unknown_not_clear():
    layers = _layers("METAR LFGJ 101900Z AUTO 19005KT 9999 ////// 24/15 Q1014")
    assert format_cloud_layers(layers, _names("en")) == "Unknown"


def test_prefix_group_with_slash_height_renders_bare_name():
    """'BKN///' - amount known, base unknown: no 'Noneft', no fake height."""
    layers = _layers("METAR LFGJ 101900Z AUTO 19005KT 9999 BKN/// 24/15 Q1014")
    assert format_cloud_layers(layers, _names("en")) == "Broken"


def test_amount_unknown_slug_is_in_enum_options():
    """cloud_coverage_state (ENUM) shows the first layer's coverage slug; an
    option missing from the closed vocabulary makes HA reject the state."""
    from custom_components.ha_metar_weather.const import CLOUD_COVERAGE_OPTIONS
    from custom_components.ha_metar_weather.metar_parser import MetarParser as MP

    parsed = MP("METAR LFGJ 101900Z AUTO 19005KT 9999 //////CB 24/15 Q1014").get_parsed_data()
    assert parsed["cloud_coverage_state"] == "amount_unknown"
    assert "amount_unknown" in CLOUD_COVERAGE_OPTIONS
    assert parsed["cloud_coverage_type"] == "cumulonimbus"


# --- issue #12: state must be localized ----------------------------------------


def test_layers_localized_french():
    """Gsyltc's exact expectation: 'Épars 7500ft, Fragmenté 25000ft'."""
    layers = _layers("METAR LFLC 101000Z 33008KT 9999 SCT075 BKN250 18/04 Q1021")
    assert format_cloud_layers(layers, _names("fr")) == "Épars 7500ft, Fragmenté 25000ft"


def test_layers_localized_english():
    layers = _layers("METAR LFLC 100600Z AUTO 06003KT 9999 FEW046 BKN058 OVC074 14/08 Q1020")
    assert (
        format_cloud_layers(layers, _names("en"))
        == "Few 4600ft, Broken 5800ft, Overcast 7400ft"
    )


def test_clear_sky_localized_french():
    layers = _layers("METAR KAUS 101153Z 18007KT 10SM CLR 26/19 A3001")
    assert format_cloud_layers(layers, _names("fr")) == "Pas de nuages sous 12 000 ft"


def test_cloud_type_suffix_localized():
    layers = _layers("METAR LFPG 101030Z 25012KT 9999 SCT045TCU 22/14 Q1015")
    assert (
        format_cloud_layers(layers, _names("en")) == "Scattered 4500ft (Towering cumulus)"
    )
    assert (
        format_cloud_layers(layers, _names("fr")) == "Épars 4500ft (Cumulus bourgeonnant)"
    )


def test_german_type_suffix_has_no_nested_parentheses():
    """de towering_cumulus is 'Mächtige Quellwolken (Cumulus congestus)' in the
    ENUM sensor; the layer-list form must use the stripped short name or the
    formatter's parentheses nest."""
    layers = _layers("METAR EDDM 101030Z 25012KT 9999 SCT045TCU 22/14 Q1015")
    state = format_cloud_layers(layers, _names("de"))
    assert state == "Aufgelockert 4500ft (Mächtige Quellwolken)"
    assert "((" not in state and "))" not in state


# --- robustness ----------------------------------------------------------------


def test_unknown_slug_falls_back_to_slug_itself():
    layers = [{"coverage": "mystery", "height": 1200, "type": None}]
    assert format_cloud_layers(layers, {}) == "mystery 1200ft"


def test_empty_names_never_raises():
    layers = _layers("METAR KAUS 101153Z 18007KT 10SM CLR 26/19 A3001")
    assert format_cloud_layers(layers, {}) == "clr"


def test_malformed_layers_are_skipped():
    layers = [
        "not-a-dict",
        {"height": 100},  # no coverage
        {"coverage": "few", "height": 3000, "type": None},
    ]
    assert format_cloud_layers(layers, _names("en")) == "Few 3000ft"


def test_degenerate_many_layer_report_fits_state_limit():
    """Localized names can overflow HA's 255-char state limit; a rejected
    state would freeze the sensor, so the formatter degrades gracefully."""
    layers = [
        {"coverage": "broken", "height": 5800, "type": "towering_cumulus"}
        for _ in range(8)
    ]
    state = format_cloud_layers(layers, _names("ru"))
    assert state is not None
    assert len(state) <= 255
    # Type suffixes are dropped before any hard truncation.
    assert "(" not in state


def test_all_coverage_and_type_slugs_have_translations():
    """Every slug the parser can emit must resolve in every language."""
    from custom_components.ha_metar_weather.const import CLOUD_COVERAGE, CLOUD_TYPES

    for lang in ("en", "de", "ru", "fr"):
        names = _names(lang)
        for slug in list(CLOUD_COVERAGE.values()) + ["clear", "vertical_visibility"]:
            assert slug in names, f"{lang}: missing coverage {slug}"
        for slug in CLOUD_TYPES.values():
            assert slug in names, f"{lang}: missing type {slug}"
