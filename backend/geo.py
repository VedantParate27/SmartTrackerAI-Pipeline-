# geo.py
# Location-recurrence helper for the waste-AI integration.
#
# The AI (process_waste_image) requires `prior_reports_at_location` — a count
# of previous reports at the same spot — supplied by the backend (the AI never
# queries a database; see WASTE_MODULE_REPORT.md on branch
# waste-image-classification).
#
# Algorithm: cheap SQL bounding-box prefilter (SQLite-friendly, no geo
# extension) followed by exact Haversine distance filtering in Python.
# Complaint volumes make this trivially fast without PostGIS or a spatial index.
#
# Radius policy (documented choice, not a magic number):
#   default 50 m, configurable via WASTE_RECURRENCE_RADIUS_M. Smartphone GPS in
#   urban conditions is accurate to ~5-15 m, degrading to 30-50 m in urban
#   canyons; 50 m roughly means "same street spot". A much larger default would
#   count neighbouring blocks as the same site (false recurrence).
#
# All functions are total: bad/missing coordinates return controlled results
# and never raise into the caller (complaint creation must not crash).

import math
import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RADIUS_ENV = "WASTE_RECURRENCE_RADIUS_M"
DEFAULT_RADIUS_M = 50

# Hard sanity bounds for latitude/longitude as decimal degrees.
MIN_LAT, MAX_LAT = -90.0, 90.0
MIN_LNG, MAX_LNG = -180.0, 180.0

EARTH_RADIUS_M = 6_371_000.0  # mean Earth radius, metres


def get_default_radius_m() -> int:
    """Configured default radius in metres (WASTE_RECURRENCE_RADIUS_M, default 50).

    Invalid/junk values fall back to the documented default; a value is capped
    at 1000 m so a typo cannot silently turn 'same spot' into 'same district'.
    """
    raw = os.getenv(RADIUS_ENV, str(DEFAULT_RADIUS_M)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RADIUS_M
    if value <= 0:
        return DEFAULT_RADIUS_M
    return min(value, 1000)


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def is_valid_coordinates(latitude, longitude) -> bool:
    """True only for finite, in-range numeric coordinates."""
    if not isinstance(latitude, (int, float)) or isinstance(latitude, bool):
        return False
    if not isinstance(longitude, (int, float)) or isinstance(longitude, bool):
        return False
    lat, lng = float(latitude), float(longitude)
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return False
    return MIN_LAT <= lat <= MAX_LAT and MIN_LNG <= lng <= MAX_LNG


def _bounding_box(latitude: float, longitude: float, radius_m: int) -> tuple[float, float, float, float]:
    """Lat/lng box that strictly contains a circle of `radius_m` metres.

    Longitude degrees shrink with cosine of latitude; near the poles the lng
    span widens safely (over-wide is fine — Haversine does the exact filter).
    """
    lat_delta = math.degrees(radius_m / EARTH_RADIUS_M)
    cos_lat = max(abs(math.cos(math.radians(latitude))), 1e-6)
    lng_delta = math.degrees(radius_m / (EARTH_RADIUS_M * cos_lat))
    return (
        latitude - lat_delta, latitude + lat_delta,
        longitude - lng_delta, longitude + lng_delta,
    )


def count_prior_reports_nearby(
    db,
    latitude,
    longitude,
    current_complaint_id: int | None = None,
    radius_m: int | None = None,
) -> dict:
    """Count EARLIER complaints within `radius_m` metres of a coordinate.

    Returns a controlled dict (never raises):
      {"success": True,  "count": int, "radius_m": int}
      {"success": False, "count": 0, "radius_m": int, "reason": str}

    Rules (per the waste-AI recurrence design):
      - missing/invalid coordinates        -> success False, count 0 (fail-open)
      - complaints with NULL lat/lng       -> ignored (SQL filter)
      - only EARLIER complaints count      -> ids strictly lower than the
        current complaint's id when `current_complaint_id` is supplied
        (id order == submission order; no timestamp parsing needed)
      - status is irrelevant: a resolved complaint at the same corner is still
        evidence of a recurring problem
    """
    if radius_m is None:
        radius_m = get_default_radius_m()

    if not is_valid_coordinates(latitude, longitude):
        return {
            "success": False,
            "count": 0,
            "radius_m": radius_m,
            "reason": "missing_or_invalid_coordinates",
        }

    from models import Complaint  # local import: avoids cycles at module load

    lat = float(latitude)
    lng = float(longitude)
    min_lat, max_lat, min_lng, max_lng = _bounding_box(lat, lng, radius_m)

    query = db.query(Complaint.id, Complaint.latitude, Complaint.longitude).filter(
        Complaint.latitude.isnot(None),
        Complaint.longitude.isnot(None),
        Complaint.latitude >= min_lat,
        Complaint.latitude <= max_lat,
        Complaint.longitude >= min_lng,
        Complaint.longitude <= max_lng,
    )
    if current_complaint_id is not None:
        query = query.filter(Complaint.id < current_complaint_id)

    count = 0
    for _cid, row_lat, row_lng in query.all():
        # Defensive re-validation: a legacy row could hold out-of-range junk.
        if not is_valid_coordinates(row_lat, row_lng):
            continue
        if haversine_distance_m(lat, lng, float(row_lat), float(row_lng)) <= float(radius_m):
            count += 1

    return {"success": True, "count": count, "radius_m": radius_m}


def count_prior_reports_nearby_or_zero(
    db,
    latitude,
    longitude,
    current_complaint_id: int | None = None,
    radius_m: int | None = None,
) -> int:
    """Convenience wrapper for the AI-call site: returns just the count (0 on any problem)."""
    outcome = count_prior_reports_nearby(
        db, latitude, longitude, current_complaint_id=current_complaint_id, radius_m=radius_m
    )
    return outcome["count"]
