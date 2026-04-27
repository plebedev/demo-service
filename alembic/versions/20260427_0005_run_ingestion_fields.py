"""Add ingestion storage fields to runs.

Revision ID: 20260427_0005
Revises: 20260426_0004
Create Date: 2026-04-27 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260427_0005"
down_revision = "20260426_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("normalized_input_text", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("uploaded_files_json", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("ingestion_summary_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "ingestion_summary_json")
    op.drop_column("runs", "uploaded_files_json")
    op.drop_column("runs", "normalized_input_text")
