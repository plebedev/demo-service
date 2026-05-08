"""Add invitation namespace to messy notes runs.

Revision ID: 20260508_0021
Revises: 20260509_0020
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260508_0021"
down_revision = "20260509_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("runs")}
    indexes = {index["name"] for index in inspector.get_indexes("runs")}
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("runs")}

    if "invitation_code_id" not in columns:
        op.add_column(
            "runs",
            sa.Column("invitation_code_id", sa.Integer(), nullable=True),
        )
    if "ix_runs_invitation_code_id" not in indexes:
        op.create_index(
            "ix_runs_invitation_code_id",
            "runs",
            ["invitation_code_id"],
        )
    if "fk_runs_invitation_code_id" not in foreign_keys:
        op.create_foreign_key(
            "fk_runs_invitation_code_id",
            "runs",
            "invitation_codes",
            ["invitation_code_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("runs")}
    indexes = {index["name"] for index in inspector.get_indexes("runs")}
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("runs")}

    if "fk_runs_invitation_code_id" in foreign_keys:
        op.drop_constraint(
            "fk_runs_invitation_code_id",
            "runs",
            type_="foreignkey",
        )
    if "ix_runs_invitation_code_id" in indexes:
        op.drop_index("ix_runs_invitation_code_id", table_name="runs")
    if "invitation_code_id" in columns:
        op.drop_column("runs", "invitation_code_id")
