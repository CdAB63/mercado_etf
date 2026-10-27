import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from core import config, init_db, fetch, save, load, sources
from market_data import provider_for, yahoo_symbol, diagnostics, training_frame, validate_bars

st.set_page_config(page_title='Mercado em perspectiva', layout='wide')
st.title('Mercado em perspectiva')
st.caption('Versão 0.2.2 • Pesquisa experimental de ETFs e câmbio • Coleta manual')
try:
    cfg = config()
    init_db()
    assets = {a['id']:a for a in cfg['assets']}
except Exception as exc:
    st.error('Não foi possível abrir o banco/configuração: '+str(exc))
    st.stop()

asset_id = st.sidebar.selectbox('Ativo', list(assets))
asset = assets[asset_id]
interval = st.sidebar.selectbox('Intervalo', ['1day','1min','5min','1h'])
try:
    provider = provider_for(asset)
except ValueError as exc:
    st.error(str(exc)); st.stop()
label = yahoo_symbol(asset) if provider == 'yfinance' else asset['symbol']
st.sidebar.caption(f'Coleta: {provider} · {label}')
st.sidebar.caption('Intervalo da barra não é garantia de atualização. Intradiário depende da fonte.')
if provider == 'twelvedata' and st.sidebar.button('Diagnosticar no Twelve Data'):
    from twelvedata_client import diagnose
    try:
        st.json(diagnose(asset, cfg['provider']))
    except Exception as exc:
        st.error(str(exc))

if 'collected' in st.session_state:
    st.success(st.session_state.pop('collected'))
if st.sidebar.button('Buscar dados do provedor'):
    try:
        with st.spinner('Consultando e validando os dados...'):
            frame = fetch(asset, interval)
            count = save(frame, asset_id, interval, frame.attrs['source'])
        provisional = int((~frame['is_final']).sum())
        rejected_count = len(frame.attrs.get('quality_rejections', []))
        st.session_state['collected'] = (f'{count} barras válidas gravadas de {provider}; '
            f'{provisional} provisórias; {rejected_count} barras em quarentena nesta coleta.')
        st.rerun()
    except Exception as exc:
        st.sidebar.error('Coleta falhou: '+str(exc))

with st.sidebar.expander('Importar CSV'):
    file = st.file_uploader('CSV com observed_at, open, high, low, close', type=['csv'])
    import_source = st.text_input('Nome da fonte importada', 'csv')
    confirmed = st.checkbox('O arquivo contém somente barras encerradas, conferidas por mim')
    if st.button('Importar') and file:
        try:
            if import_source.strip() in ('yfinance','twelvedata','brapi'):
                raise ValueError('Use um nome próprio para a fonte CSV, distinto dos coletores.')
            frame = validate_bars(pd.read_csv(file))
            # Uma importação não prova a finalização; exige confirmação explícita de origem.
            frame['is_final'] = bool(confirmed)
            frame.attrs['price_basis'] = 'csv_user_supplied'
            count = save(frame,asset_id,interval,import_source)
            st.session_state['collected'] = f'{count} barras importadas.'
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

try:
    available = sources(asset_id, interval)
except Exception as exc:
    st.error(str(exc)); st.stop()
if not available:
    st.info('Sem dados para este ativo e intervalo. Busque dados ou importe um CSV.')
    st.stop()
source = st.sidebar.selectbox('Fonte do histórico exibido', available,
    index=available.index(provider) if provider in available else 0)
try:
    df = load(asset_id, interval, source)
except Exception as exc:
    st.error(str(exc)); st.stop()
if df.empty:
    st.info('Nenhuma barra disponível.'); st.stop()

quarantine = df[df['quality_error'].notna()]
if not quarantine.empty:
    st.warning(f'{len(quarantine)} barras em quarentena. Os demais preços foram preservados. '
               'Confira abaixo os valores recebidos; o treino fica bloqueado enquanto houver pendências.')
    with st.expander('Barras em quarentena — valores recebidos e motivo', expanded=True):
        for _, item in quarantine.iterrows():
            local_time = pd.Timestamp(item.observed_at).tz_convert(asset['timezone'])
            st.write(f'{asset_id} · {local_time} · {item.quality_error}')
            st.json(item.quality_raw)
    if len(quarantine) == len(df):
        st.info('Nenhuma barra utilizável neste histórico. As rejeições foram registradas para conferência.')
        st.stop()

