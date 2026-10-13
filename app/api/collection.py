"""Collection control and history."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.platform_authorization import require_collection_operator
from app.api.deps import get_db, get_runner
from app.core.constants import TriggerType
from app.database.models import CollectionRun
from app.schemas.collection import CollectionRunOut, RunSummary
from app.services.discovery_service import CollectionAlreadyRunning, CollectionRunner

router = APIRouter(prefix="/api/collection", tags=["collection"])

ALREADY_RUNNING = "A collection run is already in progress."


@router.post(
    "/run",
    dependencies=[Depends(require_collection_operator)],
    response_model=RunSummary,
    responses={409: {"description": ALREADY_RUNNING}, 202: {"description": "Started in background"}},
)
def run_collection(
    background: bool = Query(False, description="Return 202 immediately instead of waiting for the run"),
    runner: CollectionRunner = Depends(get_runner),
):
    """Trigger a discovery run now. Returns 409 if one is already running."""
    if background:
        if runner.is_running():
            raise HTTPException(status_code=409, detail=ALREADY_RUNNING)

        def _bg() -> None:
            try:
                runner.run(TriggerType.MANUAL)
            except CollectionAlreadyRunning:
                pass

        threading.Thread(target=_bg, name="manual-collection", daemon=True).start()
        return JSONResponse({"detail": "Collection started. Poll GET /api/collection/runs."}, status_code=202)
    try:
        return runner.run(TriggerType.MANUAL)
    except CollectionAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=ALREADY_RUNNING) from exc


@router.get("/runs", response_model=list[CollectionRunOut], dependencies=[Depends(require_collection_operator)])
def list_runs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)) -> list[CollectionRunOut]:
    rows = db.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(limit)).all()
    return [CollectionRunOut.model_validate(r) for r in rows]


@router.get("/runs/{run_id}", response_model=CollectionRunOut, dependencies=[Depends(require_collection_operator)])
def get_run(run_id: int, db: Session = Depends(get_db)) -> CollectionRunOut:
    run = db.get(CollectionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return CollectionRunOut.model_validate(run)
