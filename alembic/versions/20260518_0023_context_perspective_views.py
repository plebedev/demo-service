"""Add materialized Context Engine perspective views.

Revision ID: 20260518_0023
Revises: 20260517_0022
Create Date: 2026-05-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260518_0023"
down_revision = "20260517_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create generic materialized perspective-view storage."""
    op.create_table(
        "context_perspective_views",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("domain_id", sa.String(length=128), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("view_definition_id", sa.String(length=128), nullable=False),
        sa.Column("view_json", sa.Text(), nullable=False),
        sa.Column("source_artifact_ids_json", sa.Text(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column(
            "latest_artifact_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "domain_id",
            "owner_type",
            "owner_id",
            "view_definition_id",
            name="uq_context_perspective_views_owner_view",
        ),
    )
    op.create_index(
        "ix_context_perspective_views_domain_id",
        "context_perspective_views",
        ["domain_id"],
    )
    op.create_index(
        "ix_context_perspective_views_owner",
        "context_perspective_views",
        ["domain_id", "owner_type", "owner_id"],
    )


def downgrade() -> None:
    """Drop generic materialized perspective-view storage."""
    op.drop_index(
        "ix_context_perspective_views_owner",
        table_name="context_perspective_views",
    )
    op.drop_index(
        "ix_context_perspective_views_domain_id",
        table_name="context_perspective_views",
    )
    op.drop_table("context_perspective_views")
