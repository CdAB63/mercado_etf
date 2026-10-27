import os
from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from core import config, init_db, fetch, save, load, sources, diagnostics

st.set_page_config(page_title='Mercado em perspectiva',layout='wide')
st.title('Mercado em perspectiva')
st.caption('Análise experimental de ETFs e câmbio • Nenhuma ordem é executada')
try:
    cfg=config(); init_db()
except Exception as e:
    st.error('Não foi possível abrir o banco ou a configuração: '+str(e)); st.stop()
assets={a['id']:a for a in cfg['assets']}
asset_id=st.sidebar.selectbox('Ativo',list(assets)); asset=assets[asset_id]
interval=st.sidebar.selectbox('Intervalo',['1day','1min','5min','1h'])
st.sidebar.caption('Dados intradiários dependem da cobertura e do atraso de cada provedor.')
st.sidebar.caption('Coleta exclusiva pelo Twelve Data. B3/BVMF são tratados como mic_code=BVMF.')
if st.sidebar.button('Diagnosticar ativo no Twelve Data'):
    try:
        from twelvedata_client import diagnose
        with st.spinner('Consultando catálogo e uma barra diária...'):
            report = diagnose(asset, cfg['provider'])
        st.json(report)
        st.caption('Até duas chamadas, sem gravar preços. access informa o plano do catálogo; a consulta diária verifica o acesso efetivo da sua chave. O diagnóstico usa 1day independentemente do intervalo selecionado.')
    except Exception as e:
        st.error('Diagnóstico falhou: '+str(e))
if st.sidebar.button('Buscar dados do provedor'):
    try:
        df=fetch(asset, interval)
        n=save(df,asset_id,interval,'twelvedata')
        st.sidebar.success(f'{n} registros recebidos.'); st.rerun()
    except Exception as e: st.sidebar.error('Coleta falhou: '+str(e))
with st.sidebar.expander('Importar CSV'):
    file=st.file_uploader('CSV com horário e OHLC',type=['csv'])
    source=st.text_input('Nome da fonte','csv')
    if st.button('Importar') and file:
        try:
            if not source.strip(): raise ValueError('Informe o nome da fonte.')
            df=pd.read_csv(file); n=save(df,asset_id,interval,source.strip()); st.success(f'{n} linhas importadas.'); st.rerun()
        except Exception as e: st.error(str(e))
try: available=sources(asset_id,interval)
except Exception as e: st.error(str(e)); st.stop()
if not available:
    st.info('Ainda não há dados para este ativo e intervalo. Busque dados ou importe um CSV.'); st.stop()
source=st.sidebar.selectbox('Fonte',available)
df=load(asset_id,interval,source)
df=diagnostics(df)
last=df.iloc[-1]; observed=pd.Timestamp(last.observed_at)
cols=st.columns(4)
cols[0].metric('Último fechamento',f"{last.close:,.4f}")
cols[1].metric('Última variação',f"{last['return']*100:+.2f}%" if pd.notna(last['return']) else '—')
cols[2].metric('Volatilidade / 20 barras',f"{last.vol20*100:.2f}%" if pd.notna(last.vol20) else '—')
cols[3].metric('Desvio robusto',f"{last.robust_z:+.2f}" if pd.notna(last.robust_z) else '—')
st.caption(f"Fonte: {source} | Data da barra: {observed} | Recebida: {last.received_at} | Intervalo: {interval}")
if source=='brapi': st.warning('BRAPI: OHLC diário pode vir ajustado; confirme sua metodologia. Dados podem ter atraso e não representam necessariamente preços negociáveis.')
if interval=='1day': st.caption('A data da barra diária representa a sessão, não o horário da última negociação. A hora de recebimento não prova que a cotação seja atual.')
if pd.notna(last.robust_z) and abs(last.robust_z)>=3: st.warning('Movimento incomum na última barra pelo critério estatístico. Verifique a cotação e os eventos do ativo.')
fig=go.Figure(go.Scatter(x=df.observed_at,y=df.close,name='Fechamento'))
fig.update_layout(height=420,margin=dict(l=10,r=10,t=10,b=10),yaxis_title=asset['currency'])
st.plotly_chart(fig,use_container_width=True)
st.subheader('Análise não supervisionada')
if interval!='1day': st.info('O modelo experimental usa apenas barras diárias.')
elif st.button('Treinar autoencoder e avaliar por tempo'):
    try:
        from model import analyze
        with st.spinner('Treinando e avaliando...'): result=analyze(df)
        st.write(result)
        st.caption('Erro de reconstrução acima do percentil 99 do treino sugere padrão incomum. Não é probabilidade nem sinal de compra ou venda. Avaliação cronológica única; nenhuma estratégia foi validada.')
    except Exception as e: st.error(str(e))
with st.expander('Últimas observações'):
    st.dataframe(df.tail(100).sort_values('observed_at',ascending=False),use_container_width=True)
