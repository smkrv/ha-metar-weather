# HA METAR Weather

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/smkrv/ha-metar-weather)](https://github.com/smkrv/ha-metar-weather/releases)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.2+-41BDF5.svg)](https://www.home-assistant.io/)
[![English](https://img.shields.io/badge/lang-English-blue.svg)](#localization)
[![Русский](https://img.shields.io/badge/lang-Русский-blue.svg)](#localization)
[![Deutsch](https://img.shields.io/badge/lang-Deutsch-blue.svg)](#localization)

Professional aviation weather monitoring for Home Assistant. Get real-time METAR data from over 9,000 airport weather stations worldwide with automatic trend analysis and historical tracking.

> **⚠️ IMPORTANT NOTICE**
> 
> **⚠️ This integration is NOT certified for aviation navigation or flight planning!**
> METAR data provided is for informational purposes only.
> Always consult official aviation weather sources and certified flight planning tools for aviation activities.

<div align="center">
  <img src="https://github.com/smkrv/ha-metar-weather/blob/main/assets/images/airport.png" alt="HA METAR Weather" width="700"/>
</div>

## Installation

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=smkrv&repository=ha-metar-weather&category=Integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" width="210" height="auto"></a>

## Requirements

- **Home Assistant**: Version 2025.2 or higher
- **Internet Connection**: Required for METAR data retrieval

## Features

### Global Coverage

Access real-time weather data from over 9,000 airport weather stations worldwide. The integration supports any airport with an ICAO code that publishes METAR reports.

### Comprehensive Weather Data

Every configured station provides a complete set of sensors:

- **Temperature and Dew Point** with automatic humidity calculation
- **Wind Speed, Direction and Gusts** with variable wind detection
- **Visibility** in your preferred units
- **Atmospheric Pressure** with QNH support
- **Cloud Coverage** including ceiling height and layer information
- **Weather Phenomena** such as rain, snow, fog, and thunderstorms
- **Runway Conditions** when reported by the station
- **CAVOK Status** and trend information
- **Raw METAR String** for reference

### Intelligent Trend Analysis

The integration tracks historical data and calculates trends automatically:

- **Rising/Falling/Stable** indicators for temperature, pressure, humidity
- **Veering/Backing** for wind direction changes
- **24-hour statistics** including min, max, and average values
- **Historical data storage** with automatic cleanup

### Multi-Source Reliability

Data is fetched from official sources with automatic fallback:

- **Primary**: Aviation Weather Center REST API (aviationweather.gov)
- **Fallback**: NOAA FTP via AVWX (tgftp.nws.noaa.gov)

If the primary source is unavailable, the integration seamlessly switches to the backup source.

### Flexible Unit Configuration

Choose your preferred units, use Home Assistant system settings, or native aviation units:

- **Auto**: Follow Home Assistant system settings
- **Native (METAR)**: Standard aviation units (°C, knots, statute miles, hPa, feet)
- **Manual selection**:
  - Temperature: Celsius or Fahrenheit
  - Wind Speed: km/h, m/s, mph, or knots
  - Visibility: kilometers, meters, miles, or feet
  - Pressure: hPa, inHg, or mmHg
  - Cloud Height: meters or feet

### Multi-Station Support

Monitor as many airports as you need. Each station operates independently with its own update cycle and historical data.

### Localization

Full interface translation in:
- English
- Russian (Русский)
- German (Deutsch)

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for **HA METAR Weather**
4. Enter the ICAO airport code (4 letters, e.g., KJFK, EGLL, UUEE)
5. Configure your preferred units

### Finding Airport Codes

- Use the [ICAO Airport Codes](https://www.world-airport-codes.com/) database
- Verify the station is active at [Aviation Weather Center](https://aviationweather.gov/metar)
- Major international airports have the most reliable data availability

## Services

### update_station

Force an immediate data update for a specific station:

```yaml
service: ha_metar_weather.update_station
data:
  station: KJFK
```

### clear_history

Clear stored historical data for a station:

```yaml
service: ha_metar_weather.clear_history
data:
  station: KJFK
```

## Troubleshooting

### Sensors Show "Unknown" or "Unavailable"

- Verify the ICAO code is correct (exactly 4 uppercase letters)
- Check if the station is actively reporting at [Aviation Weather Center](https://aviationweather.gov/metar)
- Some smaller airports report intermittently

### Enable Debug Logging

Add to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.ha_metar_weather: debug
```

## Data Sources

This integration fetches METAR data from two official sources:

| Source | Description |
|--------|-------------|
| [**AWC REST API**](https://aviationweather.gov/data/api/) | Aviation Weather Center API |
| [**NOAA FTP**](https://tgftp.nws.noaa.gov/) | Traditional FTP source via AVWX |

Both sources provide official NOAA/NWS data. The integration automatically falls back to the secondary source if the primary is unavailable. Users must comply with [NOAA data usage terms](https://www.weather.gov/disclaimer).

## Legal Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

**CRITICAL**: This integration is NOT certified for aviation navigation or flight planning. Always consult official aviation weather sources for aviation activities.

## License

**Author**: SMKRV
**License**: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)

## Support the Project

- Star the repository on GitHub
- Report issues with detailed information
- Suggest new features
- Help with translations

### Financial Support

**USDT Wallet (TRC10/TRC20)**:
`TXC9zYHYPfWUGi4Sv4R1ctTBGScXXQk5HZ`
