"""Guard: weather slugs the parser emits must have a translation entry.

The weather sensor is not an ENUM (open vocabulary), so there is no HA-level
safety net like ``test_enum_options.py``. Without this guard, adding a phenomenon
or a recent code without a matching translation would silently show users the raw
slug - the exact bug phase 2 fixes.
"""

import json
from pathlib import Path

from custom_components.ha_metar_weather.const import (
    WEATHER_PHENOMENON_CODES,
    RECENT_WEATHER_CODES,
)

TR_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "ha_metar_weather"
    / "translations"
)
LANGS = ("en", "de", "ru", "fr")


def _weather_keys(lang: str) -> set[str]:
    data = json.loads((TR_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    return set(data["entity"]["sensor"]["weather"]["state"])


def test_clear_present():
    assert "clear" in _weather_keys("en")


def test_each_phenomenon_and_intensities_translated():
    keys = _weather_keys("en")
    missing = []
    for slug in WEATHER_PHENOMENON_CODES.values():
        for combo in (slug, f"light_{slug}", f"heavy_{slug}", f"vicinity_{slug}"):
            if combo not in keys:
                missing.append(combo)
    assert not missing, f"untranslated weather slugs: {missing}"


def test_every_recent_code_translated():
    keys = _weather_keys("en")
    missing = [
        f"recent_{slug}"
        for slug in RECENT_WEATHER_CODES.values()
        if f"recent_{slug}" not in keys
    ]
    assert not missing, f"untranslated recent slugs: {missing}"


def test_weather_keys_identical_across_languages():
    base = _weather_keys("en")
    for lang in LANGS[1:]:
        assert _weather_keys(lang) == base, f"{lang} weather keys differ from en"
