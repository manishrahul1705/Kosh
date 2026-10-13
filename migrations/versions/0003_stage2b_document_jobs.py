"""Stage 2B: automated document job processing.

Revision ID: 0003_stage2b
Revises: 0002_stage2
Create Date: 2026-10-06

Changes (all additive, existing rows preserved):

* document_jobs: new nullable columns ``reason``, ``locked_by``, ``outcome``,
  ``result_summary``. Existing jobs keep ``reason = NULL`` (= "created before
  Stage 2B"); their status / attempt_count are untouched.
* document_jobs: index (status, next_retry_at) for the worker's claim scan.
* document_jobs: partial UNIQUE index on tender_id WHERE status IN
  ('PENDING','RETRY') -> at most one *queued* job per tender. Pre-existing
  duplicate queued jobs (if any) are NOT deleted: every duplicate except the
  oldest is marked SKIPPED with error_code DUPLICATE_QUEUED first.
* document_versions: UNIQUE (document_id, version_number) and UNIQUE
  (document_id, sha256). Created only if the existing data has no duplicates;
  otherwise the index is skipped with a warning so no historical version is
  ever destroyed (Stage 2A application-level dedup still applies).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_stage2b"
down_revision: Union[str, None] = "0002_stage2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.0003_stage2b")

QUEUED_WHERE = "status IN ('PENDING', 'RETRY')"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _index_names(bind, table: str) -> set[str]:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def _column_names(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # -- document_jobs: new columns ------------------------------------------
    existing_cols = _column_names(bind, "document_jobs")
    for name, type_ in (
        ("reason", sa.String(length=32)),
        ("locked_by", sa.String(length=128)),
        ("outcome", sa.String(length=40)),
        ("result_summary", sa.Text()),
    ):
        if name not in existing_cols:
            op.add_column("document_jobs", sa.Column(name, type_, nullable=True))

    # -- document_jobs: neutralise duplicate queued jobs (never delete) -------
    dupes = bind.execute(
        sa.text(
            f"SELECT tender_id, MIN(id) AS keep_id FROM document_jobs "
            f"WHERE {QUEUED_WHERE} GROUP BY tender_id HAVING COUNT(*) > 1"
        )
    ).fetchall()
    now = _now()
    skipped = 0
    for tender_id, keep_id in dupes:
        res = bind.execute(
            sa.text(
                f"UPDATE document_jobs SET status = 'SKIPPED', error_code = 'DUPLICATE_QUEUED', "
                f"error_message = :msg, finished_at = :now, updated_at = :now "
                f"WHERE tender_id = :tid AND id <> :keep AND {QUEUED_WHERE}"
            ),
            {"msg": f"Duplicate queued job superseded by job {keep_id} (migration 0003)",
             "now": now, "tid": tender_id, "keep": keep_id},
        )
        skipped += res.rowcount or 0
    if skipped:
        logger.warning("0003_stage2b: marked %s duplicate queued document job(s) SKIPPED", skipped)

    # -- document_jobs: indexes ----------------------------------------------
    job_indexes = _index_names(bind, "document_jobs")
    if "ix_document_jobs_status_next_retry" not in job_indexes:
        op.create_index("ix_document_jobs_status_next_retry", "document_jobs", ["status", "next_retry_at"])
    if "uq_document_jobs_tender_queued" not in job_indexes:
        op.create_index(
            "uq_document_jobs_tender_queued",
            "document_jobs",
            ["tender_id"],
            unique=True,
            sqlite_where=sa.text(QUEUED_WHERE),
            postgresql_where=sa.text(QUEUED_WHERE),
        )

    # -- document_versions: uniqueness (only if data is already clean) --------
    version_indexes = _index_names(bind, "document_versions")
    dup_versions = bind.execute(
        sa.text(
            "SELECT document_id, version_number, COUNT(*) FROM document_versions "
            "GROUP BY document_id, version_number HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if "uq_document_versions_document_version" not in version_indexes:
        if dup_versions:
            logger.warning(
                "0003_stage2b: NOT creating uq_document_versions_document_version - "
                "%s duplicate (document_id, version_number) group(s) exist: %s",
                len(dup_versions), [tuple(r) for r in dup_versions[:10]],
            )
        else:
            op.create_index(
                "uq_document_versions_document_version",
                "document_versions",
                ["document_id", "version_number"],
                unique=True,
            )

    dup_hashes = bind.execute(
        sa.text(
            "SELECT document_id, sha256, COUNT(*) FROM document_versions "
            "WHERE sha256 IS NOT NULL GROUP BY document_id, sha256 HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if "uq_document_versions_document_sha256" not in version_indexes:
        if dup_hashes:
            logger.warning(
                "0003_stage2b: NOT creating uq_document_versions_document_sha256 - "
                "%s duplicate (document_id, sha256) group(s) exist: %s",
                len(dup_hashes), [(r[0], (r[1] or "")[:12]) for r in dup_hashes[:10]],
            )
        else:
            op.create_index(
                "uq_document_versions_document_sha256",
                "document_versions",
                ["document_id", "sha256"],
                unique=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    version_indexes = _index_names(bind, "document_versions")
    for name in ("uq_document_versions_document_sha256", "uq_document_versions_document_version"):
        if name in version_indexes:
            op.drop_index(name, table_name="document_versions")
    job_indexes = _index_names(bind, "document_jobs")
    for name in ("uq_document_jobs_tender_queued", "ix_document_jobs_status_next_retry"):
        if name in job_indexes:
            op.drop_index(name, table_name="document_jobs")
    existing_cols = _column_names(bind, "document_jobs")
    with op.batch_alter_table("document_jobs") as batch_op:
        for name in ("result_summary", "outcome", "locked_by", "reason"):
            if name in existing_cols:
                batch_op.drop_column(name)
