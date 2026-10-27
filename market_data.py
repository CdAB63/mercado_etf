"""Normalização, qualidade e política de barras, sem dependência do banco/GPU."""
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

OHLC = ['open', 'high', 'low', 'close']
OPTIONAL = ['volume', 'adjusted_close', 'dividends', 'stock_splits']


def provider_for(asset):
    provider = asset.get('provider')
    if provider is None:
        provider = 'yfinance' if asset['id'] in ('BOVA11', 'IVVB11') else 'twelvedata'
    if provider not in ('yfinance', 'twelvedata'):
        raise ValueError('Provedor não suportado para este ativo: '+str(provider))
    return provider


def yahoo_symbol(asset):
    symbol = asset.get('yahoo_symbol')
    if symbol:
        return symbol
    # Converter somente os dois ativos cuja identidade é conhecida neste projeto.
    if asset['id'] in ('BOVA11', 'IVVB11'):
        return asset['id'] + '.SA'
    return asset['symbol']


def normalize_yahoo(history, asset):
    if history is None or history.empty:
        raise ValueError('Yahoo não retornou barras. Consulte novamente mais tarde; nenhum dado foi gravado.')
    if isinstance(history.columns, pd.MultiIndex):
        raise ValueError('Resposta Yahoo inesperada: múltiplos instrumentos/níveis de colunas.')
    if not isinstance(history.index, pd.DatetimeIndex) or history.index.tz is None:
        raise ValueError('Yahoo retornou datas sem fuso; coleta rejeitada para evitar datas incorretas.')
    rename = {'Open':'open', 'High':'high', 'Low':'low', 'Close':'close', 'Volume':'volume',
              'Adj Close':'adjusted_close', 'Dividends':'dividends', 'Stock Splits':'stock_splits'}
    df = history.rename(columns=rename).copy()
    df['observed_at'] = history.index.tz_convert(ZoneInfo(asset['timezone']))
    # Preservar campos retornados; não inventar adjusted_close/eventos ausentes.
    cols = ['observed_at'] + [c for c in OHLC + OPTIONAL if c in df]
    return df[cols].reset_index(drop=True)


def partition_bars(df):
    """Separar barras válidas e rejeições sem corrigir/preencher os preços.

    Datas ambíguas/duplicadas e colunas ausentes rejeitam o lote inteiro.
    O payload da rejeição preserva os valores normalizados recebidos da biblioteca.
    """
    required = {'observed_at', *OHLC}
    if not required.issubset(df.columns):
        raise ValueError('Faltam colunas: '+', '.join(sorted(required - set(df.columns))))
    if df.empty:
        raise ValueError('Nenhuma barra disponível.')
    df = df.copy().reset_index(drop=True)
    times = [pd.Timestamp(t) for t in df['observed_at']]
    if any(pd.isna(t) or t.tzinfo is None for t in times):
        raise ValueError('Cada data deve ter fuso horário explícito.')
    df['observed_at'] = pd.to_datetime(times, utc=True)
    if df['observed_at'].duplicated().any():
        raise ValueError('A resposta contém horários duplicados; lote não gravado.')
    raw = df.copy()
    reasons = [[] for _ in range(len(df))]

    def mark(mask, message):
        for i in np.flatnonzero(np.asarray(mask, dtype=bool)):
            reasons[i].append(message)

    for c in OHLC + OPTIONAL:
        if c not in df:
            df[c] = np.nan
            continue
        numeric = pd.to_numeric(df[c], errors='coerce').astype(float)
        if c in OHLC:
            bad = ~np.isfinite(numeric) | (numeric <= 0)
            message = c+': ausente, não numérico, não finito ou não positivo'
        else:
            # Ausência opcional é permitida; texto inválido/inf/negativos não são.
            bad = df[c].notna() & (~np.isfinite(numeric) | (numeric < 0))
            if c == 'adjusted_close':
                bad |= numeric.eq(0)
            message = c+': valor inválido'
        mark(bad, message)
        df[c] = numeric
    complete = np.isfinite(df[OHLC]).all(axis=1) & df[OHLC].gt(0).all(axis=1)
    mark(complete & df['high'].lt(df[['open','close','low']].max(axis=1)),
         'high: menor que abertura, fechamento ou mínima')
    mark(complete & df['low'].gt(df[['open','close','high']].min(axis=1)),
         'low: maior que abertura, fechamento ou máxima')

    def json_value(value):
        if pd.isna(value):
            return None
        if isinstance(value, (float, np.floating)) and not np.isfinite(value):
            return str(value)
        if isinstance(value, np.generic):
            return value.item()
        return value if isinstance(value, (str, int, float, bool)) else str(value)

    rejected = []
    for i, errors in enumerate(reasons):
        if errors:
            rejected.append({'observed_at': df.loc[i, 'observed_at'].isoformat(),
                'reason': '; '.join(errors),
                'raw_bar': {c: json_value(raw.loc[i, c]) for c in OHLC + OPTIONAL if c in raw}})
    valid = np.array([not r for r in reasons], dtype=bool)
    return df.loc[valid].sort_values('observed_at').reset_index(drop=True), rejected


