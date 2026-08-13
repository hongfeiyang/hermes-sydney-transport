"""Pure service progress and state policies over a typed timeline."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ...models.outputs import StopPrediction

ServiceState = Literal["scheduled", "in_progress", "completed", "cancelled", "unknown"]


def locate_progress(
    stops: tuple[StopPrediction, ...], observation_time: datetime
) -> tuple[StopPrediction | None, StopPrediction | None]:
    last = None
    for stop in stops:
        if stop.skipped:
            continue
        instant = (
            stop.departure_predicted
            or stop.arrival_predicted
            or stop.departure_planned
            or stop.arrival_planned
        )
        if instant is None:
            continue
        if instant <= observation_time:
            last = stop
            continue
        return last, stop
    return last, None


def service_state(
    stops: tuple[StopPrediction, ...], observation_time: datetime, *, cancelled: bool
) -> ServiceState:
    if cancelled:
        return "cancelled"
    times = tuple(
        value
        for stop in stops
        if not stop.skipped
        for value in (
            stop.arrival_predicted or stop.arrival_planned,
            stop.departure_predicted or stop.departure_planned,
        )
        if value is not None
    )
    if not times:
        return "unknown"
    if observation_time < min(times):
        return "scheduled"
    if observation_time > max(times):
        return "completed"
    return "in_progress"
