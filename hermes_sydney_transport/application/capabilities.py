"""Closed capability vocabulary shared by catalog and composition."""

from enum import StrEnum


class Capability(StrEnum):
    SEARCH_STOPS = "search_stops"
    NEARBY_STOPS = "nearby_stops"
    DEPARTURES = "departures"
    PLAN_TRIP = "plan_trip"
    ALERTS = "alerts"
    ROUTE_DISRUPTIONS = "route_disruptions"
    STOP_ACCESSIBILITY = "stop_accessibility"
    ROUTE_TIMETABLE = "route_timetable"
    TRAIN_SERVICE_STATUS = "train_service_status"
    TRAIN_VEHICLE_POSITION = "train_vehicle_position"
    BUS_SERVICE_STATUS = "bus_service_status"
    BUS_VEHICLE_POSITION = "bus_vehicle_position"
    METRO_SERVICE_STATUS = "metro_service_status"
    METRO_VEHICLE_POSITION = "metro_vehicle_position"
    LIGHT_RAIL_SERVICE_STATUS = "light_rail_service_status"
    LIGHT_RAIL_VEHICLE_POSITION = "light_rail_vehicle_position"
    FERRY_SERVICE_STATUS = "ferry_service_status"
    FERRY_VEHICLE_POSITION = "ferry_vehicle_position"
    LIVE_TRAFFIC_HAZARDS = "live_traffic_hazards"
    TRAFFIC_STATIONS = "traffic_stations"
    TRAFFIC_SUMMARY = "traffic_summary"
    TRAFFIC_HOURLY = "traffic_hourly"