def validate_bars(df):
    """Validação estrita para escrita de preços e importação CSV."""
    valid, rejected = partition_bars(df)
    if rejected:
        details = ' | '.join(r['observed_at']+': '+r['reason'] for r in rejected[:3])
        raise ValueError('Barra ausente/inválida: '+details+'. Lote não gravado.')
    return valid


def stamp_finality(df, asset, interval, now=None):
    """Política conservadora: diário do dia da coleta fica provisório até nova coleta.

    is_final registra a regra aplicada no recebimento, não uma certificação da bolsa.
    """
    df = df.copy()
    now = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        raise ValueError('now deve ter fuso horário.')
    times = pd.to_datetime(df['observed_at'], utc=True)
    tz = ZoneInfo(asset['timezone'])
    if interval == '1day':
        dates = times.dt.tz_convert(tz).dt.date
        today = now.tz_convert(tz).date()
        if (dates > today).any():
            raise ValueError('Provedor retornou sessão diária futura.')
        df['is_final'] = dates < today
    else:
        delta = {'1min':1, '5min':5, '1h':60}.get(interval)
        if delta is None:
            raise ValueError('Intervalo não suportado: '+interval)
        if (times > now).any():
            raise ValueError('Provedor retornou horário futuro.')
        # Conservador na fronteira, mas não certifica ausência de atraso/revisões.
        df['is_final'] = times + pd.Timedelta(minutes=delta + 1) <= now
    df['received_at'] = now.tz_convert('UTC')
    return df


def diagnostics(df, price_column='close', jump_threshold=0.08):
    df = df.copy()
    price = pd.to_numeric(df[price_column], errors='coerce')
    df['return'] = price.pct_change(fill_method=None)
    df['vol20'] = df['return'].rolling(20).std()
    ref = df['return'].shift(1)
    median = ref.rolling(60, min_periods=30).median()
    mad = ref.rolling(60, min_periods=30).apply(lambda x: np.median(np.abs(x-np.median(x))), raw=True)
    df['robust_z'] = (df['return'] - median) / (1.4826 * mad.replace(0, np.nan))
    df['review_move'] = df['return'].abs() >= jump_threshold
    return df


def training_frame(df, price_column='close', timezone='UTC', now=None):
    """Somente uma série coerente de barras diárias finais; nunca mistura adj/raw."""
    if 'is_final' not in df:
        raise ValueError('Histórico sem classificação de fechamento. Refaça a coleta.')
    if 'quality_error' in df and df['quality_error'].notna().any():
        raise ValueError('Há barras em quarentena. Confira os valores recebidos e refaça a coleta; '
                         'o treino fica bloqueado para não atravessar lacunas conhecidas.')
    ordered = df.sort_values('observed_at').reset_index(drop=True)
    now = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    dates = pd.to_datetime(ordered['observed_at'], utc=True).dt.tz_convert(timezone).dt.date
    mask = ordered['is_final'].eq(True) & (dates < now.tz_convert(timezone).date())
    # Não saltar buracos provisórios internos: isso juntaria retornos de múltiplas sessões.
    accepted = np.flatnonzero(mask.to_numpy())
    if not len(accepted):
        raise ValueError('Não há barras diárias finais. Refaça a coleta após o dia da sessão.')
    if not mask.iloc[accepted[0]:accepted[-1]+1].all():
        raise ValueError('Há barras antigas não confirmadas entre sessões. Refaça a coleta antes de treinar.')
    result = ordered.loc[mask].copy()
    if price_column not in result:
        raise ValueError('Série solicitada não está disponível: '+price_column)
    values = pd.to_numeric(result[price_column], errors='coerce').to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Série de treino tem lacunas/valores inválidos; não será preenchida com outro tipo de preço.')
    if len(values) < 251:
        raise ValueError(f'São necessários 251 fechamentos finais; disponíveis: {len(values)}.')
    result['close'] = values
    return result.reset_index(drop=True)
