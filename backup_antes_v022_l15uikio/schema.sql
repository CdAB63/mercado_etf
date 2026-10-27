CREATE TABLE IF NOT EXISTS bars (
  asset_id text NOT NULL,
  observed_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  interval text NOT NULL,
  open double precision NOT NULL CHECK (open > 0),
  high double precision NOT NULL CHECK (high > 0),
  low double precision NOT NULL CHECK (low > 0),
  close double precision NOT NULL CHECK (close > 0),
  volume double precision CHECK (volume IS NULL OR volume >= 0),
  source text NOT NULL,
  PRIMARY KEY (asset_id, interval, observed_at, source),
  CHECK (high >= greatest(open, close, low) AND low <= least(open, close, high))
);
CREATE INDEX IF NOT EXISTS bars_latest ON bars (asset_id, interval, observed_at DESC);

-- Migração aditiva 0.2. Linhas anteriores permanecem sem is_final até nova coleta.
ALTER TABLE bars ADD COLUMN IF NOT EXISTS adjusted_close double precision;
ALTER TABLE bars ADD COLUMN IF NOT EXISTS dividends double precision;
ALTER TABLE bars ADD COLUMN IF NOT EXISTS stock_splits double precision;
ALTER TABLE bars ADD COLUMN IF NOT EXISTS is_final boolean;
ALTER TABLE bars ADD COLUMN IF NOT EXISTS price_basis text;
