"""add conversation_notes table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-29
"""
from collections.abc import Sequence

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE conversation_notes (
            id SERIAL PRIMARY KEY,
            phone TEXT NOT NULL,
            note TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT 'human'
            CHECK(author IN ('human', 'bot', 'system')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            FOREIGN KEY (phone) REFERENCES conversations(phone)
        )
    """)
    op.execute("""
        CREATE INDEX idx_conversation_notes_phone
        ON conversation_notes(phone)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_notes")
