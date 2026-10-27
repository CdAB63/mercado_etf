# Mercado em perspectiva — versão 0.2.1

Aplicação local de pesquisa em Python/Streamlit/PostgreSQL. Esta versão consolida as correções anteriores e integra Yahoo Finance via yfinance para BOVA11 e IVVB11. Mantém Twelve Data para SPY, QQQ, USD/BRL e EUR/BRL. Não executa ordens, não gera recomendações de compra/venda e não possui estratégia validada. Autoencoder serve apenas à exploração de padrões e anomalias.

## Correção 0.2.1 — metadados Yahoo

A versão 0.2 exigia que history_metadata fosse dict. O yfinance também pode retornar HistoryMetadata, que implementa collections.abc.Mapping. Essa diferença causava a mensagem "Yahoo não forneceu metadados para conferir o instrumento" mesmo com metadados válidos. O coletor agora aceita Mapping (incluindo dict), mantendo obrigatórias as conferências de símbolo e moeda. Apenas esses dois campos são acessados; não convertemos o objeto inteiro em dict, pois outros campos podem carregar dados adicionais da rede. Não há mudança de configuração, dependências ou esquema de banco em relação à 0.2.

Referência do fornecedor: https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py (classe HistoryMetadata).

## Atualizar sua instalação existente

Extraia este pacote em uma pasta diferente da instalação atual e pare o Streamlit. Na pasta extraída que contém atualizar.py:

```bash
python atualizar.py --dest /caminho/da/instalacao/mercado_etf
```

O script verifica o destino e copia somente os arquivos do programa, criando uma pasta `backup_antes_v021_...` com os arquivos anteriores. Mantém seu config.json, banco, ambiente virtual, compose.yaml e senhas. O pacote não contém config.json para evitar sua substituição acidental. Se modificou os arquivos Python, compare suas mudanças com o backup. Em caso de falha de cópia, não inicie a aplicação até concluir a atualização ou restaurar os arquivos do backup.

Entre no diretório da instalação e ative seu ambiente virtual. Como você já instalou yfinance para executar o teste, normalmente não é preciso instalar nada adicional. Caso necessário:

```bash
python -m pip install yfinance
streamlit run app.py --server.address 127.0.0.1
```

As variáveis MERCADO_DB_PASSWORD e TWELVE_DATA_API_KEY continuam necessárias para banco/Twelve Data, no mesmo terminal. Yahoo não requer token adicional. A configuração enviada anteriormente funciona: BOVA11 e IVVB11 passam a usar yfinance por padrão. Se algum desses ativos tiver um provider explícito antigo, ajuste-o para `"provider": "yfinance"`. Se não houver esse campo, nenhuma alteração é necessária.

Na primeira abertura, a aplicação acrescenta cinco colunas em bars: adjusted_close, dividends, stock_splits, is_final e price_basis. Não elimina colunas nem registros. O usuário de banco precisa ser proprietário da tabela ou ter permissão para executar essa migração. Linhas antigas não recebem confirmação artificial de fechamento: refaça a coleta para atualizá-las.

## Nova instalação

