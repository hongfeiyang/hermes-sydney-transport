# TfNSW endpoint and macro reference

Validation date: 12 August 2026 (Australia/Sydney).

## Trip Planner macros

| Endpoint | Internal parameters | Purpose |
|---|---|---|
| `/stop_finder` | `TfNSWSF=true` | TfNSW stop matching |
| `/departure_mon` | `departureMonitorMacro=true`, `TfNSWDM=true` | Departure board and realtime fields |
| `/coord` | `PoisOnMapMacro=true` | Nearby public-transport stops |
| `/trip` | `depArrMacro=dep|arr`, `TfNSWTR=true` | Depart-after/arrive-by journey planning |
| `/add_info` | repeated `filterMOTType=1|5` | Train/bus current alerts |

Macros are policy, not model inputs. Train is product/MOT class `1`, bus is `5`.
Other classes are excluded from departures and journeys unless later added as an
explicit supported mode. Walking legs can still appear inside a journey.

The legacy specification's optional engine `version=10.2.1.42` is omitted.
The current engine also rejects `type_sf=stop`, so stop search uses `type_sf=any` and
then requires an intersection with the requested mode list.

## GTFS and GTFS-Realtime

| Mode | Static | Trip Updates | Vehicle Positions |
|---|---|---|---|
| Train | `/v1/gtfs/schedule/sydneytrains` | `/v2/gtfs/realtime/sydneytrains` | `/v2/gtfs/vehiclepos/sydneytrains` |
| Bus | `/v1/gtfs/schedule/buses` | `/v1/gtfs/realtime/buses` | `/v1/gtfs/vehiclepos/buses` |

The join key is Trip Planner `properties.RealtimeTripId` to GTFS/GTFS-R `trip_id`.
The shorter `tripCode` is only a fallback locator and is never treated as a trip ID.

## NSW Roads

`/v1/traffic_volume` supports arbitrary PostgreSQL through `q`, but the plugin exposes
no raw query parameter. The three model-visible tools select only constant columns
from documented tables with generated allowlisted filters and hard LIMIT values.
