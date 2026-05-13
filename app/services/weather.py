from dataclasses import dataclass
import logging

import requests


logger = logging.getLogger(__name__)


@dataclass
class WeatherSnapshot:
    temperature_c: float
    precipitation_probability: float
    uv_index: float
    us_aqi: float | None


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

        current = forecast_data.get("current", {})
        current_time = current.get("time")
        temperature = float(current.get("temperature_2m"))

        hourly = forecast_data.get("hourly", {})
        hourly_times = hourly.get("time", [])
        precip_probs = hourly.get("precipitation_probability", [])
        uv_values = hourly.get("uv_index", [])

        try:
            idx = hourly_times.index(current_time)
        except ValueError:
            idx = 0

        precipitation_probability = float(self._safe_hourly_value(precip_probs, idx, default=0.0))
        uv_index = float(self._safe_hourly_value(uv_values, idx, default=0.0))

        air_current = air_quality_data.get("current", {})
        us_aqi_raw = air_current.get("us_aqi")
        us_aqi = float(us_aqi_raw) if us_aqi_raw is not None else None

        return WeatherSnapshot(
            temperature_c=temperature,
            precipitation_probability=precipitation_probability,
            uv_index=uv_index,
            us_aqi=us_aqi,
        )

    def _fetch_forecast(self, latitude: float, longitude: float) -> dict:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m",
            "hourly": "precipitation_probability,uv_index",
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
            "current": "us_aqi",
            "timezone": "auto",
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

    def _safe_hourly_value(self, values: list, index: int, *, default: float) -> float:
        if not values:
            return default
        if index < 0 or index >= len(values):
            return default
        raw = values[index]
        if raw is None:
            return default
        return float(raw)
