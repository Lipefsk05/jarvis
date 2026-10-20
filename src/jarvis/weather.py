"""Today's forecast from Open-Meteo (free, no key). Blocking call: the bot runs it in a thread (stdlib only)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode
from urllib.request import urlopen

URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes, grouped the way a person would say them
_CODES = (
    ({0}, "céu limpo"), ({1, 2}, "poucas nuvens"), ({3}, "nublado"), ({45, 48}, "neblina"),
    ({51, 53, 55, 56, 57}, "garoa"), ({61, 63, 65, 66, 67}, "chuva"), ({71, 73, 75, 77, 85, 86}, "neve"),
    ({80, 81, 82}, "pancadas de chuva"), ({95, 96, 99}, "tempestade"),
)


@dataclass(frozen=True)
class Forecast:
    low: float
    high: float
    rain_chance: int  # percent, 0-100
    code: int


def describe_code(code: int) -> str:
    return next((text for codes, text in _CODES if code in codes), "tempo variável")


def fetch(lat: float, lon: float, timezone: str, opener: Callable = urlopen, timeout: float = 8) -> Forecast:
    query = urlencode({
        "latitude": lat, "longitude": lon, "timezone": timezone, "forecast_days": 1,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })
    with opener(f"{URL}?{query}", timeout=timeout) as response:
        daily = json.loads(response.read().decode("utf-8"))["daily"]
    return Forecast(
        low=float(daily["temperature_2m_min"][0]), high=float(daily["temperature_2m_max"][0]),
        rain_chance=int(daily["precipitation_probability_max"][0] or 0), code=int(daily["weather_code"][0]),
    )


def format_forecast(forecast: Forecast, place: str) -> str:
    text = f"{place}: {describe_code(forecast.code)}, de {forecast.low:.0f}° a {forecast.high:.0f}°"
    if forecast.rain_chance >= 30:
        text += f", {forecast.rain_chance}% de chance de chuva (leve o guarda-chuva)"
    return text + "."
