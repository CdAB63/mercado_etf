"""Cliente Twelve Data e diagnóstico sem dependência do banco.

exchange é nome; mic_code é o identificador ISO da bolsa.
Não faz troca automática de provedor ou de instrumento.
"""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, quote_plus
from urllib.request import Request, urlopen


class TwelveDataError(RuntimeError):
    pass


def redact(value, key):
    text = str(value)
    if key:
        for variant in (key, quote(key, safe=''), quote_plus(key)):
            text = text.replace(variant, '[CHAVE OCULTA]')
    text = re.sub(r'(?i)(apikey\s*[=:]\s*)[^&\s"\'<>]+', r'\1[CHAVE OCULTA]', text)
    # Não reproduzir URLs que possam conter outros dados privados.
    return re.sub(r'https?://[^\s<>"\']+', '[URL OCULTA]', text)[:1500]


def api_key(provider):
    name = provider.get('api_key_env', 'TWELVE_DATA_API_KEY')
    key = os.environ.get(name, '').strip()
    if not key:
        raise TwelveDataError('Defina a variável de ambiente ' + name + '.')
    return key


def instrument_params(asset):
    symbol = str(asset.get('symbol', '')).strip()
    if not symbol:
        raise TwelveDataError('Ativo sem symbol no config.json.')
    result = {'symbol': symbol}
    exchange = str(asset.get('exchange') or '').strip()
    mic = str(asset.get('mic_code') or '').strip().upper()
    # Compatibilidade com as configurações B3/BVMF fornecidas nas versões anteriores.
    if exchange.upper() in {'B3', 'BVMF'}:
        if mic and mic != 'BVMF':
            raise TwelveDataError('Configuração conflitante: bolsa brasileira com MIC diferente de BVMF.')
        mic = 'BVMF'
        exchange = ''
    if mic:
        if not re.fullmatch('[A-Z0-9]{4}', mic):
            raise TwelveDataError('mic_code deve conter quatro letras/dígitos.')
        result['mic_code'] = mic
    elif exchange:
        result['exchange'] = exchange
    return result


def request_json(endpoint, params, key):
    if endpoint not in {'time_series', 'symbol_search'}:
        raise TwelveDataError('Endpoint não permitido neste cliente.')
    query = dict(params, apikey=key)
    request = Request('https://api.twelvedata.com/' + endpoint + '?' + urlencode(query),
                      headers={'Accept': 'application/json', 'User-Agent': 'MercadoETF/0.1.2'})
    try:
        with urlopen(request, timeout=30) as response:
            status = response.status
            raw = response.read(4_000_001)
    except HTTPError as exc:
        status = exc.code
        try:
            raw = exc.read(4_000_001)
        finally:
            exc.close()
    except (URLError, OSError, TimeoutError):
        raise TwelveDataError('Falha de conexão/timeout ao consultar Twelve Data.') from None
    if len(raw) > 4_000_000:
        raise TwelveDataError('Resposta do provedor excedeu o tamanho permitido.')
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise TwelveDataError(f'Twelve Data HTTP {status}: resposta não é JSON.') from None
    if not isinstance(payload, dict):
        raise TwelveDataError(f'Twelve Data HTTP {status}: formato de resposta inesperado.')
    if status >= 400 or payload.get('status') == 'error':
        code = payload.get('code', status)
        message = redact(payload.get('message', 'Sem explicação adicional.'), key)
        raise TwelveDataError(f'Twelve Data HTTP {status}, código {redact(code, key)}: {message}')
    return payload


def time_series(asset, provider, interval='1day', outputsize=500):
    key = api_key(provider)
    params = instrument_params(asset)
    params.update(interval=interval, outputsize=outputsize,
                  timezone=provider.get('timezone', 'UTC'))
    data = request_json('time_series', params, key)
    values = data.get('values')
    if not isinstance(values, list) or not values:
        raise TwelveDataError('Twelve Data: resposta sem barras de preços.')
    meta = data.get('meta')
    if not isinstance(meta, dict):
        raise TwelveDataError('Twelve Data: resposta sem identificação do instrumento (meta).')
    if str(meta.get('symbol', '')).upper() != params['symbol'].upper():
        raise TwelveDataError('Símbolo retornado difere do solicitado. Dados não serão gravados.')
    # FX pode trazer currency_base/currency_quote por extenso, sem currency ISO.
    # O par integral validado acima identifica a base e a moeda de cotação.
    is_fx = asset.get('kind') == 'FX' or '/' in params['symbol']
    if not is_fx and asset.get('currency') and str(meta.get('currency', '')).upper() != asset['currency'].upper():
        raise TwelveDataError('Moeda retornada difere da configurada. Dados não serão gravados.')
    if params.get('mic_code') and str(meta.get('mic_code', '')).upper() != params['mic_code']:
        raise TwelveDataError('MIC retornado ausente ou diferente do solicitado. Dados não serão gravados.')
    if meta.get('interval') != interval:
        raise TwelveDataError('Intervalo retornado difere do solicitado. Dados não serão gravados.')
    return data


def diagnose(asset, provider):
    """Até duas chamadas por ativo: catálogo e uma barra diária, sem gravar dados."""
    key = api_key(provider)
    params = instrument_params(asset)
    report = {'ativo': asset.get('id', asset['symbol']), 'filtro_enviado': params}
    try:
        catalog = request_json('symbol_search', {
            'symbol': params['symbol'], 'show_plan': 'true', 'outputsize': 30
        }, key)
        items = catalog.get('data', [])
        if not isinstance(items, list):
            raise TwelveDataError('Catálogo retornou formato inesperado.')
        fields = ('symbol', 'instrument_name', 'exchange', 'mic_code', 'country',
                  'currency', 'instrument_type', 'access')
        matches = [item for item in items if isinstance(item, dict)
                   and str(item.get('symbol', '')).upper() == params['symbol'].upper()]
        report['catalogo_correspondencias_exatas'] = [
            {field: item[field] for field in fields if field in item} for item in matches]
        if not matches:
            report['observacao_catalogo'] = ('Nenhuma correspondência exata entre os resultados; '
                'isso, isoladamente, não prova ausência de cobertura.')
    except TwelveDataError as exc:
        report['erro_catalogo'] = str(exc)
    try:
        data = time_series(asset, provider, '1day', 1)
        report['consulta_diaria'] = {'resultado': 'OK', 'meta': data['meta'],
                                     'data_ultima_barra': data['values'][0].get('datetime')}
    except TwelveDataError as exc:
        report['consulta_diaria'] = {'resultado': 'FALHOU', 'erro': str(exc)}
    # Defesa adicional contra eventual eco de credencial em qualquer campo do servidor.
    return json.loads(redact_json(report, key))


def redact_json(value, key):
    def walk(item):
        if isinstance(item, str):
            return redact(item, key)
        if isinstance(item, dict):
            return {redact(k, key): walk(v) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        return item
    return json.dumps(walk(value), ensure_ascii=False)
