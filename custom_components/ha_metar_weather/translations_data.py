"""
Localized strings for the HA METAR Weather integration.

These translations are stored in Python code rather than HA translation files
because hassfest only allows specific top-level keys in translations JSON.

@license: CC BY-NC-SA 4.0 International
@github: https://github.com/smkrv/ha-metar-weather
@source: https://github.com/smkrv/ha-metar-weather
"""

from __future__ import annotations

from typing import Dict, Final

# Weather intensity translations
WEATHER_INTENSITY: Final[Dict[str, Dict[str, str]]] = {
    "en": {
        "light": "Light",
        "heavy": "Heavy",
        "vicinity": "In the vicinity",
    },
    "de": {
        "light": "Schwach",
        "heavy": "Stark",
        "vicinity": "In der Nähe",
    },
    "ru": {
        "light": "Слабый",
        "heavy": "Сильный",
        "vicinity": "В районе",
    },
    "fr": {
        "light": "Légere",
        "heavy": "Forte",
        "vicinity": "Au voisinage de",
    },
}

# Weather descriptor translations
WEATHER_DESCRIPTOR: Final[Dict[str, Dict[str, str]]] = {
    "en": {
        "shallow": "Shallow",
        "partial": "Partial",
        "patches": "Patches",
        "low_drifting": "Low drifting",
        "blowing": "Blowing",
        "showers": "Showers",
        "thunderstorm": "Thunderstorm",
        "freezing": "Freezing",
    },
    "de": {
        "shallow": "Oberflächlich",
        "partial": "Teilweise",
        "patches": "Stellenweise",
        "low_drifting": "Niedriges Treiben",
        "blowing": "Verwehend",
        "showers": "Schauer",
        "thunderstorm": "Gewitter",
        "freezing": "Gefrierend",
    },
    "ru": {
        "shallow": "Поверхностный",
        "partial": "Частичный",
        "patches": "Местами",
        "low_drifting": "Низовая метель",
        "blowing": "Позёмок",
        "showers": "Ливни",
        "thunderstorm": "Гроза",
        "freezing": "Замерзающий",
    },
    "fr": {
        "shallow": "Mince",
        "partial": "Partiel",
        "patches": "Bancs",
        "low_drifting": "Chasse basse",
        "blowing": "Chasse élevée",
        "showers": "Averses",
        "thunderstorm": "Orage",
        "freezing": "Givrage",
    },    
}

