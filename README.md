# HA METAR Weather

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/smkrv/ha-metar-weather)](https://github.com/smkrv/ha-metar-weather/releases)
[![GitHub](https://img.shields.io/github/license/smkrv/ha-metar-weather)](LICENSE)

A comprehensive Home Assistant custom integration that provides real-time aviation weather data using METAR (METeorological Aerodrome Reports) from airport weather stations worldwide. This integration transforms raw METAR data into structured Home Assistant sensors with advanced features like historical tracking and trend analysis.

<img src="https://github.com/smkrv/ha-metar-weather/blob/main/assets/images/airport.jpg" alt="HA METAR Weather" style="width: 50%; max-width: 256px; max-height: 128px; aspect-ratio: 2/1; object-fit: contain;"/>

## Requirements

- **Home Assistant**: Version 2023.1.0 or higher
- **Python**: 3.10 or higher (included with Home Assistant)
- **Internet Connection**: Required for METAR data retrieval
- **Memory**: Minimal impact, approximately 5-10MB per station

## Technical Overview

### METAR Data Format
METAR reports are standardized aviation weather observations that include:
- **Surface weather observations** from airports and airfields
- **Automated or manual measurements** updated typically every 30 minutes
- **International standard format** (ICAO Annex 3)
- **Real-time data** from over 9,000 airports worldwide

### Data Sources
- **Primary**: NOAA Aviation Weather Center (AWC)
- **Backup**: Aviation Digital Data Service (ADDS)
- **Update Frequency**: Every 30 minutes (configurable)
- **Data Retention**: 24-hour historical storage per station

### Performance Characteristics
- **API Rate Limits**: Complies with NOAA service limits
- **Response Time**: Typically 2-5 seconds per update
- **Storage Impact**: ~1MB per station per month
- **Processing**: Asynchronous updates to prevent blocking

## Features

### Core Functionality
- **Real-time METAR weather data** from 9,000+ airport stations globally
- **Multiple station support** with independent update cycles
- **Comprehensive sensor suite** covering all standard meteorological parameters
- **Historical data tracking** with 24-hour retention and cleanup
- **Trend analysis** with rising/falling/stable indicators
- **Unit system integration** supporting both metric and imperial units
- **Error handling and recovery** with automatic retry mechanisms

### Weather Parameters Monitored
- **Temperature** (°C/°F) with heat index calculations
- **Dew Point** (°C/°F) with relative humidity derivation
- **Wind Speed and Direction** (m/s, km/h, mph) with gust information
- **Visibility** (m, km, miles) including directional variations
- **Atmospheric Pressure** (hPa, inHg) with QNH/QFE support
- **Relative Humidity** (%) calculated from temperature/dew point
- **Weather Phenomena** (rain, snow, fog, thunderstorms, etc.)
- **Cloud Coverage** (ceiling height, coverage types)
- **Raw METAR String** for advanced parsing or debugging

### Advanced Features
- **Automatic station validation** ensures ICAO codes are valid
- **Data quality indicators** show measurement reliability
- **Configurable update intervals** from 15 minutes to 6 hours
- **Service calls** for manual updates and data management
- **Integration with Home Assistant zones** for location-based automation
- **Device registry integration** with proper device identification

## Installation

### System Requirements Check
Before installation, verify your Home Assistant meets the requirements:

```bash
# Check Home Assistant version
ha core info

# Verify internet connectivity to METAR services
curl -I https://aviationweather.gov/adds/dataserver_current/
```

### HACS Installation (Recommended)

1. **Open HACS** in your Home Assistant interface
2. **Navigate to Integrations** section
3. **Click the three dots** in the top right corner
4. **Select "Custom repositories"**
5. **Add repository**: `https://github.com/smkrv/ha-metar-weather`
6. **Set type**: Integration
7. **Click "Install"** and restart Home Assistant

### Manual Installation

1. **Download latest release**:
   ```bash
   wget https://github.com/smkrv/ha-metar-weather/releases/latest/download/ha-metar-weather.zip
   ```

2. **Extract to custom_components**:
   ```bash
   unzip ha-metar-weather.zip -d /config/custom_components/
   ```

3. **Verify file structure**:
   ```
   /config/custom_components/ha_metar_weather/
   ├── __init__.py
   ├── manifest.json
   ├── sensor.py
   ├── config_flow.py
   └── ...
   ```

4. **Restart Home Assistant**

### Docker Installation Notes
For Home Assistant Container or Docker installations:
- Ensure the container has internet access
- Mount custom_components directory properly
- Consider timezone settings for accurate timestamps

## Configuration

### Initial Setup

1. **Navigate to Settings → Devices & Services**
2. **Click "Add Integration"**
3. **Search for "HA METAR Weather"**
4. **Enter ICAO airport code** (4-letter code, e.g., KJFK, EGLL, UUEE)
5. **Configure update interval** (default: 30 minutes)
6. **Accept METAR data terms of use**

### ICAO Code Selection Guidelines

**Finding Airport Codes**:
- Use [ICAO Airport Codes](https://www.world-airport-codes.com/) database
- Verify station is active at [Aviation Weather Center](https://aviationweather.gov/metar)
- Prefer major airports for consistent data availability

**Code Format**:
- **Exactly 4 characters** (e.g., KJFK, not JFK)
- **All uppercase** (automatic conversion applied)
- **Valid ICAO format** (validated during setup)

### Advanced Configuration Options

**Update Intervals**:
- **15 minutes**: For critical weather monitoring
- **30 minutes**: Default, balances data freshness with API limits
- **1 hour**: For general weather awareness
- **6 hours**: Minimal impact mode

**Data Retention**:
- Historical data automatically cleaned after 24 hours
- Configurable retention periods (6h, 12h, 24h, 48h)
- Manual cleanup via service calls

### Adding Multiple Stations

1. **Go to integration configuration**
2. **Click "Configure"**
3. **Select "Add Station"**
4. **Enter new ICAO code**
5. **Configure station-specific settings**

**Multi-Station Tips**:
- Group stations by geographic region for zone-based automation
- Use different update intervals based on station importance
- Consider API rate limits when adding many stations

## Available Sensors

### Sensor Entity Patterns
Each configured station creates sensors with the pattern:
`sensor.metar_[ICAO_CODE]_[PARAMETER]`

### Temperature Sensors
- **`sensor.metar_[ICAO]_temperature`**
  - **Unit**: °C (metric) / °F (imperial)
  - **Attributes**: trend, historical_data, measurement_time
  - **Device Class**: temperature

- **`sensor.metar_[ICAO]_dew_point`**
  - **Unit**: °C (metric) / °F (imperial)  
  - **Attributes**: spread (temp-dew_point difference)
  - **Device Class**: temperature

### Wind Sensors
- **`sensor.metar_[ICAO]_wind_speed`**
  - **Unit**: m/s (raw), km/h or mph (display)
  - **Attributes**: gust_speed, beaufort_scale, direction_text
  - **Device Class**: wind_speed

- **`sensor.metar_[ICAO]_wind_direction`**
  - **Unit**: degrees (0-360)
  - **Attributes**: cardinal_direction, variable_wind
  - **Device Class**: None

### Atmospheric Sensors
- **`sensor.metar_[ICAO]_pressure`**
  - **Unit**: hPa (metric) / inHg (imperial)
  - **Attributes**: pressure_trend, qnh_value, altimeter_setting
  - **Device Class**: pressure

- **`sensor.metar_[ICAO]_humidity`**
  - **Unit**: % (calculated from temp/dew point)
  - **Attributes**: calculation_method, accuracy_indicator
  - **Device Class**: humidity

- **`sensor.metar_[ICAO]_visibility`**
  - **Unit**: m (metric) / miles (imperial)
  - **Attributes**: visibility_category, directional_visibility
  - **Device Class**: None

### Weather Condition Sensors
- **`sensor.metar_[ICAO]_weather`**
  - **State**: Text description (Clear, Cloudy, Rain, etc.)
  - **Attributes**: intensity, phenomena_codes, visibility_impact
  - **Device Class**: None

- **`sensor.metar_[ICAO]_cloud_coverage`**
  - **State**: Coverage description (Clear, Scattered, Broken, Overcast)
  - **Attributes**: ceiling_height, cloud_layers, coverage_oktas
  - **Device Class**: None

### Raw Data Sensor
- **`sensor.metar_[ICAO]_raw_metar`**
  - **State**: Complete METAR string
  - **Attributes**: parsing_errors, data_age, station_info
  - **Device Class**: None

## Services

### Manual Data Updates

#### update_station
Force immediate update of METAR data for specified station:

```yaml
service: ha_metar_weather.update_station
data:
  station: KJFK  # ICAO code
  force: true    # Optional: bypass cache and rate limits
```

**Use Cases**:
- Pre-flight weather checks
- Critical weather event monitoring  
- Debugging data issues

#### update_all_stations  
Update all configured stations simultaneously:

```yaml
service: ha_metar_weather.update_all_stations
data:
  force: false  # Respect rate limits
```

### Data Management

#### clear_history
Remove historical data for specific station:

```yaml
service: ha_metar_weather.clear_history
data:
  station: KJFK
  hours: 24  # Optional: hours to keep (default: 0, clear all)
```

#### reload_integration
Reload integration configuration without restart:

```yaml
service: ha_metar_weather.reload_integration
```

### Diagnostic Services

#### validate_station
Verify ICAO code and data availability:

```yaml
service: ha_metar_weather.validate_station
data:
  station: KJFK
```

**Returns**:
- Station validity status
- Last successful update time
- Data availability indicators

## Automation Examples

### Aviation Weather Monitoring

#### Pre-Flight Weather Check
```yaml
alias: "Pre-Flight Weather Briefing"
trigger:
  - platform: time
    at: input_datetime.flight_departure
action:
  - service: ha_metar_weather.update_station
    data:
      station: "{{ states('input_select.departure_airport') }}"
      force: true
  - delay: "00:00:10"
  - service: notify.pilot_phone
    data:
      title: "Flight Weather Briefing"
      message: >
        Departure: {{ states('input_select.departure_airport') }}
        Temp: {{ states('sensor.metar_' + states('input_select.departure_airport') + '_temperature') }}°C
        Wind: {{ states('sensor.metar_' + states('input_select.departure_airport') + '_wind_speed') }} km/h 
        from {{ states('sensor.metar_' + states('input_select.departure_airport') + '_wind_direction') }}°
        Visibility: {{ states('sensor.metar_' + states('input_select.departure_airport') + '_visibility') }} km
        Conditions: {{ states('sensor.metar_' + states('input_select.departure_airport') + '_weather') }}
```

#### Weather-Based HVAC Control
```yaml
alias: "Airport Weather HVAC Adjustment"
trigger:
  - platform: state
    entity_id: sensor.metar_kjfk_temperature
  - platform: state  
    entity_id: sensor.metar_kjfk_wind_speed
condition:
  - condition: numeric_state
    entity_id: sensor.metar_kjfk_temperature
    below: 5  # °C
  - condition: numeric_state
    entity_id: sensor.metar_kjfk_wind_speed
    above: 30  # km/h
action:
  - service: climate.set_temperature
    target:
      entity_id: climate.main_thermostat
    data:
      temperature: >
        {{ 21 + (5 - states('sensor.metar_kjfk_temperature')|float) * 0.5 }}
  - service: climate.set_fan_mode
    target:
      entity_id: climate.main_thermostat  
    data:
      fan_mode: >
        {% if states('sensor.metar_kjfk_wind_speed')|float > 50 %}
          high
        {% else %}
          auto
        {% endif %}
```

#### Multi-Station Weather Comparison
```yaml
alias: "Regional Weather Comparison Alert"  
trigger:
  - platform: time_pattern
    hours: "/6"  # Every 6 hours
condition:
  - condition: template
    value_template: >
      {{ (states('sensor.metar_kjfk_temperature')|float - 
          states('sensor.metar_klga_temperature')|float)|abs > 5 }}
action:
  - service: notify.weather_alerts
    data:
      title: "Regional Weather Variance Detected"
      message: >
        Temperature difference between JFK and LGA: 
        {{ (states('sensor.metar_kjfk_temperature')|float - 
            states('sensor.metar_klga_temperature')|float)|round(1) }}°C
        JFK: {{ states('sensor.metar_kjfk_temperature') }}°C, 
        {{ states('sensor.metar_kjfk_weather') }}
        LGA: {{ states('sensor.metar_klga_temperature') }}°C,
        {{ states('sensor.metar_klga_weather') }}
```

### Advanced Dashboard Configuration

#### Weather Station Dashboard Card
```yaml
type: vertical-stack
cards:
  - type: header
    title: "METAR Weather - {{ station_code }}"
    subtitle: "Last Updated: {{ states.sensor.metar_kjfk_temperature.last_changed.strftime('%H:%M UTC') }}"
  
  - type: grid
    columns: 3
    cards:
      - type: sensor
        entity: sensor.metar_kjfk_temperature
        name: Temperature
        icon: mdi:thermometer
        graph: line
        
      - type: sensor  
        entity: sensor.metar_kjfk_wind_speed
        name: Wind Speed
        icon: mdi:weather-windy
        
      - type: sensor
        entity: sensor.metar_kjfk_pressure
        name: Pressure
        icon: mdi:gauge
        
  - type: weather-forecast
    entity: weather.metar_kjfk
    show_forecast: false
    
  - type: conditional
    conditions:
      - entity: sensor.metar_kjfk_weather
        state_not: "Clear"
    card:
      type: alert
      entity: sensor.metar_kjfk_weather
      state: "on"
      
  - type: history-graph
    entities:
      - sensor.metar_kjfk_temperature
      - sensor.metar_kjfk_pressure
    hours_to_show: 24
    refresh_interval: 30
```

## Troubleshooting

### Common Issues

#### Integration Fails to Load
**Symptoms**: Integration not visible in Devices & Services

**Solutions**:
1. **Verify installation**:
   ```bash
   ls -la /config/custom_components/ha_metar_weather/
   ```
2. **Check manifest.json** for syntax errors
3. **Review Home Assistant logs**:
   ```yaml
   logger:
     logs:
       custom_components.ha_metar_weather: debug
   ```
4. **Restart Home Assistant** after installation

#### ICAO Code Validation Errors  
**Symptoms**: "Invalid ICAO code" during setup

**Solutions**:
- **Verify code format**: Must be exactly 4 uppercase letters
- **Check station activity**: Use [AWC METAR search](https://aviationweather.gov/metar)
- **Try major airports first**: Small airports may have limited data
- **Examples of valid codes**: KJFK, EGLL, UUEE, CYVR

#### No Data or "Unknown" Sensor States
**Symptoms**: Sensors show "Unknown" or "Unavailable"

**Diagnostic Steps**:
1. **Test API connectivity**:
   ```bash
   curl "https://aviationweather.gov/adds/dataserver_current/httpparam?dataSource=metars&requestType=retrieve&format=xml&stationString=KJFK&hoursBeforeNow=2"
   ```

2. **Enable debug logging**:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.ha_metar_weather: debug
       custom_components.ha_metar_weather.api_client: debug  
   ```

3. **Check integration configuration**
4. **Verify station is reporting** (some airports report intermittently)

**Common Causes**:
- Station temporarily offline or not reporting
- Network connectivity issues
- API rate limiting (wait and retry)
- Invalid or inactive ICAO code

#### Incorrect Units or Values
**Symptoms**: Wrong temperature scale, wind speeds, etc.

**Solutions**:
1. **Check Home Assistant unit system**:
   ```yaml
   # configuration.yaml
   homeassistant:
     unit_system: metric  # or imperial
   ```

2. **Verify sensor attributes** for unit information
3. **Temperature scale**: 
   - Metric: Celsius
   - Imperial: Fahrenheit
4. **Wind speed units**:
   - Metric: km/h
   - Imperial: mph
   - Raw METAR: m/s or knots

#### Performance and Memory Issues
**Symptoms**: Home Assistant slow, high memory usage

**Optimization Steps**:
1. **Reduce update frequency** for non-critical stations
2. **Limit historical data retention**:
   ```yaml
   # Reduce to 12 hours
   clear_history:
     hours: 12
   ```
3. **Remove unused stations**
4. **Monitor system resources**
5. **Consider station grouping** by importance

#### API Rate Limiting
**Symptoms**: Intermittent data updates, timeout errors

**Solutions**:
- **Increase update intervals** (minimum 15 minutes recommended)
- **Stagger updates** for multiple stations  
- **Use force=false** in service calls
- **Monitor logs** for rate limit messages
- **Contact NOAA** if persistent issues

### Advanced Diagnostics

#### Enable Detailed Logging
```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.ha_metar_weather: debug
    custom_components.ha_metar_weather.sensor: info
    custom_components.ha_metar_weather.api_client: debug
    custom_components.ha_metar_weather.metar_parser: info
```

#### Integration Health Check
Create automation to monitor integration health:
```yaml
alias: "METAR Integration Health Check"
trigger:
  - platform: time_pattern
    minutes: "/15"
condition:
  - condition: template
    value_template: >
      {{ (now() - states.sensor.metar_kjfk_temperature.last_changed).total_seconds() > 3600 }}
action:
  - service: persistent_notification.create
    data:
      title: "METAR Data Warning" 
      message: "No data update from KJFK station in over 1 hour"
      notification_id: metar_health_check
```

#### Manual API Testing
Test METAR data retrieval manually:
```bash
# Test specific station
curl -s "https://aviationweather.gov/adds/dataserver_current/httpparam?dataSource=metars&requestType=retrieve&format=xml&stationString=KJFK&hoursBeforeNow=1" | xmllint --format -

# Test multiple stations  
curl -s "https://aviationweather.gov/adds/dataserver_current/httpparam?dataSource=metars&requestType=retrieve&format=xml&stationString=KJFK,KLGA,KEWR&hoursBeforeNow=1"
```

### Getting Support

#### Before Reporting Issues
1. **Check existing issues**: [GitHub Issues](https://github.com/smkrv/ha-metar-weather/issues)
2. **Enable debug logging** and collect logs
3. **Test with major airport** (KJFK, EGLL, etc.)
4. **Verify Home Assistant version compatibility**

#### Issue Report Template
When creating issues, please include:

```
**Home Assistant Version**: 2024.1.0
**Integration Version**: 1.0.0  
**ICAO Station(s)**: KJFK, KLGA
**Error Description**: Brief description
**Logs**: (paste relevant debug logs)
**Steps to Reproduce**: 
1. Step one
2. Step two
**Expected Behavior**: What should happen
**Actual Behavior**: What actually happened
```

#### Community Support
- **GitHub Discussions**: General questions and feature requests
- **Home Assistant Community**: Integration usage and automation examples
- **Discord/Forums**: Real-time community support

## Data Sources and Compliance

### Primary Data Sources
- **NOAA Aviation Weather Center (AWC)**: Primary METAR data source
- **Aviation Digital Data Service (ADDS)**: XML API endpoint
- **Coverage**: 9,000+ airports worldwide
- **Update Frequency**: Typically 30-60 minutes per station

### Terms of Use Compliance
This integration complies with NOAA/NWS data usage policies:
- **Attribution**: Data sourced from NOAA/NWS
- **Commercial Use**: Permitted under government data policies
- **Rate Limiting**: Respects service limitations
- **Disclaimer**: See NOAA weather service disclaimer

**NOAA Disclaimer**: This integration uses data from the National Weather Service. Users must comply with [NOAA data usage terms](https://www.weather.gov/disclaimer).

### Data Accuracy and Limitations
- **Automated Stations**: May have sensor limitations
- **Reporting Intervals**: Not all stations report continuously  
- **Weather Phenomena**: Limited to observable conditions
- **Accuracy**: Professional grade equipment, but subject to calibration
- **Historical Data**: Limited to 24-hour retention in this integration

## Contributing

### Development Setup
1. **Fork the repository**
2. **Clone locally**:
   ```bash
   git clone https://github.com/yourusername/ha-metar-weather.git
   ```
3. **Create development environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. **Install pre-commit hooks**:
   ```bash
   pre-commit install
   ```

### Code Standards
- **Python 3.10+** compatibility required
- **Black formatting** (line length: 88)
- **Pylint compliance** (score > 9.0)
- **Type hints** for all functions
- **Docstrings** following Google style
- **Unit tests** for all new features

### Contribution Types Welcome
1. **Bug Fixes**: Issue reproduction and resolution
2. **Feature Enhancements**: New sensors or functionality
3. **Documentation**: Improved guides and examples
4. **Testing**: Additional unit tests and integration tests
5. **Translations**: UI text localization
6. **Performance**: Optimization and efficiency improvements

### Testing
```bash
# Run unit tests
python -m pytest tests/

# Run integration tests
python -m pytest tests/integration/

# Check code quality
pylint custom_components/ha_metar_weather/
black --check custom_components/ha_metar_weather/
```

## Legal Disclaimer and Limitation of Liability

### Software Disclaimer
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.

IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

### Aviation Weather Disclaimer
**CRITICAL NOTICE**: This integration is NOT certified for aviation navigation or flight planning. METAR data provided is for informational purposes only. Always consult official aviation weather sources and certified flight planning tools for aviation activities.

### Data Accuracy Disclaimer  
Weather data accuracy depends on reporting station equipment and maintenance. Users should verify critical weather information through multiple sources and official meteorological services.

## License

**Author**: SMKRV  
**License**: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)

### License Summary
- **Attribution Required**: Credit original author
- **Non-Commercial Use**: Commercial use prohibited without permission
- **Share Alike**: Derivative works must use same license
- **Source Code**: Available under same terms

See [LICENSE](LICENSE) file for complete terms.

## Support the Project

### Community Support
The best support comes from community engagement:
- **Share feedback** and usage experiences
- **Contribute ideas** for new features  
- **Recommend** to other Home Assistant users
- **Report issues** with detailed information
- **Star the repository** on GitHub
- **Write reviews** and tutorials

### Development Support
Technical contributions are highly valued:
- **Code contributions** via pull requests
- **Documentation improvements**
- **Translation assistance**
- **Beta testing** of new features
- **Performance optimization**

### Financial Support
If this integration has been valuable and you wish to express appreciation financially:

**USDT Wallet (TRC10/TRC20)**:
`TXC9zYHYPfWUGi4Sv4R1ctTBGScXXQk5HZ`

*Remember: Open-source thrives on community passion and collaboration!*

---

**Version**: 1.0.0  
**Last Updated**: January 2024  
**Compatibility**: Home Assistant 2023.1.0+
