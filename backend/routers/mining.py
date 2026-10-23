# routers/mining.py
# Admin-protected access to the mining-ready dataset export.
# No mining algorithms here — see mining.py for the data-preparation rules.

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from mining import MINING_FIELDNAMES, build_mining_rows, export_mining_csv
from routers.complaints import get_current_admin_user

router = APIRouter(prefix="/admin/mining", tags=["dwm-mining"])


@router.get(
    "/dataset",
    summary="[Admin] Mining-ready dataset as JSON (one row per complaint)",
)
def get_mining_dataset(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_user),
):
    """Denormalized historical dataset for the DWM team's offline experiments
    (Decision Tree, Naive Bayes, K-Means, hierarchical clustering, Apriori).
    Missing facts are null — never imputed. Seeded rows are flagged
    is_synthetic=true so research data stays separable from citizen data."""
    rows = build_mining_rows(db)
    return {"fieldnames": MINING_FIELDNAMES, "count": len(rows), "rows": rows}


@router.get(
    "/dataset/export",
    summary="[Admin] Mining-ready dataset as CSV download",
    response_class=StreamingResponse,
)
def export_mining_dataset_csv(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin_user),
):
    rows = build_mining_rows(db)
    csv_text = export_mining_csv(rows)
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mining_dataset.csv"},
    )