# Weather phenomenon translations
WEATHER_PHENOMENON: Final[Dict[str, Dict[str, str]]] = {
    "en": {
        "drizzle": "Drizzle",
        "rain": "Rain",
        "snow": "Snow",
        "snow_grains": "Snow grains",
        "ice_crystals": "Ice crystals",
        "ice_pellets": "Ice pellets",
        "hail": "Hail",
        "small_hail": "Small hail",
        "unknown": "Unknown precipitation",
        "mist": "Mist",
        "fog": "Fog",
        "smoke": "Smoke",
        "volcanic_ash": "Volcanic ash",
        "dust": "Widespread dust",
        "sand": "Sand",
        "haze": "Haze",
        "spray": "Spray",
        "dust_whirls": "Dust/sand whirls",
        "squalls": "Squalls",
        "funnel_cloud": "Funnel cloud",
        "sandstorm": "Sandstorm",
        "duststorm": "Duststorm",
    },
    "de": {
        "drizzle": "Nieselregen",
        "rain": "Regen",
        "snow": "Schnee",
        "snow_grains": "Schneekörner",
        "ice_crystals": "Eiskristalle",
        "ice_pellets": "Eiskügelchen",
        "hail": "Hagel",
        "small_hail": "Kleinhagel",
        "unknown": "Unbekannter Niederschlag",
        "mist": "Dunst",
        "fog": "Nebel",
        "smoke": "Rauch",
        "volcanic_ash": "Vulkanasche",
        "dust": "Weitverbreiteter Staub",
        "sand": "Sand",
        "haze": "Trübung",
        "spray": "Gischt",
        "dust_whirls": "Staub-/Sandwirbel",
        "squalls": "Böen",
        "funnel_cloud": "Trichterwolke",
        "sandstorm": "Sandsturm",
        "duststorm": "Staubsturm",
    },
    "ru": {
        "drizzle": "Морось",
        "rain": "Дождь",
        "snow": "Снег",
        "snow_grains": "Снежная крупа",
        "ice_crystals": "Ледяные кристаллы",
        "ice_pellets": "Ледяные гранулы",
        "hail": "Град",
        "small_hail": "Мелкий град",
        "unknown": "Неизвестные осадки",
        "mist": "Дымка",
        "fog": "Туман",
        "smoke": "Дым",
        "volcanic_ash": "Вулканический пепел",
        "dust": "Пыль повсеместно",
        "sand": "Песок",
        "haze": "Мгла",
        "spray": "Брызги",
        "dust_whirls": "Пыльные/песчаные вихри",
        "squalls": "Шквалы",
        "funnel_cloud": "Воронкообразное облако",
        "sandstorm": "Песчаная буря",
        "duststorm": "Пыльная буря",
    },
    "fr": {
        "drizzle": "Bruine",
        "rain": "Pluie",
        "snow": "Neige",
        "snow_grains": "Neige en grains",
        "ice_crystals": "Givrage",
        "ice_pellets": "Granules de glace",
        "hail": "Grêle",
        "small_hail": "Grésil",
        "unknown": "Неизвестные осадки",
        "mist": "Brume",
        "fog": "Brouillard",
        "smoke": "Fumée",
        "volcanic_ash": "Cendre volcanique",
        "dust": "Poussière généralisée",
        "sand": "Sable",
        "haze": "Brume sèche",
        "spray": "Précipitations",
        "dust_whirls": "Tornades",
        "squalls": "Bourrasques",
        "funnel_cloud": "Trombe",
        "sandstorm": "Tempête de sable",
        "duststorm": "Tempête de poussière",
    },    
}

# Cloud coverage translations
CLOUD_COVERAGE_TRANSLATIONS: Final[Dict[str, Dict[str, str]]] = {
    "en": {
        "clear_sky": "Clear sky",
        "clear": "Clear",
        "no_significant": "No significant clouds",
        "few": "Few (1-2 oktas)",
        "scattered": "Scattered (3-4 oktas)",
        "broken": "Broken (5-7 oktas)",
        "overcast": "Overcast (8 oktas)",
        "vertical_visibility": "Vertical visibility",
    },
    "de": {
        "clear_sky": "Klarer Himmel",
        "clear": "Klar",
        "no_significant": "Keine bedeutenden Wolken",
        "few": "Wenige Wolken (1-2 Achtel)",
        "scattered": "Aufgelockerte Bewölkung (3-4 Achtel)",
        "broken": "Bedeckt mit Lücken (5-7 Achtel)",
        "overcast": "Bedeckt (8 Achtel)",
        "vertical_visibility": "Vertikale Sicht",
    },
    "ru": {
        "clear_sky": "Ясное небо",
        "clear": "Ясно",
        "no_significant": "Нет значимых облаков",
        "few": "Малооблачно (1-2 окта)",
        "scattered": "Рассеянная облачность (3-4 окта)",
        "broken": "Переменная облачность (5-7 окт)",
        "overcast": "Сплошная облачность (8 окт)",
        "vertical_visibility": "Вертикальная видимость",
    },
    "fr": {
        "clear_sky": "Ciel dégagé",
        "clear": "Clair",
        "no_significant": "Pas de nuage significatif",
        "few": "Peu (1-2 oktas)",
        "scattered": "Epars (3-4 oktas)",
        "broken": "Fragmenté (5-7 oktas)",
        "overcast": "Couvert (8 oktas)",
        "vertical_visibility": "Visibilité verticale",
    },    
}

