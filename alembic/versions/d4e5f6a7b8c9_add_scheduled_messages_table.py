"""add scheduled_messages table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-20
"""
from collections.abc import Sequence

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE scheduled_messages (
            id SERIAL PRIMARY KEY,
            phone TEXT NOT NULL,
            template_name TEXT NOT NULL,
            components_json JSONB DEFAULT '[]',
            scheduled_at TIMESTAMPTZ NOT NULL,
            triggered_by_message_id TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING', 'SENT', 'CANCELLED', 'FAILED')),
            sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            FOREIGN KEY (phone) REFERENCES conversations(phone)
        )
    """)
    op.execute("""
        CREATE INDEX idx_scheduled_messages_due
        ON scheduled_messages(scheduled_at)
        WHERE status = 'PENDING'
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scheduled_messages")
