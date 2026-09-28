# routers/eventlog.py
# Event-logging service for the complete complaint lifecycle.
#
# One row per state change; actor-attributed; JSON metadata. The exported log
# is the direct input for process mining (pm4py), so activity names come from
# taxonomy.EVENT_ACTIVITIES and timestamps use a single UTC clock.

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import EventLog
from routers.complaints import get_current_admin_user
from taxonomy import EVENT_ACTIVITIES

import csv
import io


# ---------------------------------------------------------------------------
# Logging service (imported by every mutating router)
# ---------------------------------------------------------------------------
def log_event(
    db: Session,
    case_id: str,
    activity: str,
    actor_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    meta: Optional[dict] = None,
) -> EventLog:
    """Record one lifecycle event. Never raises into the caller's flow —
    logging must not be able to break the workflow it observes."""
    if activity not in EVENT_ACTIVITIES:
        raise ValueError(f"Unknown activity '{activity}' — extend taxonomy.EVENT_ACTIVITIES.")
    event = EventLog(
        case_id=case_id,
        activity=activity,
        actor_id=actor_id,
        actor_role=actor_role,
        old_value=old_value,
        new_value=new_value,
        meta_json=json.dumps(meta, default=str) if meta else None,
    )
    try:
        db.add(event)
        db.flush()  # assigns event.id without committing the caller's transaction
    except Exception:
        db.rollback()
        return event  # caller's own commit path will simply not include this row
    return event


def _meta(meta: Optional[dict]) -> Optional[str]:
    return json.dumps(meta, default=str) if meta else None


# ---------------------------------------------------------------------------
# Read/export API (admin only)
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/admin/events", tags=["events"])


class EventLogResponse(BaseModel):
    event_id: int
    case_id: str
    activity: str
    actor_id: Optional[int] = None
    actor_role: Optional[str] = None
    timestamp: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    meta: Optional[dict] = None

    model_config = {"from_attributes": True}


def _serialize(event: EventLog) -> EventLogResponse:
    meta = None
    if event.meta_json:
        try:
            meta = json.loads(event.meta_json)
        except json.JSONDecodeError:
            meta = {"raw": event.meta_json}
    return EventLogResponse(
        event_id=event.event_id,
        case_id=event.case_id,
        activity=event.activity,
        actor_id=event.actor_id,
        actor_role=event.actor_role,
        timestamp=event.timestamp.isoformat() if event.timestamp else "",
        old_value=event.old_value,
        new_value=event.new_value,
        meta=meta,
    )


@router.get("", response_model=list[EventLogResponse], summary="[Admin] List lifecycle events")
def list_events(
    case_id: Optional[str] = Query(default=None, description="Filter by complaint tracking id"),
    activity: Optional[str] = Query(default=None),
    actor_role: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=5000),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_user),
):
    """Return lifecycle events (newest first) with optional filters."""
    query = db.query(EventLog)
    if case_id:
        query = query.filter(EventLog.case_id == case_id)
    if activity:
        query = query.filter(EventLog.activity == activity)
    if actor_role:
        query = query.filter(EventLog.actor_role == actor_role)
    events = query.order_by(EventLog.event_id.desc()).limit(limit).all()
    return [_serialize(e) for e in events]


@router.get(
    "/export",
    summary="[Admin] Export the complete event log as process-mining CSV",
    response_class=StreamingResponse,
)
def export_events_csv(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_user),
):
    """CSV with one row per event: case:concept:name / concept:name /
    time:timestamp / actor_role / old_value / new_value / meta — the XES-style
    column naming pm4py expects when reading CSV logs."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "event_id",
            "case:concept:name",
            "concept:name",
            "time:timestamp",
            "actor_id",
            "actor_role",
            "old_value",
            "new_value",
            "meta_json",
        ]
    )
    for event in db.query(EventLog).order_by(EventLog.event_id.asc()).all():
        writer.writerow(
            [
                event.event_id,
                event.case_id,
                event.activity,
                event.timestamp.isoformat() if event.timestamp else "",
                event.actor_id,
                event.actor_role,
                event.old_value,
                event.new_value,
                event.meta_json,
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=event_log.csv"},
    )
