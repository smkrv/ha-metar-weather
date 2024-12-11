# HA METAR Weather

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/smkrv/ha-metar-weather)](https://github.com/smkrv/ha-metar-weather/releases)
[![GitHub](https://img.shields.io/github/license/smkrv/ha-metar-weather)](LICENSE)

Home Assistant custom integration for METAR weather data. This integration allows you to get detailed weather information from airport weather stations using METAR data.

## Features

- Real-time METAR weather data from airport stations
- Support for multiple stations
- Detailed weather sensors including:
  - Temperature
  - Dew Point
  - Wind Speed and Direction
  - Visibility
  - Pressure
  - Humidity
  - Weather Conditions
  - Cloud Coverage
  - Raw METAR data
- Historical data tracking (24 hours)
- Trend analysis
- Metric system support
- Easy configuration through UI

## Installation

### HACS Installation (Preferred)

1. Open HACS
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add `https://github.com/smkrv/ha-metar-weather` as an Integration
6. Click "Install"

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/smkrv/ha-metar-weather/releases)
2. Extract the contents to your `custom_components` folder
3. Restart Home Assistant

## Configuration

1. Go to Settings -> Devices & Services
2. Click "Add Integration"
3. Search for "HA METAR Weather"
4. Enter your ICAO airport code (e.g., KJFK for New York JFK)
5. Accept the terms of use for METAR data

### Adding Additional Stations

1. Go to the integration settings
2. Click "Configure"
3. Click "Add Station"
4. Enter the ICAO code for the new station

## Available Sensors

Each station will create the following sensors:

- `sensor.metar_[ICAO]_temperature`: Temperature in Celsius
- `sensor.metar_[ICAO]_dew_point`: Dew point in Celsius
- `sensor.metar_[ICAO]_wind_speed`: Wind speed in meters per second
- `sensor.metar_[ICAO]_wind_direction`: Wind direction in degrees
- `sensor.metar_[ICAO]_visibility`: Visibility in meters
- `sensor.metar_[ICAO]_pressure`: Pressure in hPa
- `sensor.metar_[ICAO]_humidity`: Relative humidity in percentage
- `sensor.metar_[ICAO]_weather`: Current weather conditions
- `sensor.metar_[ICAO]_cloud_coverage`: Cloud coverage information
- `sensor.metar_[ICAO]_raw_metar`: Raw METAR data

## Services

### update_station
Force update of METAR data for a specific station.
```yaml
service: ha_metar_weather.update_station
data:
  station: KJFK
```

### clear_history
Clear historical data for a specific station.
```yaml
service: ha_metar_weather.clear_history
data:
  station: KJFK
```

## Data Source

This integration uses data from the NOAA Aviation Digital Data Service (ADDS). Please ensure you comply with their [terms of use](https://www.weather.gov/disclaimer).

## Contributing

Feel free to contribute to this project by:
1. Creating issues for bugs or feature requests
2. Creating pull requests for improvements
3. Sharing your experience and use cases

## Legal Disclaimer and Limitation of Liability  

### Software Disclaimer  

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,   
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A   
PARTICULAR PURPOSE AND NONINFRINGEMENT.  

IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,   
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,   
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER   
DEALINGS IN THE SOFTWARE.  

## 📝 License

Author: SMKRV
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) - see [LICENSE](LICENSE) for details.

## 💡 Support the Project

The best support is:
- Sharing feedback
- Contributing ideas
- Recommending to friends
- Reporting issues
- Star the repository

If you want to say thanks financially, you can send a small token of appreciation in USDT:

**USDT Wallet (TRC10/TRC20):**
`TXC9zYHYPfWUGi4Sv4R1ctTBGScXXQk5HZ`

*Open-source is built by community passion!* 🚀
