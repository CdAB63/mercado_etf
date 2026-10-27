import json, os
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import psycopg

CONFIG = os.environ.get('MERCADO_CONFIG', 'config.json')
def config():
    with open(CONFIG, encoding='utf-8') as f: return json.load(f)
def connection():
    d = config()['database'].copy(); password_env = d.pop('password_env')
    d['password'] = os.environ.get(password_env, '')
    return psycopg.connect(**d)
def init_db():
    with connection() as con:
        with open(os.path.join(os.path.dirname(__file__), 'schema.sql'), encoding='utf-8') as f: con.execute(f.read())
def fetch(asset, interval='1day', outputsize=500):
    from twelvedata_client import time_series, TwelveDataError
    cfg = config()['provider']
    payload = time_series(asset, cfg, interval, outputsize)
    df = pd.DataFrame(payload['values']).rename(columns={'datetime': 'observed_at'})
    required = {'observed_at', 'open', 'high', 'low', 'close'}
    if not required.issubset(df.columns):
        raise TwelveDataError('Twelve Data: barras sem data ou OHLC completo.')
    # Diários usam a data de sessão; intradiários usam o fuso solicitado.
    tz = asset['timezone'] if interval == '1day' else cfg.get('timezone', 'UTC')
    if tz == 'Exchange':
        tz = payload['meta'].get('exchange_timezone') or asset['timezone']
    timestamps = pd.to_datetime(df['observed_at'], errors='raise')
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(ZoneInfo(tz))
    else:
        timestamps = timestamps.dt.tz_convert(ZoneInfo(tz))
    df['observed_at'] = timestamps
    for col in ('open', 'high', 'low', 'close', 'volume'):
        if col in df: df[col] = pd.to_numeric(df[col], errors='raise')
    return df.sort_values('observed_at').reset_index(drop=True)

def save(df, asset, interval, source):
    required = ['observed_at','open','high','low','close']
    missing = set(required)-set(df.columns)
    if missing: raise ValueError('Colunas ausentes: '+', '.join(sorted(missing)))
    rows=[]
    for _, row in df.iterrows():
        t = pd.Timestamp(row['observed_at'])
        if pd.isna(t) or t.tzinfo is None: raise ValueError('Datas devem conter fuso horário explícito.')
        vals = [float(row[x]) for x in ['open','high','low','close']]
        if not all(np.isfinite(vals)) or min(vals)<=0 or vals[1]<max(vals) or vals[2]>min(vals): raise ValueError('OHLC inválido: '+str(t))
        v = row.get('volume'); v = None if pd.isna(v) or v == '' else float(v)
        if v is not None and (not np.isfinite(v) or v < 0): raise ValueError('Volume inválido')
        rows.append((asset, t.to_pydatetime(), interval, *vals, v, source))
    with connection() as con:
        with con.cursor() as cur:
            cur.executemany('''INSERT INTO bars(asset_id,observed_at,interval,open,high,low,close,volume,source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (asset_id,interval,observed_at,source)
                DO UPDATE SET open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,volume=EXCLUDED.volume,received_at=now()''',rows)
    return len(rows)

def load(asset, interval, source):
    with connection() as con:
        return pd.read_sql_query('SELECT observed_at, received_at, open, high, low, close, volume FROM bars WHERE asset_id=%s AND interval=%s AND source=%s ORDER BY observed_at',con,params=(asset,interval,source))
def sources(asset, interval):
    with connection() as con:
        return [r[0] for r in con.execute('SELECT DISTINCT source FROM bars WHERE asset_id=%s AND interval=%s ORDER BY source',(asset,interval))]

def diagnostics(df):
    df=df.copy(); df['return']=df.close.pct_change(); df['vol20']=df['return'].rolling(20).std()
    # Desvio usa somente a distribuição anterior, nunca a observação atual.
    ref=df['return'].shift(1); median=ref.rolling(60,min_periods=30).median()
    mad=ref.rolling(60,min_periods=30).apply(lambda x: np.median(np.abs(x-np.median(x))),raw=True)
    df['robust_z']=(df['return']-median)/(1.4826*mad.replace(0,np.nan))
    return df
