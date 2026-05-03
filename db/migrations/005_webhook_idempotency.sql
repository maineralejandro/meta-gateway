-- Migration 005: Webhook idempotency
-- Add UNIQUE index on meta_message_id to prevent duplicate webhook processing

CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_meta_id ON messages(meta_message_id);
