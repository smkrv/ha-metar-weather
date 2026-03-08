# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant custom integration for real-time METAR aviation weather data. Fetches data from 9,000+ airport weather stations worldwide, parses METAR reports, and exposes sensors with trend analysis and historical tracking.

- **Domain**: `ha_metar_weather`
- **HA version**: 2025.2+
- **License**: CC BY-NC-SA 4.0
- **Languages**: English, Russian, German

## Development Commands

```bash
# Validate manifest and integration structure
python -m script.hassfest  # or use the hassfest GitHub Action

# Install dependencies in venv
python -m venv .venv && source .venv/bin/activate
pip install avwx-engine>=1.7.2 aiohttp>=3.8.0 certifi>=2024.2.2

# Debug logging in HA
# Add to configuration.yaml:
# logger:
#   logs:
#     custom_components.ha_metar_weather: debug
```

No test suite exists. CI runs hassfest (`validate.yaml`) and HACS validation (`hassfest.yaml`) via GitHub Actions.

## Architecture

All integration code lives in `custom_components/ha_metar_weather/`.

### Data Flow

```
AWC REST API (primary) ──┐
                         ├──> MetarApiClient ──> MetarDataUpdateCoordinator ──> MetarSensor
AVWX / NOAA FTP (fallback)┘        │                      │
                            validates/rounds          saves to
                                                  MetarHistoryStorage
```

### Key Modules

- **`__init__.py`** — Integration setup, `MetarDataUpdateCoordinator` (HA's `DataUpdateCoordinator` subclass), service registration (`update_station`, `clear_history`), config entry lifecycle, migration v1→v2
- **`api_client.py`** — `MetarApiClient` orchestrates dual-source fetching: tries AWC first, falls back to AVWX. Validates value ranges and rounds numerics. Contains `validate_station()` used by config flow
- **`awc_client.py`** — `AWCApiClient` for Aviation Weather Center REST API (`aviationweather.gov/api/data/metar`). Parses AWC JSON response into internal format. AWC returns wind in knots, visibility in statute miles, pressure in hPa
- **`metar_parser.py`** — `MetarParser` parses raw METAR strings from AVWX data. Handles wind (KT/MPS/VRB), visibility (meters/SM/fractional), clouds, weather phenomena, runway states, pressure (Q/A format). Caches cloud layers and runway states
- **`sensor.py`** — 17 sensor types defined as `MetarSensorEntityDescription` tuples. `MetarSensor` extends `CoordinatorEntity`. Handles unit conversion via `suggested_unit_of_measurement`, trend calculation (rising/falling/veering/backing), 24h statistics in `extra_state_attributes`. Dynamic runway sensors created per-runway
- **`config_flow.py`** — Two-step config: station entry → unit preferences. Options flow for adding/removing stations and changing units. Config version 2
- **`storage.py`** — `MetarHistoryStorage` uses HA's `Store` with debounced saves. Stores up to 200 records per station, auto-cleans data older than 24h. Thread-safe via `asyncio.Lock`
- **`const.py`** — All constants, unit mappings, conversion factors, value ranges, weather/cloud/runway code dictionaries. Version read dynamically from `manifest.json`
- **`utils.py`** — Shared utilities: `calculate_humidity()` (Magnus formula), `parse_runway_states_from_raw()`, `validate_icao_format()`
- **`translations_data.py`** — Python-based translations (en/de/ru) for weather phenomena, clouds, runways. Used because hassfest restricts top-level keys in translation JSON files

### Internal Data Format

All measurements are stored internally in metric/SI base units:
- Wind speed: **km/h** (converted from knots/MPS at parse time)
- Visibility: **km** (converted from meters or statute miles)
- Pressure: **hPa** (converted from inHg if needed)
- Temperature: **°C**
- Cloud height: **feet** (aviation standard)

Unit conversion for display is handled by HA's `suggested_unit_of_measurement` mechanism.

### Unit Configuration

Three modes: `auto` (follow HA system), `native` (METAR aviation units), or manual selection. Configured per-entry, stored in `config_entry.data`.

## Conventions

- All commit messages, release notes, PR descriptions, and repository content (except UI translations) must be in **English only**
- ICAO codes are always uppercased and validated against `^[A-Z0-9]{4}$`
- `asyncio.CancelledError` is always re-raised (never suppressed)
- Storage uses debounced saves (1s cooldown) to avoid excessive disk writes
- Retry on API failure uses exponential backoff: 2s, 5s, 10s, 30s intervals
- Update interval: 30 minutes (`DEFAULT_SCAN_INTERVAL`)
- Translations in `translations/` (en.json, ru.json, de.json) are for HA config flow UI; `translations_data.py` is for runtime weather descriptions
- Version is single-sourced from `manifest.json`
