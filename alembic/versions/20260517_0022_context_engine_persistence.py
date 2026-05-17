"""Add generic Context Engine persistence tables.

Revision ID: 20260517_0022
Revises: 20260508_0021
Create Date: 2026-05-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260517_0022"
down_revision = "20260508_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_artifacts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("domain_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_type_id", sa.String(length=128), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_uri", sa.String(length=1024), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_context_artifacts_domain_id", "context_artifacts", ["domain_id"]
    )
    op.create_index(
        "ix_context_artifacts_owner",
        "context_artifacts",
        ["domain_id", "owner_type", "owner_id"],
    )

    op.create_table(
        "context_artifact_chunks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("source_link_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["context_artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "artifact_id",
            "chunk_index",
            name="uq_context_artifact_chunks_artifact_index",
        ),
    )
    op.create_index(
        "ix_context_artifact_chunks_artifact_id",
        "context_artifact_chunks",
        ["artifact_id"],
    )

    op.create_table(
        "context_entities",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("domain_id", sa.String(length=128), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("source_links_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_context_entities_domain_id", "context_entities", ["domain_id"])
    op.create_index(
        "ix_context_entities_owner",
        "context_entities",
        ["domain_id", "owner_type", "owner_id"],
    )

    op.create_table(
        "context_relationships",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("domain_id", sa.String(length=128), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("relationship_type", sa.String(length=128), nullable=False),
        sa.Column("source_entity_id", sa.String(length=64), nullable=False),
        sa.Column("target_entity_id", sa.String(length=64), nullable=False),
        sa.Column("source_links_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_context_relationships_domain_id",
        "context_relationships",
        ["domain_id"],
    )
    op.create_index(
        "ix_context_relationships_owner",
        "context_relationships",
        ["domain_id", "owner_type", "owner_id"],
    )

    op.create_table(
        "context_signals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("domain_id", sa.String(length=128), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("signal_type", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=True),
        sa.Column("source_links_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_context_signals_domain_id", "context_signals", ["domain_id"])
    op.create_index(
        "ix_context_signals_owner",
        "context_signals",
        ["domain_id", "owner_type", "owner_id"],
    )

    op.create_table(
        "context_actionable_items",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("domain_id", sa.String(length=128), nullable=False),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("item_type", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("readiness_status", sa.String(length=64), nullable=False),
        sa.Column("source_links_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_context_actionable_items_domain_id",
        "context_actionable_items",
        ["domain_id"],
    )
    op.create_index(
        "ix_context_actionable_items_owner",
        "context_actionable_items",
        ["domain_id", "owner_type", "owner_id"],
    )

    op.create_table(
        "context_source_links",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=512), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_context_source_links_artifact_id",
        "context_source_links",
        ["artifact_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_context_source_links_artifact_id", table_name="context_source_links"
    )
    op.drop_table("context_source_links")
    op.drop_index(
        "ix_context_actionable_items_owner",
        table_name="context_actionable_items",
    )
    op.drop_index(
        "ix_context_actionable_items_domain_id",
        table_name="context_actionable_items",
    )
    op.drop_table("context_actionable_items")
    op.drop_index("ix_context_signals_owner", table_name="context_signals")
    op.drop_index("ix_context_signals_domain_id", table_name="context_signals")
    op.drop_table("context_signals")
    op.drop_index(
        "ix_context_relationships_owner",
        table_name="context_relationships",
    )
    op.drop_index(
        "ix_context_relationships_domain_id",
        table_name="context_relationships",
    )
    op.drop_table("context_relationships")
    op.drop_index("ix_context_entities_owner", table_name="context_entities")
    op.drop_index("ix_context_entities_domain_id", table_name="context_entities")
    op.drop_table("context_entities")
    op.drop_index(
        "ix_context_artifact_chunks_artifact_id",
        table_name="context_artifact_chunks",
    )
    op.drop_table("context_artifact_chunks")
    op.drop_index("ix_context_artifacts_owner", table_name="context_artifacts")
    op.drop_index("ix_context_artifacts_domain_id", table_name="context_artifacts")
    op.drop_table("context_artifacts")
