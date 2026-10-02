# tests/test_geo.py
# Tests for the location-recurrence helper (backend/geo.py).
#
# Uses the shared in-memory test engine from test_app_state (same pattern as
# the other suites) so the real Complaint table and query path are exercised.

import math
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402

import geo  # noqa: E402
from test_app_state import TestingSessionLocal  # noqa: E402
from models import Complaint  # noqa: E402


def _add_complaint(lat=None, lng=None, status="pending", email_suffix="") -> int:
    with TestingSessionLocal() as db:
        complaint = Complaint(
            name="Geo Test",
            email=f"geo-test{email_suffix}@example.com",
            complaint_text="Waste accumulation near the gate.",
            latitude=lat,
            longitude=lng,
            status=status,
            priority="medium",
            source="citizen",
        )
        db.add(complaint)
        db.commit()
        db.refresh(complaint)
        return complaint.id


@pytest.fixture(autouse=True)
def _geo_isolation():
    """geo tests share the in-memory DB with other suites; start each test empty."""
    with TestingSessionLocal() as db:
        db.query(Complaint).delete()
        db.commit()
    yield
    with TestingSessionLocal() as db:
        db.query(Complaint).delete()
        db.commit()


# ---------------------------------------------------------------------------
# Reference point: central Bengaluru (12.9716, 77.5946) — same as the workflow
# tests use. At this latitude 0.001 deg lat ≈ 111 m and 0.001 deg lng ≈ 108 m.
# ---------------------------------------------------------------------------
LAT0, LNG0 = 12.9716, 77.5946


# ---------------------------------------------------------------------------
# 1. nearby complaint counted
# ---------------------------------------------------------------------------
def test_nearby_complaint_is_counted():
    # ~11 m north of the reference point
    prior_id = _add_complaint(lat=LAT0 + 0.0001, lng=LNG0)
    outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0)
    assert outcome["success"] is True
    assert outcome["count"] == 1
    assert outcome["radius_m"] == 50


# ---------------------------------------------------------------------------
# 2. distant complaint ignored
# ---------------------------------------------------------------------------
def test_distant_complaint_ignored():
    # ~1.1 km away
    _add_complaint(lat=LAT0 + 0.01, lng=LNG0)
    outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0)
    assert outcome["success"] is True
    assert outcome["count"] == 0


# ---------------------------------------------------------------------------
# 3. current complaint excluded (only EARLIER ids count)
# ---------------------------------------------------------------------------
def test_current_complaint_excluded():
    earlier = _add_complaint(lat=LAT0 + 0.0001, lng=LNG0)   # ~11 m away
    current = _add_complaint(lat=LAT0 + 0.0002, lng=LNG0)   # ~22 m away
    outcome = geo.count_prior_reports_nearby(
        TestingSessionLocal(), LAT0 + 0.0002, LNG0, current_complaint_id=current
    )
    assert outcome["count"] == 1        # earlier one counted...
    # ...and passing the current id also excludes it when queried at its own coords
    outcome2 = geo.count_prior_reports_nearby(
        TestingSessionLocal(), LAT0 + 0.0001, LNG0, current_complaint_id=current
    )
    assert outcome2["count"] == 1
    assert earlier < current            # sanity: id order == insertion order


# ---------------------------------------------------------------------------
# 4. missing coordinates -> controlled 0
# ---------------------------------------------------------------------------
def test_missing_coordinates_return_zero():
    for lat, lng in [(None, LNG0), (LAT0, None), (None, None)]:
        outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), lat, lng)
        assert outcome["success"] is False
        assert outcome["count"] == 0
        assert outcome["reason"] == "missing_or_invalid_coordinates"


# ---------------------------------------------------------------------------
# 5. NULL-coordinate complaints ignored
# ---------------------------------------------------------------------------
def test_null_coordinate_complaints_ignored():
    _add_complaint(lat=None, lng=None)
    _add_complaint(lat=LAT0, lng=None)
    _add_complaint(lat=None, lng=LNG0)
    _add_complaint(lat=LAT0 + 0.0001, lng=LNG0)   # the only countable one
    outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0)
    assert outcome["success"] is True
    assert outcome["count"] == 1


# ---------------------------------------------------------------------------
# 6. multiple nearby complaints counted
# ---------------------------------------------------------------------------
def test_multiple_nearby_complaints_counted():
    _add_complaint(lat=LAT0 + 0.0001, lng=LNG0)              # ~11 m
    _add_complaint(lat=LAT0 - 0.0001, lng=LNG0)              # ~11 m
    _add_complaint(lat=LAT0, lng=LNG0 + 0.0001)              # ~11 m
    _add_complaint(lat=LAT0 + 0.01, lng=LNG0)                # ~1.1 km — outside
    _add_complaint(lat=None, lng=None)                        # NULL — ignored
    outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0)
    assert outcome["count"] == 3


