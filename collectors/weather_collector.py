"""
Weather data collector using Open-Meteo API (free, no API key required).
"""
import httpx
from typing import List
from datetime import datetime
from core.models import DataItem, DataSource, DataCategory
from core.database import Database
from collectors.base import BaseCollector
import hashlib


class WeatherCollector(BaseCollector):
    def __init__(self, db: Database, config: dict = None):
        super().__init__("weather", db, config)
        self.locations = config.get("locations", []) if config else []

    async def collect(self) -> List[DataItem]:
        items = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for location in self.locations:
                try:
                    loc_items = await self._collect_location(client, location)
                    items.extend(loc_items)
                except Exception as e:
                    self.logger.warning(f"Weather failed for {location.get('name', '?')}: {e}")
        return items

    async def _collect_location(self, client: httpx.AsyncClient, location: dict) -> List[DataItem]:
        name = location.get("name", "Unknown")
        lat = location.get("latitude", 0)
        lon = location.get("longitude", 0)

        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode,windspeed_10m_max",
            "current_weather": "true",
            "timezone": "auto",
            "forecast_days": 7,
        }

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        items = []

        # Current weather
        current = data.get("current_weather", {})
        if current:
            temp = current.get("temperature", 0)
            windspeed = current.get("windspeed", 0)
            weathercode = current.get("weathercode", 0)
            weather_desc = self._weathercode_to_text(weathercode)

            item_id = hashlib.md5(
                f"weather:{name}:{datetime.utcnow().strftime('%Y-%m-%d-%H')}".encode()
            ).hexdigest()

            title = f"Weather in {name}: {temp}°C, {weather_desc}"
            content = (f"Current weather in {name}: {temp}°C ({self._c_to_f(temp)}°F). "
                       f"Conditions: {weather_desc}. Wind: {windspeed} km/h.")

            items.append(DataItem(
                id=item_id,
                title=title,
                content=content,
                url=f"https://open-meteo.com/",
                source=DataSource.WEATHER_API,
                category=DataCategory.WEATHER,
                metadata={
                    "location": name,
                    "latitude": lat,
                    "longitude": lon,
                    "temperature_c": temp,
                    "temperature_f": self._c_to_f(temp),
                    "windspeed_kmh": windspeed,
                    "weathercode": weathercode,
                    "conditions": weather_desc,
                },
                collected_at=datetime.utcnow()
            ))

        # Daily forecast
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        codes = daily.get("weathercode", [])

        for i, date_str in enumerate(dates):
            fcast_id = hashlib.md5(f"weather:{name}:forecast:{date_str}".encode()).hexdigest()
            tmax = temp_max[i] if i < len(temp_max) else None
            tmin = temp_min[i] if i < len(temp_min) else None
            rain = precip[i] if i < len(precip) else 0
            code = codes[i] if i < len(codes) else 0
            desc = self._weathercode_to_text(code)

            title = f"{name} forecast {date_str}: {tmin}–{tmax}°C, {desc}"
            content = (f"Forecast for {name} on {date_str}: "
                       f"High {tmax}°C, Low {tmin}°C. {desc}. "
                       f"Precipitation: {rain}mm.")

            items.append(DataItem(
                id=fcast_id,
                title=title,
                content=content,
                url=f"https://open-meteo.com/",
                source=DataSource.WEATHER_API,
                category=DataCategory.WEATHER,
                metadata={
                    "location": name,
                    "date": date_str,
                    "temp_max_c": tmax,
                    "temp_min_c": tmin,
                    "precipitation_mm": rain,
                    "weathercode": code,
                    "conditions": desc,
                    "is_forecast": True,
                },
                collected_at=datetime.utcnow()
            ))

        return items

    @staticmethod
    def _c_to_f(celsius):
        return round(celsius * 9 / 5 + 32, 1) if celsius is not None else None

    @staticmethod
    def _weathercode_to_text(code: int) -> str:
        codes = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Depositing rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
            77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
            82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
            95: "Thunderstorm", 96: "Thunderstorm w/ slight hail", 99: "Thunderstorm w/ heavy hail",
        }
        return codes.get(code, f"Unknown ({code})")
