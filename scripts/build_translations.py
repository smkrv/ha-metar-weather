"""Generate entity-state translations for translations/<lang>.json.

Single source of truth for the human-readable strings behind the canonical
sensor-state slugs (see docs/localization-roadmap.md). Run from the repo root:

    python scripts/build_translations.py

It rewrites the ``entity.sensor`` section of each language file and leaves the
config-flow / services / exceptions sections untouched. en/de/ru base strings
come from the integration's history; fr comes from community PR #2 (corrected).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LANGS = ("en", "de", "ru", "fr")
TR_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "ha_metar_weather" / "translations"

# --- token tables: slug -> {lang: string} ---------------------------------

CLOUD_COVERAGE = {
    "clear": {"en": "Clear", "de": "Klar", "ru": "Ясно", "fr": "Clair"},
    "clear_sky": {"en": "Clear sky", "de": "Klarer Himmel", "ru": "Ясное небо", "fr": "Ciel dégagé"},
    # ru uses Latin "ft" - the composite cloud_layers state appends "ft" to
    # heights, and mixing scripts within one sensor reads as a glitch.
    "clr": {"en": "No clouds below 12,000 ft", "de": "Keine Wolken unter 12.000 ft", "ru": "Нет облаков ниже 12000 ft", "fr": "Pas de nuages sous 12 000 ft"},
    "no_significant": {"en": "No significant clouds", "de": "Keine bedeutenden Wolken", "ru": "Нет значимых облаков", "fr": "Pas de nuage significatif"},
    "ncd": {"en": "No clouds detected", "de": "Keine Wolken erkannt", "ru": "Облака не обнаружены", "fr": "Aucun nuage détecté"},
    "cavok": {"en": "Ceiling and visibility OK", "de": "Wolkenuntergrenze und Sicht OK", "ru": "Облачность и видимость в норме", "fr": "Plafond et visibilité OK"},
    "few": {"en": "Few (1-2 oktas)", "de": "Wenige Wolken (1-2 Achtel)", "ru": "Малооблачно (1-2 окты)", "fr": "Rares (1-2 octas)"},
    "scattered": {"en": "Scattered (3-4 oktas)", "de": "Aufgelockert (3-4 Achtel)", "ru": "Рассеянная облачность (3-4 окты)", "fr": "Épars (3-4 octas)"},
    "broken": {"en": "Broken (5-7 oktas)", "de": "Bedeckt mit Lücken (5-7 Achtel)", "ru": "Значительная облачность (5-7 окт)", "fr": "Fragmenté (5-7 octas)"},
    "overcast": {"en": "Overcast (8 oktas)", "de": "Bedeckt (8 Achtel)", "ru": "Сплошная облачность (8 окт)", "fr": "Couvert (8 octas)"},
    "vertical_visibility": {"en": "Vertical visibility", "de": "Vertikale Sicht", "ru": "Вертикальная видимость", "fr": "Visibilité verticale"},
    # AUTO slash placeholders (//////, ///015, //////CB): cloud amount unknown.
    "amount_unknown": {"en": "Unknown", "de": "Unbekannt", "ru": "Неизвестно", "fr": "Inconnu"},
}

CLOUD_TYPE = {
    "none": {"en": "None", "de": "Keine", "ru": "Нет", "fr": "Aucun"},
    "cumulonimbus": {"en": "Cumulonimbus", "de": "Cumulonimbus", "ru": "Кучево-дождевые", "fr": "Cumulonimbus"},
    "towering_cumulus": {"en": "Towering cumulus", "de": "Mächtige Quellwolken (Cumulus congestus)", "ru": "Мощно-кучевые", "fr": "Cumulus bourgeonnant"},
    "cirrus": {"en": "Cirrus", "de": "Cirrus", "ru": "Перистые", "fr": "Cirrus"},
    "cirrostratus": {"en": "Cirrostratus", "de": "Cirrostratus", "ru": "Перисто-слоистые", "fr": "Cirrostratus"},
    "cirrocumulus": {"en": "Cirrocumulus", "de": "Cirrocumulus", "ru": "Перисто-кучевые", "fr": "Cirrocumulus"},
    "altostratus": {"en": "Altostratus", "de": "Altostratus", "ru": "Высокослоистые", "fr": "Altostratus"},
    "altocumulus": {"en": "Altocumulus", "de": "Altocumulus", "ru": "Высококучевые", "fr": "Altocumulus"},
    "nimbostratus": {"en": "Nimbostratus", "de": "Nimbostratus", "ru": "Слоисто-дождевые", "fr": "Nimbostratus"},
    "stratocumulus": {"en": "Stratocumulus", "de": "Stratocumulus", "ru": "Слоисто-кучевые", "fr": "Stratocumulus"},
    "stratus": {"en": "Stratus", "de": "Stratus", "ru": "Слоистые", "fr": "Stratus"},
    "cumulus": {"en": "Cumulus", "de": "Cumulus", "ru": "Кучевые", "fr": "Cumulus"},
}


def _strip_parenthetical(strings: dict[str, str]) -> dict[str, str]:
    """Drop a trailing ' (...)' explanation: too long for composite lists."""
    return {lang: re.sub(r"\s*\([^)]*\)$", "", text) for lang, text in strings.items()}


# Per-layer names for the composite cloud_layers state ("Scattered 5800ft,
# Broken 8400ft (Cumulonimbus)"). The frontend can only translate exact state
# values, never composite strings, so sensor.py composes this state
# server-side from these entries (issues #11, #12). Coverage names derive from
# CLOUD_COVERAGE, cloud types from CLOUD_TYPE, both minus trailing
# parentheticals (the okta counts; de "(Cumulus congestus)" would nest inside
# the formatter's own parentheses). A few rows read wrong as list items and
# get explicit overrides.
CLOUD_LAYER = {
    slug: _strip_parenthetical(strings) for slug, strings in CLOUD_COVERAGE.items()
}
CLOUD_LAYER.update(
    {
        slug: _strip_parenthetical(strings)
        for slug, strings in CLOUD_TYPE.items()
        if slug != "none"
    }
)
# ru "Малооблачно" is a whole-sky adverb, wrong as one layer among noun
# phrases; de BKN "Bedeckt mit Lücken" is too easy to misread next to OVC
# "Bedeckt" in a list (DWD decodes BKN as "durchbrochen").
CLOUD_LAYER["few"] = {**CLOUD_LAYER["few"], "ru": "Незначительная облачность"}
CLOUD_LAYER["broken"] = {**CLOUD_LAYER["broken"], "de": "Durchbrochen"}

RUNWAY_SURFACE = {
    "clear_and_dry": {"en": "Clear and dry", "de": "Frei und trocken", "ru": "Чисто и сухо", "fr": "Dégagée et sèche"},
    "damp": {"en": "Damp", "de": "Feucht", "ru": "Влажно", "fr": "Humide"},
    "wet": {"en": "Wet or water patches", "de": "Nass oder Wasserstellen", "ru": "Мокро или лужи", "fr": "Mouillée ou flaques"},
    "rime_or_frost": {"en": "Rime or frost", "de": "Reif oder Frost", "ru": "Иней или изморозь", "fr": "Givre ou gelée"},
    "dry_snow": {"en": "Dry snow", "de": "Trockener Schnee", "ru": "Сухой снег", "fr": "Neige sèche"},
    "wet_snow": {"en": "Wet snow", "de": "Nasser Schnee", "ru": "Мокрый снег", "fr": "Neige mouillée"},
    "slush": {"en": "Slush", "de": "Schneematsch", "ru": "Слякоть", "fr": "Neige fondante"},
    "ice": {"en": "Ice", "de": "Eis", "ru": "Лёд", "fr": "Glace"},
    "compacted_snow": {"en": "Compacted snow", "de": "Festgefahrener Schnee", "ru": "Уплотнённый снег", "fr": "Neige compactée"},
    "frozen_ruts": {"en": "Frozen ruts or ridges", "de": "Gefrorene Spurrillen", "ru": "Замёрзшая колея", "fr": "Ornières gelées"},
    "not_reported": {"en": "Not reported", "de": "Nicht gemeldet", "ru": "Не сообщается", "fr": "Non communiqué"},
    "snow_closed": {"en": "Closed due to snow", "de": "Wegen Schnee gesperrt", "ru": "Закрыто из-за снега", "fr": "Fermée pour neige"},
    "cleared": {"en": "Cleared", "de": "Geräumt", "ru": "Очищено", "fr": "Dégagée"},
    "unknown": {"en": "Unknown", "de": "Unbekannt", "ru": "Неизвестно", "fr": "Inconnue"},
}

RUNWAY_COVERAGE = {
    "cov_0": {"en": "0%", "de": "0%", "ru": "0%", "fr": "0%"},
    "cov_lt10": {"en": "Less than 10%", "de": "Weniger als 10%", "ru": "Менее 10%", "fr": "Moins de 10%"},
    "cov_11_25": {"en": "11-25%", "de": "11-25%", "ru": "11-25%", "fr": "11-25%"},
    "cov_26_50": {"en": "26-50%", "de": "26-50%", "ru": "26-50%", "fr": "26-50%"},
    "cov_51_75": {"en": "51-75%", "de": "51-75%", "ru": "51-75%", "fr": "51-75%"},
    "cov_76_90": {"en": "76-90%", "de": "76-90%", "ru": "76-90%", "fr": "76-90%"},
    "cov_91_100": {"en": "91-100%", "de": "91-100%", "ru": "91-100%", "fr": "91-100%"},
    "cov_51_100": {"en": "51-100%", "de": "51-100%", "ru": "51-100%", "fr": "51-100%"},
    "not_reported": {"en": "Not reported", "de": "Nicht gemeldet", "ru": "Не сообщается", "fr": "Non communiqué"},
    "unknown": {"en": "Unknown", "de": "Unbekannt", "ru": "Неизвестно", "fr": "Inconnue"},
}

REPORT_TYPE = {
    "auto": {"en": "Automated report", "de": "Automatischer Bericht", "ru": "Автоматический отчёт", "fr": "Rapport automatique"},
    "manual": {"en": "Manual report", "de": "Manueller Bericht", "ru": "Ручной отчёт", "fr": "Rapport manuel"},
}

CAVOK = {
    "yes": {"en": "Yes", "de": "Ja", "ru": "Да", "fr": "Oui"},
    "no": {"en": "No", "de": "Nein", "ru": "Нет", "fr": "Non"},
}

# weather building blocks ---------------------------------------------------

INTENSITY = {
    "light": {"en": "Light", "de": "Leicht", "ru": "Слабый", "fr": "Faible"},
    "heavy": {"en": "Heavy", "de": "Stark", "ru": "Сильный", "fr": "Forte"},
    "vicinity": {"en": "In the vicinity", "de": "In der Nähe", "ru": "В районе", "fr": "Au voisinage"},
}

DESCRIPTOR = {
    "shallow": {"en": "Shallow", "de": "Flach", "ru": "Поверхностный", "fr": "Mince"},
    "partial": {"en": "Partial", "de": "Teilweise", "ru": "Частичный", "fr": "Partiel"},
    "patches": {"en": "Patches", "de": "Stellenweise", "ru": "Местами", "fr": "Bancs"},
    "low_drifting": {"en": "Low drifting", "de": "Niedriges Treiben", "ru": "Низовая", "fr": "Chasse basse"},
    "blowing": {"en": "Blowing", "de": "Verwehend", "ru": "Поднятый", "fr": "Chasse élevée"},
    "showers": {"en": "Showers", "de": "Schauer", "ru": "Ливневый", "fr": "Averses"},
    "thunderstorm": {"en": "Thunderstorm", "de": "Gewitter", "ru": "Гроза", "fr": "Orage"},
    "freezing": {"en": "Freezing", "de": "Gefrierend", "ru": "Переохлаждённый", "fr": "Verglaçant"},
}

PHENOMENON = {
    "drizzle": {"en": "Drizzle", "de": "Nieselregen", "ru": "Морось", "fr": "Bruine"},
    "rain": {"en": "Rain", "de": "Regen", "ru": "Дождь", "fr": "Pluie"},
    "snow": {"en": "Snow", "de": "Schnee", "ru": "Снег", "fr": "Neige"},
    "snow_grains": {"en": "Snow grains", "de": "Schneekörner", "ru": "Снежная крупа", "fr": "Neige en grains"},
    "ice_crystals": {"en": "Ice crystals", "de": "Eiskristalle", "ru": "Ледяные кристаллы", "fr": "Cristaux de glace"},
    "ice_pellets": {"en": "Ice pellets", "de": "Eiskörner", "ru": "Ледяная крупа", "fr": "Granules de glace"},
    "hail": {"en": "Hail", "de": "Hagel", "ru": "Град", "fr": "Grêle"},
    "small_hail": {"en": "Small hail", "de": "Kleinhagel", "ru": "Мелкий град", "fr": "Grésil"},
    "unknown": {"en": "Unknown precipitation", "de": "Unbekannter Niederschlag", "ru": "Неизвестные осадки", "fr": "Précipitations inconnues"},
    "mist": {"en": "Mist", "de": "Feuchter Dunst", "ru": "Дымка", "fr": "Brume"},
    "fog": {"en": "Fog", "de": "Nebel", "ru": "Туман", "fr": "Brouillard"},
    "smoke": {"en": "Smoke", "de": "Rauch", "ru": "Дым", "fr": "Fumée"},
    "volcanic_ash": {"en": "Volcanic ash", "de": "Vulkanasche", "ru": "Вулканический пепел", "fr": "Cendres volcaniques"},
    "dust": {"en": "Widespread dust", "de": "Weitverbreiteter Staub", "ru": "Пыль повсеместно", "fr": "Poussière généralisée"},
    "sand": {"en": "Sand", "de": "Sand", "ru": "Песок", "fr": "Sable"},
    "haze": {"en": "Haze", "de": "Trockener Dunst", "ru": "Мгла", "fr": "Brume sèche"},
    "spray": {"en": "Spray", "de": "Gischt", "ru": "Брызги", "fr": "Embruns"},
    "dust_whirls": {"en": "Dust or sand whirls", "de": "Staub- oder Sandwirbel", "ru": "Пыльные вихри", "fr": "Tourbillons de poussière"},
    "squalls": {"en": "Squalls", "de": "Böen", "ru": "Шквалы", "fr": "Grains"},
    "funnel_cloud": {"en": "Funnel cloud", "de": "Trichterwolke", "ru": "Воронкообразное облако", "fr": "Nuage en entonnoir"},
    "sandstorm": {"en": "Sandstorm", "de": "Sandsturm", "ru": "Песчаная буря", "fr": "Tempête de sable"},
    "duststorm": {"en": "Duststorm", "de": "Staubsturm", "ru": "Пыльная буря", "fr": "Tempête de poussière"},
}

RECENT = {"en": "Recent", "de": "Kürzlich", "ru": "Недавний", "fr": "Récent"}
CLEAR = {"en": "Clear", "de": "Klar", "ru": "Ясно", "fr": "Clair"}

# Compound recent phenomena that the parser emits as single slugs.
RECENT_COMPOUND = {
    "freezing_rain": {"en": "Freezing rain", "de": "Gefrierender Regen", "ru": "Переохлаждённый дождь", "fr": "Pluie verglaçante"},
    "blowing_snow": {"en": "Blowing snow", "de": "Schneeverwehung", "ru": "Метель", "fr": "Chasse-neige"},
}

# Realistic descriptor+phenomenon pairs to enumerate.
DESCRIPTOR_PAIRS = {
    "showers": ["rain", "snow", "drizzle"],
    "thunderstorm": ["rain", "snow", "hail", "small_hail"],
    "freezing": ["rain", "drizzle", "fog"],
    "blowing": ["snow", "sand", "dust"],
    "low_drifting": ["snow", "sand"],
    "shallow": ["fog"],
    "patches": ["fog"],
    "partial": ["fog"],
}


def _compose(parts: list[dict], lang: str) -> str:
    return " ".join(p[lang] for p in parts if p)


def build_weather() -> dict[str, dict[str, str]]:
    """slug -> {lang: composed string} for the enumerated weather combinations."""
    out: dict[str, dict[str, str]] = {}

    def add(slug: str, parts: list[dict]) -> None:
        out[slug] = {lang: _compose(parts, lang) for lang in LANGS}

    add("clear", [CLEAR])

    # phenomenon alone + intensity variants
    for p_slug, p in PHENOMENON.items():
        add(p_slug, [p])
        for i_slug, i in INTENSITY.items():
            add(f"{i_slug}_{p_slug}", [i, p])

    # descriptor-only (thunderstorm) + intensity
    add("thunderstorm", [DESCRIPTOR["thunderstorm"]])
    for i_slug, i in INTENSITY.items():
        add(f"{i_slug}_thunderstorm", [i, DESCRIPTOR["thunderstorm"]])

    # descriptor + phenomenon (+ light/heavy/vicinity)
    for d_slug, phenoms in DESCRIPTOR_PAIRS.items():
        d = DESCRIPTOR[d_slug]
        for p_slug in phenoms:
            p = PHENOMENON[p_slug]
            add(f"{d_slug}_{p_slug}", [d, p])
            for i_slug in ("light", "heavy", "vicinity"):
                add(f"{i_slug}_{d_slug}_{p_slug}", [INTENSITY[i_slug], d, p])

    # vicinity descriptor-only (VCSH, VCTS) and common mixed precipitation.
    add("vicinity_showers", [INTENSITY["vicinity"], DESCRIPTOR["showers"]])
    add("vicinity_thunderstorm", [INTENSITY["vicinity"], DESCRIPTOR["thunderstorm"]])
    for a, b in (("rain", "snow"), ("snow", "rain"), ("rain", "drizzle"),
                 ("drizzle", "rain"), ("snow", "ice_pellets"), ("rain", "ice_pellets")):
        add(f"{a}_{b}", [PHENOMENON[a], PHENOMENON[b]])
        for i_slug in ("light", "heavy"):
            add(f"{i_slug}_{a}_{b}", [INTENSITY[i_slug], PHENOMENON[a], PHENOMENON[b]])

    # recent phenomena (every slug in RECENT_WEATHER_CODES must be covered)
    recent_simple = ["rain", "snow", "drizzle", "showers", "fog", "hail",
                     "small_hail", "ice_pellets", "thunderstorm"]
    for p_slug in recent_simple:
        token = PHENOMENON.get(p_slug) or DESCRIPTOR.get(p_slug)
        add(f"recent_{p_slug}", [RECENT, token])
    for c_slug, c in RECENT_COMPOUND.items():
        add(f"recent_{c_slug}", [RECENT, c])

    # Apply hand/native-reviewed overrides on top of the naive composition.
    # weather_overrides.json fixes word order, gender agreement and capitalization
    # per language (composition is only the coverage floor). Regenerate the file by
    # re-running the polish-weather-translations review when adding combinations.
    ov_path = Path(__file__).resolve().parent / "weather_overrides.json"
    if ov_path.exists():
        overrides = json.loads(ov_path.read_text(encoding="utf-8"))
        for slug, strings in overrides.items():
            out.setdefault(slug, {lang: slug for lang in LANGS}).update(strings)

    return out


def _states(table: dict[str, dict[str, str]], lang: str) -> dict[str, str]:
    return {slug: strings[lang] for slug, strings in table.items()}


def build_entity_sensor(lang: str, weather: dict) -> dict:
    """Build the entity.sensor block for one language."""
    trend_attr = {
        "trend": {"state": {
            "rising": {"en": "Rising", "de": "Steigend", "ru": "Растёт", "fr": "En hausse"}[lang],
            "falling": {"en": "Falling", "de": "Fallend", "ru": "Падает", "fr": "En baisse"}[lang],
            "stable": {"en": "Stable", "de": "Stabil", "ru": "Стабильно", "fr": "Stable"}[lang],
            "veering": {"en": "Veering", "de": "Rechtsdrehend", "ru": "По часовой", "fr": "Adonnant"}[lang],
            "backing": {"en": "Backing", "de": "Linksdrehend", "ru": "Против часовой", "fr": "Refusant"}[lang],
        }}
    }
    measurement = ("temperature", "dew_point", "wind_speed", "wind_gust",
                   "wind_direction", "visibility", "pressure", "humidity")
    sensor: dict = {key: {"state_attributes": trend_attr} for key in measurement}
    sensor["weather"] = {"state": _states(weather, lang)}
    sensor["cloud_coverage_state"] = {"state": _states(CLOUD_COVERAGE, lang)}
    # Read server-side by sensor.py (async_cloud_layer_names), not the frontend.
    sensor["cloud_layers"] = {"state": _states(CLOUD_LAYER, lang)}
    sensor["cloud_coverage_type"] = {"state": _states(CLOUD_TYPE, lang)}
    sensor["report_type"] = {"state": _states(REPORT_TYPE, lang)}
    sensor["cavok"] = {"state": _states(CAVOK, lang)}
    sensor["runway_state"] = {
        "state": _states(RUNWAY_SURFACE, lang),
        "state_attributes": {"coverage": {"state": _states(RUNWAY_COVERAGE, lang)}},
    }
    return sensor


def main() -> None:
    weather = build_weather()
    for lang in LANGS:
        path = TR_DIR / f"{lang}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data.setdefault("entity", {})
        data["entity"]["sensor"] = build_entity_sensor(lang, weather)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        states = sum(len(v.get("state", {})) for v in data["entity"]["sensor"].values())
        print(f"{lang}.json: {len(data['entity']['sensor'])} sensors, {states} state strings")


if __name__ == "__main__":
    main()
