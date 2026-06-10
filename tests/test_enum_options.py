"""Guard: every slug the parser can emit must be inside the ENUM options.

Home Assistant raises ValueError if an ENUM sensor's native_value is not in its
declared ``options`` list. These tests fail fast if the slug maps and the option
lists ever drift apart.
"""

from custom_components.ha_metar_weather.const import (
    CLOUD_COVERAGE,
    CLOUD_COVERAGE_OPTIONS,
    CLOUD_TYPES,
    CLOUD_TYPE_OPTIONS,
    RUNWAY_SURFACE_CODES,
    RUNWAY_SURFACE_OPTIONS,
    RUNWAY_COVERAGE_CODES,
    RUNWAY_COVERAGE_OPTIONS,
)


def test_cloud_coverage_slugs_within_options():
    produced = set(CLOUD_COVERAGE.values()) | {"clear"}
    assert produced <= set(CLOUD_COVERAGE_OPTIONS)


def test_cloud_type_slugs_within_options():
    produced = set(CLOUD_TYPES.values()) | {"none"}
    assert produced <= set(CLOUD_TYPE_OPTIONS)


def test_runway_surface_slugs_within_options():
    produced = set(RUNWAY_SURFACE_CODES.values()) | {"snow_closed", "cleared", "unknown"}
    assert produced <= set(RUNWAY_SURFACE_OPTIONS)


def test_runway_coverage_slugs_within_options():
    produced = set(RUNWAY_COVERAGE_CODES.values()) | {"cov_91_100", "cov_0", "unknown"}
    assert produced <= set(RUNWAY_COVERAGE_OPTIONS)


def test_options_have_no_duplicates():
    for options in (
        CLOUD_COVERAGE_OPTIONS,
        CLOUD_TYPE_OPTIONS,
        RUNWAY_SURFACE_OPTIONS,
        RUNWAY_COVERAGE_OPTIONS,
    ):
        assert len(options) == len(set(options)), f"duplicate slug in {options}"