# Runway condition translations
RUNWAY_CONDITION: Final[Dict[str, Dict[str, str]]] = {
    "en": {
        "contamination": "Contamination",
        "coverage": "Coverage",
        "depth": "Depth",
        "friction": "Friction",
        "braking": "Braking action",
    },
    "de": {
        "contamination": "Verunreinigung",
        "coverage": "Bedeckung",
        "depth": "Tiefe",
        "friction": "Reibung",
        "braking": "Bremswirkung",
    },
    "ru": {
        "contamination": "Загрязнение",
        "coverage": "Покрытие",
        "depth": "Глубина",
        "friction": "Сцепление",
        "braking": "Торможение",
    },
    "fr": {
        "contamination": "Contamination",
        "coverage": "Couverture",
        "depth": "Profondeur",
        "friction": "Friction",
        "braking": "Action de freinage",
    },    
}

# Wind translations
WIND_TRANSLATIONS: Final[Dict[str, Dict[str, str]]] = {
    "en": {
        "from": "From",
        "to": "To",
        "varying_between": "Varying between",
        "up_to": "Up to",
    },
    "de": {
        "from": "Von",
        "to": "Bis",
        "varying_between": "Variierend zwischen",
        "up_to": "Bis zu",
    },
    "ru": {
        "from": "От",
        "to": "До",
        "varying_between": "Изменяется между",
        "up_to": "До",
    },
    "fr": {
        "from": "Du",
        "to": "Vers",
        "varying_between": "Variable entre",
        "up_to": "Jusqu'a",
    },    
}

# State attributes translations
STATE_ATTRIBUTES: Final[Dict[str, Dict[str, str]]] = {
    "en": {
        "last_update": "Last Update",
        "station": "Station",
        "station_name": "Station Name",
        "raw_metar": "Raw METAR",
        "min_24h": "24h Minimum",
        "max_24h": "24h Maximum",
        "average_24h": "24h Average",
        "trend": "Trend",
        "wind_gust": "Wind Gust",
        "wind_variable_direction": "Variable Wind Direction",
        "wind_variation_from": "Wind Variation From",
        "wind_variation_to": "Wind Variation To",
    },
    "de": {
        "last_update": "Letzte Aktualisierung",
        "station": "Station",
        "station_name": "Stationsname",
        "raw_metar": "Roh-METAR",
        "min_24h": "24h Minimum",
        "max_24h": "24h Maximum",
        "average_24h": "24h Durchschnitt",
        "trend": "Trend",
        "wind_gust": "Windböen",
        "wind_variable_direction": "Variable Windrichtung",
        "wind_variation_from": "Windvariation von",
        "wind_variation_to": "Windvariation bis",
    },
    "ru": {
        "last_update": "Последнее обновление",
        "station": "Станция",
        "station_name": "Название станции",
        "raw_metar": "Исходная METAR",
        "min_24h": "Минимум за 24ч",
        "max_24h": "Максимум за 24ч",
        "average_24h": "Среднее за 24ч",
        "trend": "Тенденция",
        "wind_gust": "Порывы ветра",
        "wind_variable_direction": "Переменное направление ветра",
        "wind_variation_from": "Вариация ветра от",
        "wind_variation_to": "Вариация ветра до",
    },
    "fr": {
        "last_update": "Dernière mise à jour",
        "station": "Station",
        "station_name": "Nom de la station",
        "raw_metar": "METAR brut",
        "min_24h": "24h Minimum",
        "max_24h": "24h Maximum",
        "average_24h": "Moyenne à 24H",
        "trend": "Tendance",
        "wind_gust": "Rafales",
        "wind_variable_direction": "Direction du vent variable",
        "wind_variation_from": "Vent en provenance du",
        "wind_variation_to": "Vent en direction vers",
    },    
}


def get_translation(translations: Dict[str, Dict[str, str]], key: str, lang: str = "en") -> str:
    """Get translation for a key in specified language.
    
    Falls back to English if translation not found.
    
    Args:
        translations: Dictionary of translations by language
        key: The key to translate
        lang: Language code (en, de, ru, fr)
        
    Returns:
        Translated string or the key itself if not found
    """
    if lang in translations and key in translations[lang]:
        return translations[lang][key]
    # Fallback to English
    if "en" in translations and key in translations["en"]:
        return translations["en"][key]
    return key

