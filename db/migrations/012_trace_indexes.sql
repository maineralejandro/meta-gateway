-- 012: Indices for inference_traces query performance
-- These support the /api/debug/traces/recent endpoint (polled every 15s)
-- and the /api/debug/trace/{phone} endpoint

CREATE INDEX IF NOT EXISTS idx_traces_created_at
  ON inference_traces(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_traces_source_created
  ON inference_traces(response_source, created_at DESC);
