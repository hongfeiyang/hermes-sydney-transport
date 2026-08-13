# TfNSW endpoint and macro reference

Validation date: 14 August 2026 (Australia/Sydney).

## Trip Planner macros

| Endpoint | Internal parameters | Purpose |
|---|---|---|
| `/stop_finder` | `TfNSWSF=true` | TfNSW stop matching |
| `/departure_mon` | `departureMonitorMacro=true`, `TfNSWDM=true` | Departure board and realtime fields |
| `/coord` | `PoisOnMapMacro=true` | Nearby public-transport stops |
| `/trip` | `depArrMacro=dep|arr`, `TfNSWTR=true` | Depart-after/arrive-by journey planning |
| `/add_info` | repeated `filterMOTType=1|2|4|5|9` | Current Trip Planner alerts for selected modes |

Macros are policy, not model inputs. Train is product/MOT class `1`, metro is `2`,
light rail is `4`, bus is `5`, and ferry is `9`. Non-requested classes are excluded
from departures and journeys. Walking legs can still appear inside a journey.

The legacy specification's optional engine `version=10.2.1.42` is omitted.
The current engine also rejects `type_sf=stop`, so stop search uses `type_sf=any` and
then requires an intersection with the requested mode list.

## GTFS-Realtime Alerts v2

| Mode family | Alerts endpoint(s) |
|---|---|
| Train | `/v2/gtfs/alerts/sydneytrains`, `/v2/gtfs/alerts/nswtrains` |
| Bus | `/v2/gtfs/alerts/buses`, `/v2/gtfs/alerts/regionbuses` |
| Metro | `/v2/gtfs/alerts/metro` |
| Light rail | `/v2/gtfs/alerts/lightrail` |
| Ferry | `/v2/gtfs/alerts/ferries` |

These endpoints power `sydney_transport_route_disruptions` and current accessibility
warnings inside `sydney_transport_stop_accessibility`.

## GTFS and GTFS-Realtime Trip Updates / Vehicle Positions

| Mode | Static schedule | Trip Updates | Vehicle Positions |
|---|---|---|---|
| Train | `/v1/gtfs/schedule/sydneytrains` | `/v2/gtfs/realtime/sydneytrains` | `/v2/gtfs/vehiclepos/sydneytrains` |
| Bus | `/v1/gtfs/schedule/buses` | `/v1/gtfs/realtime/buses` | `/v1/gtfs/vehiclepos/buses` |
| Metro | `/v2/gtfs/schedule/metro` | `/v2/gtfs/realtime/metro` | `/v2/gtfs/vehiclepos/metro` |
| Light rail | v1 `/lightrail/{cbdandsoutheast,innerwest,newcastle,parramatta}` | v2 `/lightrail/innerwest`; v1 `/lightrail/{cbdandsoutheast,newcastle,parramatta}` | v1 `/lightrail/{cbdandsoutheast,innerwest,newcastle,parramatta}` |
| Ferry | v1 `/ferries/{sydneyferries,MFF}` | v1 `/ferries/{sydneyferries,MFF}` | v1 `/ferries/{sydneyferries,MFF}` |

The join key is Trip Planner `properties.RealtimeTripId` to GTFS/GTFS-R `trip_id`.
The shorter `tripCode` is only a fallback locator and is never treated as a trip ID.

## Static accessibility and Complete GTFS resources

| Resource | Endpoint |
|---|---|
| Complete GTFS timetable bundle | `/v1/publictransport/timetables/complete/gtfs` |
| Location facilities CSV | official TfNSW Open Data resource download |
| Interchange lifts workbook | official TfNSW Open Data resource download |

Complete GTFS route/trip/stop IDs are used only by `sydney_transport_route_timetable`.

## Live Traffic hazards

| Hazard type | Endpoint |
|---|---|
| Incident | `/v1/live/hazards/incident/open` |
| Fire | `/v1/live/hazards/fire/open` |
| Flood | `/v1/live/hazards/flood/open` |
| Alpine | `/v1/live/hazards/alpine/open` |
| Major event | `/v1/live/hazards/majorevent/open` |
| Roadwork | `/v1/live/hazards/roadwork/open` |
| Regional LGA incident | `/v1/live/hazards/regional-lga-incident/open` |

The plugin exposes no generic URL, polygon, or provider-defined query interface.

## NSW Roads Traffic Volume Counts

`/v1/traffic_volume` supports arbitrary PostgreSQL through `q`, but the plugin exposes
no raw query parameter. The model-visible road-count tools select only constant
columns from documented tables with generated allowlisted filters and hard `LIMIT`
values.
