"""add_whatsapp_templates_table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-20 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE whatsapp_templates (
            id SERIAL PRIMARY KEY,
            agent_id INTEGER NOT NULL DEFAULT 1,
            template_name TEXT NOT NULL UNIQUE,
            template_type TEXT NOT NULL DEFAULT 'UTILITY'
                CHECK(template_type IN ('MARKETING', 'UTILITY', 'AUTHENTICATION')),
            category TEXT NOT NULL DEFAULT 'UTILITY',
            language TEXT NOT NULL DEFAULT 'es',
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'PAUSED', 'DISABLED')),
            body_text TEXT NOT NULL,
            header_text TEXT,
            header_image_url TEXT,
            footer_text TEXT,
            buttons_json JSONB DEFAULT '[]',
            meta_template_id TEXT,
            meta_quality_rating TEXT,
            rejection_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
        );

        CREATE INDEX idx_wa_templates_agent ON whatsapp_templates(agent_id);
        CREATE INDEX idx_wa_templates_status ON whatsapp_templates(status);
        CREATE INDEX idx_wa_templates_name ON whatsapp_templates(template_name);
    """)

    op.add_column('promotions', sa.Column('template_name', sa.Text(), nullable=True))
    op.add_column('promotions', sa.Column('coupon_code', sa.Text(), nullable=True))
    op.add_column('promotions', sa.Column('offer_expiration_ts', sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('promotions', 'offer_expiration_ts')
    op.drop_column('promotions', 'coupon_code')
    op.drop_column('promotions', 'template_name')
    op.execute("DROP TABLE IF EXISTS whatsapp_templates;")
