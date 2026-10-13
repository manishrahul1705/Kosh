"""Shared FastAPI dependencies (wired from app.state in create_app)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.services.discovery_service import CollectionRunner


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_runner(request: Request) -> CollectionRunner:
    return request.app.state.runner


def get_document_worker(request: Request):
    """Stage 2B DocumentJobWorker of this process (None if not wired)."""
    return getattr(request.app.state, "document_worker", None)


def get_extraction_worker(request: Request):
    """Stage 3A ExtractionJobWorker of this process (None if not wired)."""
    return getattr(request.app.state, "extraction_worker", None)


def get_field_extraction_worker(request: Request):
    """Stage 3B FieldExtractionJobWorker of this process (None if not wired)."""
    return getattr(request.app.state, "field_extraction_worker", None)


def get_ai_analysis_worker(request: Request):
    """Stage 3C AIAnalysisJobWorker of this process (None if not wired)."""
    return getattr(request.app.state, "ai_analysis_worker", None)


def get_scheduler(request: Request):
    return getattr(request.app.state, "scheduler", None)
