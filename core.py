import json
import os
from pathlib import Path
import pandas as pd
import numpy as np
from market_data import validate_bars, diagnostics

BASE = Path(__file__).resolve().parent


def config():
    path = Path(os.environ.get('MERCADO_CONFIG', str(BASE / 'config.json')))
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def connection():
    import psycopg
    options = config()['database'].copy()
    name = options.pop('password_env', 'MERCADO_DB_PASSWORD')
    password = os.environ.get(name)
    if password:
        options['password'] = password
    # Se a variável não existir, libpq ainda pode utilizar ~/.pgpass.
    options.setdefault('connect_timeout', 10)
    return psycopg.connect(**options)


def init_db():
    with connection() as con:
        con.execute((BASE / 'schema.sql').read_text(encoding='utf-8'))


def fetch(asset, interval='1day', outputsize=500):
    from collectors import fetch_market
    return fetch_market(asset, config()['provider'], interval, outputsize)


def save(df, asset, interval, source):
    if not source or not source.strip():
        raise ValueError('Informe a fonte.')
    basis = df.attrs.get('price_basis', 'imported_unknown')
    rejected = df.attrs.get('quality_rejections', [])
    data = df.copy() if df.empty and rejected else validate_bars(df)
    rejection_rows = []
    for item in rejected:
        observed = pd.Timestamp(item['observed_at'])
        received = pd.Timestamp(item['received_at'])
        if pd.isna(observed) or pd.isna(received) or observed.tzinfo is None or received.tzinfo is None:
            raise ValueError('Rejeição sem data/fuso válido.')
        if not isinstance(item['reason'], str) or not item['reason'].strip():
            raise ValueError('Rejeição sem motivo.')
        if observed in pd.to_datetime(data['observed_at'], utc=True).tolist():
            raise ValueError('Uma barra não pode ser válida e rejeitada na mesma coleta.')
        rejection_rows.append((asset, interval, observed.to_pydatetime(), source.strip(),
            received.to_pydatetime(), item['reason'], json.dumps(item['raw_bar'], allow_nan=False)))
    def nullable(value):
        return None if pd.isna(value) else float(value)
    rows = []
    for _, row in data.iterrows():
        final = row.get('is_final')
        if pd.isna(final):
            final = None
        elif not isinstance(final, (bool, np.bool_)):
            raise ValueError('is_final inválido.')
        else:
            final = bool(final)
        received = row.get('received_at')
        if pd.isna(received):
            received = pd.Timestamp.now(tz='UTC')
        else:
            received = pd.Timestamp(received)
            if received.tzinfo is None:
                raise ValueError('received_at deve ter fuso.')
        rows.append((asset, row.observed_at.to_pydatetime(), interval,
            *[float(row[c]) for c in ('open','high','low','close')],
            nullable(row.volume), source.strip(), nullable(row.adjusted_close),
            nullable(row.dividends), nullable(row.stock_splits), final, basis, received.to_pydatetime()))
    sql = '''INSERT INTO bars
        (asset_id, observed_at, interval, open, high, low, close, volume, source,
         adjusted_close, dividends, stock_splits, is_final, price_basis, received_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (asset_id, interval, observed_at, source) DO UPDATE SET
          open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,
          volume=EXCLUDED.volume, adjusted_close=EXCLUDED.adjusted_close,
          dividends=EXCLUDED.dividends, stock_splits=EXCLUDED.stock_splits,
          is_final=EXCLUDED.is_final, price_basis=EXCLUDED.price_basis, received_at=EXCLUDED.received_at'''
    with connection() as con:
        with con.cursor() as cur:
            if rows:
                cur.executemany(sql, rows)
                # Só uma barra válida recebida novamente resolve a sua rejeição.
                # Datas ausentes desta coleta permanecem pendentes.
                cur.executemany('''UPDATE bar_rejections SET resolved_at=%s
                    WHERE asset_id=%s AND interval=%s AND observed_at=%s AND source=%s
                      AND received_at <= %s''',
                    [(r[14], asset, interval, r[1], source.strip(), r[14]) for r in rows])
            if rejection_rows:
                cur.executemany('''INSERT INTO bar_rejections
                    (asset_id, interval, observed_at, source, received_at, reason, raw_bar)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (asset_id, interval, observed_at, source) DO UPDATE SET
                      received_at=EXCLUDED.received_at, reason=EXCLUDED.reason,
                      raw_bar=EXCLUDED.raw_bar, resolved_at=NULL
                    WHERE bar_rejections.received_at <= EXCLUDED.received_at''', rejection_rows)
    return len(rows)


def load(asset, interval, source):
    # Cursor DB-API explícito evita a advertência de read_sql com conexão psycopg.
    with connection() as con:
        with con.cursor() as cur:
            cur.execute('''WITH rejected AS (
                SELECT observed_at, received_at, reason, raw_bar FROM bar_rejections
                WHERE asset_id=%s AND interval=%s AND source=%s AND resolved_at IS NULL
                )
                SELECT b.observed_at, b.received_at, b.open, b.high, b.low, b.close, b.volume,
                    b.adjusted_close, b.dividends, b.stock_splits, b.is_final, b.price_basis,
                    NULL::text AS quality_error, NULL::jsonb AS quality_raw
                FROM bars b WHERE b.asset_id=%s AND b.interval=%s AND b.source=%s
                    AND NOT EXISTS (SELECT 1 FROM rejected q WHERE q.observed_at=b.observed_at)
                UNION ALL
                SELECT observed_at, received_at, NULL, NULL, NULL, NULL, NULL,
                    NULL, NULL, NULL, FALSE, NULL, reason, raw_bar FROM rejected
                ORDER BY observed_at''',
                (asset, interval, source, asset, interval, source))
            return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def sources(asset, interval):
    with connection() as con:
        return [r[0] for r in con.execute('''SELECT source FROM bars WHERE asset_id=%s AND interval=%s
            UNION SELECT source FROM bar_rejections
            WHERE asset_id=%s AND interval=%s AND resolved_at IS NULL ORDER BY source''',
            (asset, interval, asset, interval))]
