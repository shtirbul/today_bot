from dataclasses import dataclass
import logging

import requests


logger = logging.getLogger(__name__)


@dataclass
class WeatherSnapshot:
    temperature_min_c: float
    temperature_max_c: float
    precipitation_probability_max: float
    uv_index_max: float
    us_aqi_avg: float | None
    us_aqi_max: float | None


class WeatherService:
    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def detect_coordinates_from_ip(self) -> tuple[float, float]:
        response = requests.get("https://ipapi.co/json/", timeout=self.timeout)
        if not response.ok:
            raise Exception(f"IP geolocation failed: {response.status_code}")

        data = response.json()
        latitude = data.get("latitude")
        longitude = data.get("longitude")

        if latitude is None or longitude is None:
            raise Exception("IP geolocation did not return latitude/longitude")

        return float(latitude), float(longitude)

    def get_snapshot(self, latitude: float, longitude: float) -> WeatherSnapshot:
        forecast_data = self._fetch_forecast(latitude, longitude)
        air_quality_data = self._fetch_air_quality(latitude, longitude)

        daily = forecast_data.get("daily", {})
        temperature_min = float(self._safe_series_value(daily.get("temperature_2m_min", []), 0, default=0.0))
        temperature_max = float(self._safe_series_value(daily.get("temperature_2m_max", []), 0, default=0.0))
        precipitation_probability_max = float(
            self._safe_series_value(daily.get("precipitation_probability_max", []), 0, default=0.0)
        )
        uv_index_max = float(self._safe_series_value(daily.get("uv_index_max", []), 0, default=0.0))

        air_hourly = air_quality_data.get("hourly", {})
        aqi_values_raw = air_hourly.get("us_aqi", [])
        aqi_values = [float(v) for v in aqi_values_raw if v is not None]

        if aqi_values:
            us_aqi_avg = sum(aqi_values) / len(aqi_values)
            us_aqi_max = max(aqi_values)
        else:
            us_aqi_avg = None
            us_aqi_max = None

        return WeatherSnapshot(
            temperature_min_c=temperature_min,
            temperature_max_c=temperature_max,
            precipitation_probability_max=precipitation_probability_max,
            uv_index_max=uv_index_max,
            us_aqi_avg=us_aqi_avg,
            us_aqi_max=us_aqi_max,
        )

    def _fetch_forecast(self, latitude: float, longitude: float) -> dict:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,uv_index_max",
            "timezone": "auto",
            "forecast_days": 1,
        }
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            timeout=self.timeout,
        )
        if not response.ok:
            raise Exception(f"Weather forecast request failed: {response.status_code}")
        data = response.json()
        logger.info("Weather forecast fetched for lat=%s lon=%s", latitude, longitude)
        return data

    def _fetch_air_quality(self, latitude: float, longitude: float) -> dict:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "us_aqi",
            "timezone": "auto",
            "forecast_days": 1,
        }
        response = requests.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params=params,
            timeout=self.timeout,
        )
        if not response.ok:
            raise Exception(f"Air quality request failed: {response.status_code}")
        data = response.json()
        logger.info("Air quality fetched for lat=%s lon=%s", latitude, longitude)
        return data

    def _safe_series_value(self, values: list, index: int, *, default: float) -> float:
        if not values:
            return default
        if index < 0 or index >= len(values):
            return default
        raw = values[index]
        if raw is None:
            return default
        return float(raw)
