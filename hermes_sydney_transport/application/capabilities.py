"""Closed capability vocabulary shared by catalog and composition."""

from enum import StrEnum


class Capability(StrEnum):
    SEARCH_STOPS = "search_stops"
    NEARBY_STOPS = "nearby_stops"
    DEPARTURES = "departures"
    PLAN_TRIP = "plan_trip"
    ALERTS = "alerts"
    TRAIN_SERVICE_STATUS = "train_service_status"
    TRAIN_VEHICLE_POSITION = "train_vehicle_position"
    BUS_SERVICE_STATUS = "bus_service_status"
    BUS_VEHICLE_POSITION = "bus_vehicle_position"
    TRAFFIC_STATIONS = "traffic_stations"
    TRAFFIC_SUMMARY = "traffic_summary"
    TRAFFIC_HOURLY = "traffic_hourly"
