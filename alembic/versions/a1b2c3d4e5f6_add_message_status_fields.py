"""add_message_status_fields

Revision ID: a1b2c3d4e5f6
Revises: 2996d0df42da
Create Date: 2026-05-20 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '2996d0df42da'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('meta_status', sa.Text(), nullable=True))
    op.add_column('messages', sa.Column('meta_status_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_index('idx_messages_meta_status', 'messages', ['meta_status'])


def downgrade() -> None:
    op.drop_index('idx_messages_meta_status', table_name='messages')
    op.drop_column('messages', 'meta_status_at')
    op.drop_column('messages', 'meta_status')
