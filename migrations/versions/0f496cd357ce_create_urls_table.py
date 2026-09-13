"""create urls table

The initial schema. Everything before this migration was created by
Base.metadata.create_all(), which makes tables but never alters them — an
existing database created that way needs `alembic stamp head` once before
future migrations will apply cleanly.

Revision ID: 0f496cd357ce
Revises:
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0f496cd357ce"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "urls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("original_url", sa.String(), nullable=False),
        sa.Column("short_code", sa.String(length=50), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        # func.now() renders per dialect: CURRENT_TIMESTAMP on SQLite, now() on
        # Postgres. A literal would have been portable only by accident.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("urls", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_urls_short_code"), ["short_code"], unique=True)
        batch_op.create_index(batch_op.f("ix_urls_expires_at"), ["expires_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("urls", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_urls_expires_at"))
        batch_op.drop_index(batch_op.f("ix_urls_short_code"))

    op.drop_table("urls")
