"""initial_postgres_schema

Revision ID: ddd37b2a9d4b
Revises:
Create Date: 2026-05-15 11:44:11.568782

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = 'ddd37b2a9d4b'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'schema_migrations',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('version', sa.String, nullable=False, unique=True),
        sa.Column('description', sa.String, nullable=True),
        sa.Column('applied_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
    )

    op.create_table(
        'agents',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String, nullable=False, unique=True),
        sa.Column('description', sa.String, nullable=False, server_default=''),
        sa.Column('system_prompt', sa.String, nullable=False),
        sa.Column('escalation_marker', sa.String, nullable=False, server_default='ESCALATE_TO_HUMAN'),
        sa.Column('fallback_responses', JSONB, nullable=False, server_default='{}'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('TRUE')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
    )

    op.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            started_at TIMESTAMPTZ DEFAULT NOW(),
            ended_at TIMESTAMPTZ,
            end_reason TEXT,
            summary TEXT,
            message_count INTEGER NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE conversations (
            phone TEXT PRIMARY KEY,
            contact_name TEXT,
            state TEXT NOT NULL DEFAULT 'BOT_ACTIVE' CHECK(state IN ('BOT_ACTIVE','PENDING_APPROVAL','HUMAN_ONLY')),
            last_message_at TIMESTAMPTZ DEFAULT NOW(),
            requires_human_review BOOLEAN NOT NULL DEFAULT FALSE,
            unread_count INTEGER NOT NULL DEFAULT 0,
            sentiment_score DOUBLE PRECISION,
            confidence DOUBLE PRECISION,
            agent_id INTEGER DEFAULT 1,
            current_session_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            FOREIGN KEY (agent_id) REFERENCES agents(id),
            FOREIGN KEY (current_session_id) REFERENCES sessions(id) DEFERRABLE INITIALLY DEFERRED
        )
    """)

    op.execute("""
        ALTER TABLE sessions
        ADD CONSTRAINT fk_sessions_phone
        FOREIGN KEY (phone) REFERENCES conversations(phone)
    """)

    op.create_index('idx_sessions_phone', 'sessions', ['phone', 'started_at'])
    op.create_index('idx_conversations_state', 'conversations', ['state'])

    op.create_table(
        'messages',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('phone', sa.String, nullable=False),
        sa.Column('direction', sa.String, nullable=False),
        sa.Column('source', sa.String, nullable=False),
        sa.Column('text', sa.String, nullable=True),
        sa.Column('media_type', sa.String, nullable=True),
        sa.Column('media_url', sa.String, nullable=True),
        sa.Column('meta_message_id', sa.String, nullable=True),
        sa.Column('session_id', sa.String, nullable=True),
        sa.Column('correlation_id', sa.String, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.CheckConstraint("direction IN ('inbound','outbound')", name='ck_messages_direction'),
        sa.CheckConstraint("source IN ('bot','human','customer')", name='ck_messages_source'),
        sa.ForeignKeyConstraint(['phone'], ['conversations.phone']),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id']),
    )

    op.create_index('idx_messages_phone', 'messages', ['phone', 'created_at'])

    op.create_table(
        'escalation_events',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('phone', sa.String, nullable=False),
        sa.Column('from_state', sa.String, nullable=False),
        sa.Column('to_state', sa.String, nullable=False),
        sa.Column('reason', sa.String, nullable=True),
        sa.Column('sentiment_score', sa.Float, nullable=True),
        sa.Column('confidence', sa.Float, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['phone'], ['conversations.phone']),
    )

    op.create_index('idx_escalation_phone', 'escalation_events', ['phone'])
    op.create_index('idx_agents_is_active', 'agents', ['is_active'])

    op.create_table(
        'agent_decisions',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('message_id', sa.Integer, nullable=True),
        sa.Column('phone', sa.String, nullable=False),
        sa.Column('sentiment', sa.String, nullable=False, server_default='neutral'),
        sa.Column('sentiment_score', sa.Float, nullable=False, server_default='0.5'),
        sa.Column('confidence', sa.Float, nullable=False, server_default='0.5'),
        sa.Column('llm_escalate', sa.Boolean, nullable=False, server_default=sa.text('FALSE')),
        sa.Column('escalate_reason', sa.String, nullable=True),
        sa.Column('history_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('agent_name', sa.String, nullable=False, server_default=''),
        sa.Column('correlation_id', sa.String, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id']),
    )

    op.create_index('idx_decisions_message', 'agent_decisions', ['message_id'])
    op.create_index('idx_decisions_phone', 'agent_decisions', ['phone'])

    op.create_table(
        'conversation_memory',
        sa.Column('phone', sa.String, primary_key=True),
        sa.Column('summary', sa.String, nullable=False, server_default=''),
        sa.Column('key_facts', JSONB, nullable=False, server_default='[]'),
        sa.Column('total_messages_summarized', sa.Integer, nullable=False, server_default='0'),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['phone'], ['conversations.phone']),
    )

    op.create_index('idx_memory_phone', 'conversation_memory', ['phone'])

    op.create_table(
        'carts',
        sa.Column('phone', sa.String, primary_key=True),
        sa.Column('items_json', JSONB, nullable=False, server_default='[]'),
        sa.Column('total', sa.Integer, nullable=False, server_default='0'),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['phone'], ['conversations.phone']),
    )

    op.create_index('idx_carts_phone', 'carts', ['phone'])

    op.create_table(
        'catalog_items',
        sa.Column('key', sa.String, primary_key=True),
        sa.Column('name', sa.String, nullable=False),
        sa.Column('price', sa.Integer, nullable=False),
        sa.Column('category', sa.String, nullable=False, server_default='general'),
        sa.Column('subcategory', sa.String, nullable=False, server_default=''),
        sa.Column('base_price', sa.Integer, nullable=True),
        sa.Column('is_available', sa.Boolean, nullable=False, server_default=sa.text('TRUE')),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('description', sa.String, nullable=False, server_default=''),
        sa.Column('tags', JSONB, nullable=False, server_default='[]'),
        sa.Column('size', sa.String, nullable=False, server_default=''),
        sa.Column('specifications', sa.String, nullable=False, server_default=''),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
    )

    op.create_index('idx_catalog_items_category', 'catalog_items', ['category'])

    op.create_table(
        'catalog_item_variants',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('item_key', sa.String, nullable=False),
        sa.Column('label', sa.String, nullable=False),
        sa.Column('price', sa.Integer, nullable=False),
        sa.Column('slug', sa.String, nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['item_key'], ['catalog_items.key'], ondelete='CASCADE'),
        sa.UniqueConstraint('item_key', 'slug', name='uq_variants_item_key_slug'),
    )

    op.create_index('idx_catalog_variants_item_key', 'catalog_item_variants', ['item_key'])

    op.create_table(
        'catalog_options',
        sa.Column('key', sa.String, primary_key=True),
        sa.Column('name', sa.String, nullable=False),
        sa.Column('price', sa.Integer, nullable=False),
        sa.Column('category_scope', sa.String, nullable=False, server_default='*'),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
    )

    op.create_table(
        'promotions',
        sa.Column('key', sa.String, primary_key=True),
        sa.Column('name', sa.String, nullable=False),
        sa.Column('promotion_type', sa.String, nullable=False, server_default='fixed_price'),
        sa.Column('price', sa.Integer, nullable=True),
        sa.Column('display_text', sa.String, nullable=False, server_default=''),
        sa.Column('valid_days', JSONB, nullable=False, server_default='[]'),
        sa.Column('valid_from', sa.String, nullable=False, server_default=''),
        sa.Column('valid_to', sa.String, nullable=False, server_default=''),
        sa.Column('terms', sa.String, nullable=False, server_default=''),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.CheckConstraint(
            "promotion_type IN ('fixed_price','percentage','bogo','bundle','flat_discount','other')",
            name='ck_promotions_type',
        ),
    )

    op.create_table(
        'promotion_items',
        sa.Column('promotion_key', sa.String, nullable=False),
        sa.Column('item_key', sa.String, nullable=False),
        sa.Column('promotion_price', sa.Integer, nullable=True),
        sa.PrimaryKeyConstraint('promotion_key', 'item_key'),
        sa.ForeignKeyConstraint(['promotion_key'], ['promotions.key'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_key'], ['catalog_items.key'], ondelete='CASCADE'),
    )

    op.create_index('idx_promotion_items_promo', 'promotion_items', ['promotion_key'])
    op.create_index('idx_promotion_items_item', 'promotion_items', ['item_key'])

    op.create_table(
        'agent_capabilities',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('agent_id', sa.Integer, nullable=False),
        sa.Column('capability_name', sa.String, nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('TRUE')),
        sa.Column('config_json', JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_id', 'capability_name', name='uq_agent_capabilities'),
    )

    op.create_index('idx_agent_capabilities_agent', 'agent_capabilities', ['agent_id'])
    op.create_index('idx_agent_capabilities_active', 'agent_capabilities', ['agent_id', 'is_active'])

    op.create_table(
        'appointments',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('phone', sa.String, nullable=False),
        sa.Column('date', sa.String, nullable=False),
        sa.Column('time', sa.String, nullable=False),
        sa.Column('service_key', sa.String, nullable=False, server_default=''),
        sa.Column('status', sa.String, nullable=False, server_default='confirmed'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['phone'], ['conversations.phone']),
    )

    op.create_index('idx_appointments_phone', 'appointments', ['phone'])
    op.create_index('idx_appointments_date', 'appointments', ['date'])

    op.create_table(
        'memberships',
        sa.Column('phone', sa.String, primary_key=True),
        sa.Column('plan_key', sa.String, nullable=False),
        sa.Column('status', sa.String, nullable=False, server_default='active'),
        sa.Column('started_at', sa.String, nullable=False),
        sa.Column('next_billing', sa.String, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['phone'], ['conversations.phone']),
    )

    op.create_table(
        'plans',
        sa.Column('key', sa.String, primary_key=True),
        sa.Column('name', sa.String, nullable=False),
        sa.Column('price', sa.Integer, nullable=False),
        sa.Column('billing_cycle', sa.String, nullable=False, server_default='monthly'),
        sa.Column('features', JSONB, nullable=False, server_default='[]'),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
    )

    op.create_table(
        'leads',
        sa.Column('phone', sa.String, primary_key=True),
        sa.Column('stage', sa.String, nullable=False, server_default='interesado'),
        sa.Column('data_json', JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['phone'], ['conversations.phone']),
    )

    op.create_table(
        'agent_templates',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String, nullable=False, unique=True),
        sa.Column('description', sa.String, nullable=False),
        sa.Column('system_prompt_template', sa.String, nullable=False),
        sa.Column('capabilities', JSONB, nullable=False, server_default='[]'),
        sa.Column('fallback_responses', JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
    )

    op.create_table(
        'inference_traces',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('phone', sa.String, nullable=False),
        sa.Column('correlation_id', sa.String, nullable=False),
        sa.Column('agent_id', sa.Integer, nullable=True),
        sa.Column('request_messages', JSONB, nullable=False),
        sa.Column('response_raw', JSONB, nullable=True),
        sa.Column('response_source', sa.String, nullable=False),
        sa.Column('error_type', sa.String, nullable=True),
        sa.Column('error_message', sa.String, nullable=True),
        sa.Column('token_usage_prompt', sa.Integer, nullable=False, server_default='0'),
        sa.Column('token_usage_completion', sa.Integer, nullable=False, server_default='0'),
        sa.Column('latency_ms', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
    )

    op.create_index('idx_traces_phone', 'inference_traces', ['phone', sa.text('created_at DESC')])
    op.create_index('idx_traces_correlation', 'inference_traces', ['correlation_id'])

    op.create_table(
        'turns',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('phone', sa.String, nullable=False),
        sa.Column('user_text', sa.String, nullable=False),
        sa.Column('assistant_text', sa.String, nullable=False),
        sa.Column('user_correlation_id', sa.String, nullable=True),
        sa.Column('assistant_correlation_id', sa.String, nullable=True),
        sa.Column('message_ids', JSONB, nullable=False, server_default='[]'),
        sa.Column('session_id', sa.String, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.NOW()),
        sa.ForeignKeyConstraint(['phone'], ['conversations.phone']),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id']),
    )

    op.create_index('idx_turns_phone_created', 'turns', ['phone', sa.text('created_at DESC')])
    op.create_index('idx_turns_session', 'turns', ['session_id'])


def downgrade() -> None:
    op.drop_table('turns')
    op.drop_table('inference_traces')
    op.drop_table('agent_templates')
    op.drop_table('leads')
    op.drop_table('plans')
    op.drop_table('memberships')
    op.drop_table('appointments')
    op.drop_table('agent_capabilities')
    op.drop_table('promotion_items')
    op.drop_table('promotions')
    op.drop_table('catalog_options')
    op.drop_table('catalog_item_variants')
    op.drop_table('catalog_items')
    op.drop_table('carts')
    op.drop_table('conversation_memory')
    op.drop_table('agent_decisions')
    op.drop_table('escalation_events')
    op.drop_table('messages')
    op.drop_table('sessions')
    op.execute("DROP TABLE IF EXISTS conversations")
    op.drop_table('agents')
    op.drop_table('schema_migrations')
