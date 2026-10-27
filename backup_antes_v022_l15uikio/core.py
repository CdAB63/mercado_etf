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
    data = validate_bars(df)
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
            cur.executemany(sql, rows)
    return len(rows)


def load(asset, interval, source):
    # Cursor DB-API explícito evita a advertência de read_sql com conexão psycopg.
    with connection() as con:
        with con.cursor() as cur:
            cur.execute('''SELECT observed_at, received_at, open, high, low, close, volume,
                adjusted_close, dividends, stock_splits, is_final, price_basis
                FROM bars WHERE asset_id=%s AND interval=%s AND source=%s ORDER BY observed_at''',
                (asset, interval, source))
            return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def sources(asset, interval):
    with connection() as con:
        return [r[0] for r in con.execute('SELECT DISTINCT source FROM bars WHERE asset_id=%s AND interval=%s ORDER BY source', (asset, interval))]
