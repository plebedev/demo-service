"""Add Context Engine ingestion batch idempotency records.

Revision ID: 20261118_0026
Revises: 20261104_0025
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261118_0026"
down_revision = "20261104_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_ingestion_batches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("domain_id", sa.String(length=128), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("results_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "domain_id",
            "owner_type",
            "owner_id",
            "idempotency_key",
            name="uq_context_ingestion_batches_idempotency",
        ),
    )


def downgrade() -> None:
    op.drop_table("context_ingestion_batches")