# ---------------------------------------------------------------------------
# 7. exact radius boundary handled reasonably
# ---------------------------------------------------------------------------
def test_exact_radius_boundary():
    # Place a complaint at ~30 m and one at ~70 m; run with radius 50.
    lat_30m = LAT0 + 30.0 / 111_320.0
    lat_70m = LAT0 + 70.0 / 111_320.0
    _add_complaint(lat=lat_30m, lng=LNG0)
    _add_complaint(lat=lat_70m, lng=LNG0)

    outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0, radius_m=50)
    assert outcome["count"] == 1
    assert outcome["radius_m"] == 50

    # Inclusive boundary: a point at almost exactly 50 m is inside.
    # Compute a truly exact 50 m offset with Haversine itself.
    delta_deg = math.degrees(50.0 / (geo.EARTH_RADIUS_M * math.cos(math.radians(LAT0))))
    exact_id = _add_complaint(lat=LAT0, lng=LNG0 + delta_deg)
    _ = exact_id
    outcome_exact = geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0, radius_m=50)
    assert outcome_exact["count"] == 2   # both the ~30 m and the ~50 m point


# ---------------------------------------------------------------------------
# 8. configurable radius works
# ---------------------------------------------------------------------------
def test_configurable_radius():
    _add_complaint(lat=LAT0 + 70.0 / 111_320.0, lng=LNG0)   # ~70 m away
    assert geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0, radius_m=50)["count"] == 0
    assert geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0, radius_m=100)["count"] == 1
    assert geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0, radius_m=200)["count"] == 1


def test_radius_env_variable(monkeypatch):
    monkeypatch.setenv("WASTE_RECURRENCE_RADIUS_M", "250")
    assert geo.get_default_radius_m() == 250
    monkeypatch.setenv("WASTE_RECURRENCE_RADIUS_M", "junk")
    assert geo.get_default_radius_m() == 50      # junk -> documented default
    monkeypatch.setenv("WASTE_RECURRENCE_RADIUS_M", "-3")
    assert geo.get_default_radius_m() == 50      # non-positive -> default
    monkeypatch.setenv("WASTE_RECURRENCE_RADIUS_M", "100000")
    assert geo.get_default_radius_m() == 1000    # capped at 1000 m


# ---------------------------------------------------------------------------
# 9. invalid coordinates handled safely
# ---------------------------------------------------------------------------
def test_invalid_coordinates_return_controlled_zero():
    for lat, lng in [
        (999.0, LNG0),        # out of range lat
        (LAT0, 999.0),        # out of range lng
        (float("nan"), LNG0), # NaN
        (float("inf"), LNG0), # inf
        ("12.97", LNG0),      # string, not a number
    ]:
        outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), lat, lng)
        assert outcome["success"] is False
        assert outcome["count"] == 0


def test_invalid_db_rows_are_skipped_safely():
    """A legacy row with out-of-range junk coordinates must not crash the count."""
    _add_complaint(lat=999.0, lng=999.0)          # junk row inside the raw box filter
    _add_complaint(lat=LAT0 + 0.0001, lng=LNG0)   # one legit neighbor
    outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0)
    assert outcome["success"] is True
    assert outcome["count"] == 1


# ---------------------------------------------------------------------------
# Haversine sanity checks (pure function)
# ---------------------------------------------------------------------------
def test_haversine_known_distances():
    # 0.001 deg latitude ≈ 111.32 m
    d = geo.haversine_distance_m(12.0, 77.0, 12.001, 77.0)
    assert 110 < d < 113
    # identical points -> 0
    assert geo.haversine_distance_m(12.9716, 77.5946, 12.9716, 77.5946) == 0.0
    # symmetric
    assert geo.haversine_distance_m(12.0, 77.0, 13.0, 77.0) == pytest.approx(
        geo.haversine_distance_m(13.0, 77.0, 12.0, 77.0)
    )
    # ~111 km for one degree of latitude
    one_degree = geo.haversine_distance_m(12.0, 77.0, 13.0, 77.0)
    assert 110_000 < one_degree < 112_000


def test_haversine_antimeridian():
    # Crossing the antimeridian: 179.9995 -> -179.9995 is ~111 m at the equator,
    # not ~40,000 km the wrong way around.
    d = geo.haversine_distance_m(0.0, 179.9995, 0.0, -179.9995)
    assert d < 500


def test_zero_radius_counts_only_exact_same_point():
    _add_complaint(lat=LAT0 + 0.0001, lng=LNG0)
    outcome = geo.count_prior_reports_nearby(TestingSessionLocal(), LAT0, LNG0, radius_m=0)
    assert outcome["count"] == 0
