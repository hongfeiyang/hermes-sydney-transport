"""Small pure geographic calculations shared by location adapters."""

from __future__ import annotations

import math


def haversine_metres(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> int:
    lat1 = math.radians(latitude_a)
    lon1 = math.radians(longitude_a)
    lat2 = math.radians(latitude_b)
    lon2 = math.radians(longitude_b)
    arc = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return round(2 * 6_371_000 * math.asin(min(1.0, math.sqrt(arc))))
