from collections.abc import Mapping
from zoneinfo import ZoneInfo
import pandas as pd
from market_data import provider_for, yahoo_symbol, normalize_yahoo, validate_bars, partition_bars, stamp_finality


def fetch_yahoo(asset, interval):
    try:
        import yfinance as yf
    except ImportError:
        raise ValueError('Instale yfinance no ambiente ativo: python -m pip install yfinance') from None
    options = {'1day': ('1d', '2y'), '1min': ('1m', '5d'),
               '5min': ('5m', '1mo'), '1h': ('1h', '1mo')}
    if interval not in options:
        raise ValueError('Intervalo não suportado pelo coletor Yahoo.')
    yahoo_interval, period = options[interval]
    symbol = yahoo_symbol(asset)
    ticker = yf.Ticker(symbol)
    # Manter Close e Adj Close separados; não reparar dados automaticamente.
    history = ticker.history(period=period, interval=yahoo_interval, auto_adjust=False,
                             back_adjust=False, actions=True, repair=False, keepna=True,
                             timeout=30)
    df = normalize_yahoo(history, asset)
    meta = ticker.history_metadata
    # yfinance pode retornar HistoryMetadata (Mapping), não apenas dict.
    # Ler só os campos necessários: dict(meta) pode carregar campos remotos.
    if not isinstance(meta, Mapping):
        raise ValueError('Yahoo retornou metadados em formato inválido '
                         f'({type(meta).__name__}); nada será gravado.')
    if str(meta.get('symbol', '')).upper() != symbol.upper():
        raise ValueError('Yahoo retornou outro símbolo ou não o identificou; nada será gravado.')
    if str(meta.get('currency', '')).upper() != asset['currency'].upper():
        raise ValueError('Yahoo retornou moeda diferente/ausente; nada será gravado.')
    return df


def fetch_twelve(asset, provider, interval, outputsize=500):
    from twelvedata_client import time_series
    payload = time_series(asset, provider, interval, outputsize)
    df = pd.DataFrame(payload['values']).rename(columns={'datetime':'observed_at'})
    if 'observed_at' not in df:
        raise ValueError('Twelve Data retornou barras sem data.')
    tz = asset['timezone'] if interval == '1day' else provider.get('timezone', 'UTC')
    if tz == 'Exchange':
        tz = payload['meta'].get('exchange_timezone') or asset['timezone']
    dates = pd.to_datetime(df['observed_at'], errors='raise')
    df['observed_at'] = (dates.dt.tz_localize(ZoneInfo(tz)) if dates.dt.tz is None
                         else dates.dt.tz_convert(ZoneInfo(tz)))
    return df


def fetch_market(asset, provider, interval='1day', outputsize=500, now=None):
    source = provider_for(asset)
    df = fetch_yahoo(asset, interval) if source == 'yfinance' else fetch_twelve(asset, provider, interval, outputsize)
    now = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    if source == 'yfinance':
        valid, rejected = partition_bars(df)
        # Validar datas futuras também nas linhas que vão para quarentena.
        stamp_finality(df, asset, interval, now=now)
        df = stamp_finality(valid, asset, interval, now=now)
        received = now.tz_convert('UTC')
        for item in rejected:
            item['received_at'] = received.isoformat()
        df.attrs['quality_rejections'] = rejected
    else:
        df = stamp_finality(validate_bars(df), asset, interval, now=now)
    df.attrs['source'] = source
    df.attrs['price_basis'] = 'yahoo_auto_adjust_false_repair_false' if source == 'yfinance' else 'twelvedata_as_received'
    return df
