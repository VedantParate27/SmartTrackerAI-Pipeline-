"""Persistence API for the complete SmartTracker frontend workflow.

The existing complaint endpoints intentionally expose a small, stable domain
model.  The frontend prototype contains additional SRS entities that do not
yet have individual relational tables.  This API stores a validated snapshot
so every visible workflow action is durable instead of living only in one
browser's localStorage.
"""

import json
from json import JSONDecodeError
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from database import get_db
from models import AppStateSnapshot, utcnow


MAX_CASES = 2_000
MAX_POLICIES = 500
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024


class FrontendStatePayload(BaseModel):
    """The durable part of the client store.

    Nested records stay forward-compatible with the TypeScript domain model,
    while IDs and collection bounds are validated here to reject corrupt or
    accidentally unbounded snapshots.
    """

    cases: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_CASES)
    policies: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=MAX_POLICIES,
    )

    @model_validator(mode="after")
    def validate_records(self) -> "FrontendStatePayload":
        for label, records in (("case", self.cases), ("policy", self.policies)):
            identifiers: list[str] = []
            for index, record in enumerate(records):
                identifier = record.get("id")
                if not isinstance(identifier, str) or not identifier.strip():
                    raise ValueError(f"{label} at index {index} must have a non-empty id")
                identifiers.append(identifier.strip().upper())

            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"Duplicate {label} ids are not allowed")

        encoded = json.dumps(
            self.model_dump(mode="json"),
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise ValueError("Application state exceeds the 5 MB storage limit")
        return self


class AppStateResponse(BaseModel):
    state: FrontendStatePayload | None
    revision: int
    updated_at: str | None


router = APIRouter(prefix="/app", tags=["application state"])


def response_for(snapshot: AppStateSnapshot | None) -> AppStateResponse:
    if snapshot is None:
        return AppStateResponse(state=None, revision=0, updated_at=None)

    try:
        payload = FrontendStatePayload.model_validate(json.loads(snapshot.payload))
    except (JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored application state is invalid.",
        ) from exc

    return AppStateResponse(
        state=payload,
        revision=snapshot.revision,
        updated_at=snapshot.updated_at.isoformat(),
    )


@router.get("/state", response_model=AppStateResponse)
def get_app_state(db: Session = Depends(get_db)):
    """Load the most recently persisted workflow state."""
    return response_for(db.get(AppStateSnapshot, 1))


@router.put("/state", response_model=AppStateResponse)
def put_app_state(body: FrontendStatePayload, db: Session = Depends(get_db)):
    """Create or atomically replace the shared workflow state."""
    snapshot = db.get(AppStateSnapshot, 1)
    encoded = json.dumps(body.model_dump(mode="json"), separators=(",", ":"))

    if snapshot is None:
        snapshot = AppStateSnapshot(
            id=1,
            payload=encoded,
            revision=1,
            updated_at=utcnow(),
        )
        db.add(snapshot)
    else:
        snapshot.payload = encoded
        snapshot.revision += 1
        snapshot.updated_at = utcnow()

    db.commit()
    db.refresh(snapshot)
    return response_for(snapshot)
