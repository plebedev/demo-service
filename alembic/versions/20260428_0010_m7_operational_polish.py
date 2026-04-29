"""Add M7 invitation review and run failure metadata.

Revision ID: 20260428_0010
Revises: 20260428_0009
Create Date: 2026-04-28 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260428_0010"
down_revision = "20260428_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invitation_requests",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("invitation_requests", sa.Column("reviewer_note", sa.Text()))
    op.add_column(
        "invitation_codes",
        sa.Column("invitation_request_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_inv_codes_req_id",
        "invitation_codes",
        "invitation_requests",
        ["invitation_request_id"],
        ["id"],
    )
    op.create_index(
        "ix_inv_codes_req_id",
        "invitation_codes",
        ["invitation_request_id"],
    )
    op.add_column("runs", sa.Column("failure_message", sa.Text(), nullable=True))
    op.add_column(
        "runs", sa.Column("failure_internal_reason", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("runs", "failure_internal_reason")
    op.drop_column("runs", "failure_message")
    op.drop_index("ix_inv_codes_req_id", table_name="invitation_codes")
    op.drop_constraint(
        "fk_inv_codes_req_id",
        "invitation_codes",
        type_="foreignkey",
    )
    op.drop_column("invitation_codes", "invitation_request_id")
    op.drop_column("invitation_requests", "reviewer_note")
    op.drop_column("invitation_requests", "reviewed_at")
