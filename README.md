# Mercado em perspectiva — protótipo 0.1

Aplicação local de pesquisa para acompanhar BOVA11, IVVB11, SPY, QQQ, USD/BRL e EUR/BRL. Coleta manual de OHLC do Twelve Data, importação CSV, armazenamento PostgreSQL, gráficos, alerta por retorno anormal e autoencoder experimental em PyTorch com seleção automática CPU/CUDA.

## Estado e limites

Este protótipo NÃO implementa recomendações de compra e venda, cenários probabilísticos, agrupamento de regimes, carteira, simulação, notícias ou coleta automática; são etapas futuras. O modelo é demonstrativo e não está validado como estratégia. Os preços nunca são enviados a corretoras e a aplicação não executa operações. A coleta da B3, os símbolos, cobertura, histórico e intervalos disponíveis dependem do plano do provedor e precisam ser verificados. Uma assinatura/chave gratuita não garante dados em tempo real. O sistema não tem calendário de pregões ou verificação automática de atraso; confira data da observação e fonte antes de usar. Dados intradiários podem ser parciais; o sistema não garante que a barra mais recente esteja fechada. Não usar para decisões financeiras sem confirmação independente.

Preços brutos não incluem automaticamente dividendos, desdobramentos ou ajuste por proventos. Consulte as regras do fornecedor e obtenha uma série ajustada confiável antes de análises de retornos ou treinamento. A troca de fontes pode produzir séries incompatíveis: selecione uma fonte por vez. Falhas de coleta não são preenchidas automaticamente. O autoencoder usa janelas de 20 retornos do mesmo ativo, treinamento cronológico de 75%, separação na fronteira para impedir sobreposição de janelas e teste posterior. O limiar é um percentil das perdas do treino, não uma probabilidade; não há validação walk-forward, análise de estabilidade ou comparação com estratégia passiva. CUDA é opcional.

## Instalação Linux

Requisitos: Python 3.10+ (3.11 recomendado), PostgreSQL 14+ ou Docker Compose, conta/API key Twelve Data. No terminal, a partir da pasta extraída:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Para instalar PyTorch com suporte à sua versão de CUDA, siga o seletor de instalação oficial do PyTorch e verifique `python -c 'import torch; print(torch.cuda.is_available())'`. Se já possuir uma instalação CUDA adequada, mantenha-a ao instalar os demais pacotes.

Defina uma senha forte no terminal (o comando read não a imprime):

```bash
read -rsp 'Senha PostgreSQL: ' MERCADO_DB_PASSWORD; export MERCADO_DB_PASSWORD; echo
read -rsp 'Chave Twelve Data: ' TWELVE_DATA_API_KEY; export TWELVE_DATA_API_KEY; echo
```

Escolha UMA das opções:

1. Banco em contêiner: `docker compose up -d`. O contêiner cria usuário e banco `mercado` na porta local 5432. Se essa porta estiver ocupada, altere `compose.yaml` e `database.port` no `config.json`. Uma senha alterada depois da primeira inicialização não modifica um banco já criado.
2. Banco PostgreSQL existente: crie previamente banco e usuário com permissão CREATE no schema padrão. Ajuste `database` em `config.json`. A senha vem da variável `MERCADO_DB_PASSWORD`. A aplicação cria a tabela automaticamente; não instala extensões nem altera bancos existentes além da sua tabela `bars`.

Execute `streamlit run app.py --server.address 127.0.0.1`. Abra o endereço mostrado no terminal. As variáveis existem somente nessa sessão de terminal. Não publique a interface na rede: este protótipo não possui autenticação nem criptografia.

## Uso

Selecione ativo e intervalo, então clique em Buscar dados do provedor ou importe CSV. A consulta consome créditos da API; não há agendamento. As chamadas, o acesso aos instrumentos B3, os horários e as cotas precisam ser verificados no plano da conta. Falhas são exibidas sem interpretar respostas como preços. O campo exchange pode precisar ser ajustado em config.json conforme o código reconhecido pelo provedor; evite eliminar o identificador de bolsa se isso tornar o símbolo ambíguo. Ativos adicionais podem ser inseridos na lista assets, com id único, symbol, exchange quando aplicável, currency, kind e timezone IANA.

Formato CSV: UTF-8, cabeçalho `observed_at,open,high,low,close,volume`. Horário deve ter fuso explícito, por exemplo `2026-01-02T00:00:00-03:00`; volume pode estar vazio. Para barras diárias, o timestamp representa a data da sessão no fuso do mercado. Se não souber OHLC, não invente valores. Uma importação completa é transacional e repetições da mesma combinação ativo/intervalo/horário/fonte atualizam a linha existente. A importação apenas confirma os valores fornecidos e não identifica desdobramentos.

A coleta Twelve Data usa timezone UTC para intradiário e identifica barras diárias pela data da sessão no fuso configurado para o ativo. Verifique se a convenção do provedor corresponde a cada instrumento antes de comparar sessões e datas. O horário de recebimento representa a importação, não o momento de negociação.

Atualização manual substitui dados da mesma fonte e timestamp, sem guardar versões anteriores; não fornece trilha histórica completa da informação disponível em cada momento. Essa limitação deve ser resolvida antes de simulações financeiras fiéis.