known_adjusted = df['adjusted_close'].notna().any()
choices = ['close', 'adjusted_close'] if known_adjusted else ['close']
basis = st.selectbox('Série para indicadores e treino', choices,
    index=1 if known_adjusted else 0,
    format_func=lambda c: 'Adj Close — ajustado pelo provedor' if c=='adjusted_close' else 'Close — conforme recebido')
st.caption('O gráfico abaixo mostra Close. O ajuste é guardado separadamente; preços ajustados não são preços de execução.')
analyzed = diagnostics(df, basis, float(cfg.get('analysis',{}).get('jump_threshold',0.08)))
last = analyzed.iloc[-1]
cols = st.columns(4)
cols[0].metric('Último Close', f'{last.close:,.4f}' if pd.notna(last.close) else '—')
cols[1].metric('Variação da série', f"{last['return']*100:+.2f}%" if pd.notna(last['return']) else '—')
cols[2].metric('Volatilidade / 20 barras', f'{last.vol20*100:.2f}%' if pd.notna(last.vol20) else '—')
cols[3].metric('Desvio robusto', f'{last.robust_z:+.2f}' if pd.notna(last.robust_z) else '—')
st.caption(f'Fonte: {source} | Barra: {last.observed_at} | Recebida: {last.received_at} | Moeda: {asset["currency"]}')
unconfirmed = int((~df['is_final'].eq(True) & df['quality_error'].isna()).sum())
if unconfirmed:
    st.info(f'{unconfirmed} barras provisórias ou antigas sem confirmação. Elas não entram no treino; refaça a coleta para atualizá-las.')
if interval == '1day':
    st.caption('Barra diária de hoje permanece provisória, mesmo após o fechamento, até nova consulta em outro dia. A data da barra não é a hora da última negociação.')

fig = go.Figure(go.Scatter(x=df.observed_at, y=df.close, name='Close', connectgaps=False))
if known_adjusted:
    fig.add_trace(go.Scatter(x=df.observed_at,y=df.adjusted_close,name='Adj Close',visible='legendonly',connectgaps=False))
fig.update_layout(height=420,margin=dict(l=10,r=10,t=10,b=10),yaxis_title=asset['currency'])
st.plotly_chart(fig,use_container_width=True)

review = analyzed[analyzed['review_move']]
if not review.empty:
    st.warning(f'{len(review)} variações excedem o limiar de conferência na série selecionada. Podem ser movimentos reais, eventos ou problemas na fonte. Nenhuma foi corrigida ou removida automaticamente.')
    with st.expander('Conferir variações e eventos', expanded=True):
        st.dataframe(review[['observed_at','close','adjusted_close','return','dividends','stock_splits','is_final']].tail(20),use_container_width=True)

st.subheader('Análise não supervisionada')
st.caption('Autoencoder experimental: erro de reconstrução não é probabilidade nem sinal de compra/venda. Quantidade de registros suficiente não demonstra qualidade nem capacidade preditiva.')
if interval != '1day':
    st.info('O modelo desta versão usa somente barras diárias.')
else:
    try:
        ready = training_frame(df, basis, asset['timezone'])
    except ValueError as exc:
        ready = None
        st.info(str(exc))
    if ready is not None:
        st.caption(f'{len(ready)} fechamentos finais disponíveis. Série: {basis}. Confira as variações destacadas antes de interpretar resultados.')
        if st.button('Treinar autoencoder e avaliar por tempo'):
            try:
                from model import analyze
                with st.spinner('Treinando e avaliando...'):
                    result = analyze(ready)
                st.json(result)
            except Exception as exc:
                st.error(str(exc))
with st.expander('Últimas observações'):
    st.dataframe(analyzed.tail(100).sort_values('observed_at',ascending=False),use_container_width=True)