Use Python 3.10+ (3.11 recomendado) e PostgreSQL 14+. Copie config.example.json para config.json e ajuste a conexão. Crie banco/usuário ou use compose.yaml:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
read -rsp 'Senha PostgreSQL: ' MERCADO_DB_PASSWORD
export MERCADO_DB_PASSWORD
echo
read -rsp 'Chave Twelve Data: ' TWELVE_DATA_API_KEY
export TWELVE_DATA_API_KEY
echo
docker compose up -d
streamlit run app.py --server.address 127.0.0.1
```

Docker é opcional; não execute o comando docker se usar seu PostgreSQL existente. O contêiner ocupa a porta local 5432; altere a porta e config se necessário. A aplicação usa a senha em variável de ambiente ou, se ela não existir, permite a autenticação padrão da libpq (por exemplo ~/.pgpass). Para CUDA, mantenha uma instalação PyTorch compatível com seu driver. Não é necessário reinstalar PyTorch para atualizar este projeto.

Use apenas localmente ou atrás de uma infraestrutura autenticada: não há autenticação web nesta versão.

## Uso dos dados

Selecione BOVA11, intervalo 1day, e clique em Buscar dados do provedor. A legenda identifica yfinance e BOVA11.SA. Repita para IVVB11. A fonte efetivamente coletada é registrada; históricos de fontes distintas nunca são concatenados automaticamente.

A coleta Yahoo usa 2 anos no diário, 5 dias em barras de 1 minuto e 1 mês nos intervalos 5 minutos/1 hora. Intradiário ainda não foi validado na conta do usuário; a existência de uma opção na interface não garante cobertura nem baixa latência. Não há coleta automática, atualização por timer, SLA ou limite de chamadas formal garantido pelo Yahoo. Não clique repetidamente após rate limit. Dado ausente não é preenchido com valores inventados.

Yahoo recebe auto_adjust=False, back_adjust=False, repair=False, actions=True e keepna=True. Open/High/Low/Close são preservados conforme recebidos; isso não garante que a própria fonte nunca tenha ajustado eventos. Adj Close, dividendos e splits são guardados separadamente quando disponíveis. Não há reparo automático de preços ou eventos. Falhas estruturais, preços inválidos ou datas duplicadas rejeitam o lote inteiro antes da escrita. Metadados do Yahoo são conferidos por símbolo e moeda.

O seletor Série para indicadores e treino permite Close ou Adj Close. Adj Close é a escolha inicial se houver essa coluna na fonte, mas o treino exige que ela esteja completa nas barras selecionadas. Não se preenchem buracos de Adj Close com Close. O gráfico principal mostra Close; a série ajustada pode ser ligada pela legenda. Preços ajustados não são preços de execução.

## Barras provisórias e qualidade

A data diária é a data da sessão no fuso do mercado, não a hora de negociação. Conservadoramente, qualquer barra diária do dia da coleta fica provisória, mesmo depois do encerramento. Só uma nova coleta em outro dia pode atualizar sua classificação. A regra e o momento do recebimento são persistidos: apenas a passagem do tempo não promove um preço parcial antigo a definitivo. is_final indica essa regra local, não certificação do fechamento pelo provedor.

O autoencoder usa apenas diários anteriores ao dia atual, confirmados no recebimento. Registros legados sem confirmação são excluídos na borda histórica; uma lacuna não confirmada entre sessões bloqueia o treino para evitar juntar retornos de vários dias. Lacunas de calendário sem registros não são detectadas nesta versão (ainda não há calendário oficial de pregões). Barras intradiárias são marcadas provisórias até o término do intervalo mais uma margem de um minuto; não são usadas pelo modelo atual.

Variações absolutas de pelo menos 8% por barra são destacadas para conferência. O limite pode ser alterado em analysis.jump_threshold. O limiar é uma heurística de revisão, não um teste de fraude/erro e nem uma regra de compra/venda. Movimentos reais intensos também podem ser sinalizados. Nenhuma observação anormal é corrigida ou descartada automaticamente.

No teste enviado pelo usuário, BOVA11 caiu de 201,69 para 172,42 de 23/10 para 26/10/2026 (aproximadamente -14,51%); IVVB11 passou de 430,00 para 468,54 (aproximadamente +8,96%). Conferir com fonte independente e eventos do ETF antes de interpretar o treinamento. Os valores apresentados não permitem determinar a causa desses movimentos.

## Modelo

Mantém o autoencoder experimental em PyTorch, com GPU quando disponível. Usa janelas de 20 retornos, treino cronológico de 75%, separação de janelas na fronteira e teste posterior. Média/desvio vêm apenas do treino. O mínimo de 251 preços finais é um requisito operacional; 496 registros permitem experimentar, mas não demonstram adequação estatística, previsibilidade ou rentabilidade. O erro de reconstrução não é uma probabilidade financeira; o percentil 99 é calculado no treino, sem calibração independente. Não há persistência do modelo, agrupamento de regimes, walk-forward, backtest, carteira simulada ou notícias.

Históricos ajustados são a visão atual do fornecedor e podem ser revistos. A base faz upsert de cada barra, sem preservar todas as versões anteriores. Portanto não é um arquivo point-in-time adequado para simular o conhecimento passado sem verificações adicionais.

## Adicionar ativos

Mantenha id, symbol, currency, kind e timezone. Configure provider por ativo (yfinance ou twelvedata); para Yahoo use yahoo_symbol exato, por exemplo BOVA11.SA. Apenas BOVA11/IVVB11 recebem o sufixo .SA automaticamente se yahoo_symbol não for informado. Para novos ativos de B3, informe yahoo_symbol e provider explicitamente. Para Twelve Data, exchange identifica o nome da bolsa e mic_code identifica seu MIC; a compatibilidade B3/BVMF da correção anterior foi preservada.

## CSV

Cabeçalho mínimo: observed_at,open,high,low,close. Use fuso explícito, exemplo 2026-10-26T00:00:00-03:00. Volume, adjusted_close, dividends e stock_splits são opcionais. Use uma fonte própria, distinta dos coletores. A importação só marca barras como encerradas se você confirmar que o arquivo foi conferido. Mesmo assim o modelo exclui a data atual. Uma importação não prova o ajuste ou a qualidade da série.

## Testes e evidências

Foram aprovados 37 testes locais, além da compilação de todos os módulos. Execute `python -m unittest discover -s tests -v` na pasta extraída do pacote. Os testes verificam conversão de datas, identificação e moeda, rejeição de OHLC inválido, preservação das séries, roteamento de fontes, finalização conservadora, não preenchimento de ajustes, uso apenas do treino para normalização, escrita parametrizada simulada, backup/config e a correção Twelve Data. Os quatro testes adicionais da 0.2.1 verificam metadados Mapping válidos para ambos os ETFs sem acessar campos tardios, rejeição de símbolo/moeda incorretos, campos ausentes e formatos inválidos. Dependem de pandas e numpy; banco, GPU e provedores são simulados.

O usuário comprovou o download real de 496 registros para cada ETF com yfinance no seu ambiente. A integração nova foi verificada com respostas simuladas e compilação. Não foi executada contra um PostgreSQL real, Streamlit em execução, conta Twelve Data nem GPU neste ambiente.

Fontes: https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html ; https://ranaroussi.github.io/yfinance/advanced/price_repair.html ; https://github.com/ranaroussi/yfinance ; https://twelvedata.com/docs . yfinance é independente do Yahoo e voltado a pesquisa/uso pessoal; consulte os termos da fonte para distribuição de dados.
