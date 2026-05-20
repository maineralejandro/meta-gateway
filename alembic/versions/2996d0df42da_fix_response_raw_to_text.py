"""fix_response_raw_to_text

Revision ID: 2996d0df42da
Revises: ddd37b2a9d4b
Create Date: 2026-05-15 19:32:15.485637

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '2996d0df42da'
down_revision: str | Sequence[str] | None = 'ddd37b2a9d4b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('inference_traces', 'response_raw',
                    existing_type=sa.dialects.postgresql.JSONB(),
                    type_=sa.Text(),
                    existing_nullable=True,
                    postgresql_using='response_raw::text')
    op.drop_constraint('fk_sessions_phone', 'sessions', type_='foreignkey')
    op.create_foreign_key('fk_sessions_phone', 'sessions', 'conversations',
                          ['phone'], ['phone'],
                          deferrable=True, initially='deferred')


def downgrade() -> None:
    op.drop_constraint('fk_sessions_phone', 'sessions', type_='foreignkey')
    op.create_foreign_key('fk_sessions_phone', 'sessions', 'conversations',
                          ['phone'], ['phone'])
    op.alter_column('inference_traces', 'response_raw',
                    existing_type=sa.Text(),
                    type_=sa.dialects.postgresql.JSONB(),
                    existing_nullable=True,
                    postgresql_using='response_raw::jsonb')
