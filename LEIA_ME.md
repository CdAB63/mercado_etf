# Correção Twelve Data — 0.1.2 — 27/10/2026

Esta atualização do protótipo usa exclusivamente Twelve Data. Resolve a confusão de parâmetros: BVMF é MIC; o nome da bolsa mostrado no catálogo BOVA11 é BOVESPA. `exchange=BVMF` não equivale a `mic_code=BVMF`.

## Instalação na aplicação existente

1. Pare o Streamlit (Ctrl+C).
2. Guarde cópias de app.py/core.py se você os modificou.
3. Copie app.py, core.py, twelvedata_client.py e diagnostico_twelve.py deste pacote para a pasta da aplicação existente, substituindo app.py/core.py.
4. Preserve config.json, schema.sql, model.py, requirements.txt, seu banco e ambiente virtual. Este pacote é uma atualização, não a aplicação completa.
5. No terminal onde já definiu MERCADO_DB_PASSWORD e TWELVE_DATA_API_KEY, execute:

```
streamlit run app.py --server.address 127.0.0.1
```

O config.json enviado pelo usuário continua válido: valores antigos exchange=B3 ou exchange=BVMF são convertidos para mic_code=BVMF ao montar a chamada, sem escrever no arquivo. Se quiser explicitar o formato correto, substitua apenas `"exchange": "BVMF"` por `"mic_code": "BVMF"` nos dois ativos brasileiros. `exchange=BOVESPA` também é enviado como nome, se escolhido explicitamente. Quando mic_code existe, ele tem prioridade sobre exchange. A interface nova usa apenas Twelve Data mesmo se uma configuração anterior contiver provider=brapi por ativo. Dados já gravados de outras fontes continuam consultáveis separadamente.

SPY/QQQ e os pares cambiais mantêm seus filtros. Dados novos têm source=twelvedata. Nenhuma tabela, senha, configuração ou dado existente é removido.

## Diagnóstico com sua própria chave

Selecione BOVA11 ou IVVB11 e clique em **Diagnosticar ativo no Twelve Data**. Isso consulta o catálogo com show_plan=true e tenta uma barra diária com o filtro correto. Não grava nada no banco nem altera configurações. A pesquisa mostra correspondências exatas, bolsa, MIC, moeda e access (plano informado pelo catálogo), quando disponíveis. A consulta diária verifica o acesso efetivo da sua chave; a presença no catálogo não prova permissão para obter histórico.

Também pode executar, sem Streamlit/PostgreSQL:

```
python diagnostico_twelve.py --config config.json
```

Por padrão são até quatro chamadas: duas para cada um de BOVA11 e IVVB11. Execute uma vez e examine a resposta, respeitando sua cota. Para um ativo:

```
python diagnostico_twelve.py --config config.json --assets BOVA11
```

Use a chave apenas na variável de ambiente definida em provider.api_key_env. Se não estiver definida:

```
read -rsp 'Chave Twelve Data: ' TWELVE_DATA_API_KEY
export TWELVE_DATA_API_KEY
echo
```

O relatório elimina a chave e URLs retornadas pelo servidor. Ele não imprime a URL autenticada. Se quiser compartilhar o diagnóstico, revise-o e envie apenas a saída, nunca a chave.

## Interpretação

- consulta_diaria.resultado=OK: uma barra diária foi recebida e validada para o ativo. Use Buscar dados para gravar o histórico. Isso não comprova disponibilidade intradiária.
- HTTP/código de erro: a mensagem original sanitizada agora é exibida. Um 404 isolado não determina se a conta exige upgrade.
- O campo access do catálogo informa um nível de acesso; avalie junto com a resposta real da consulta.
- Catálogo sem correspondência: não se conclui automaticamente que o ativo não existe; a busca tem limite de resultados. Consulte o suporte do provedor se necessário.
- Restrição explícita do plano: correções de software não liberam permissões comerciais. A aplicação pode continuar só no Twelve Data com os ativos acessíveis e os demais pendentes. Não há troca por outro ETF, fonte alternativa ou preço estimado.

## Validação e limites

16 testes automatizados locais de parâmetros, HTTP 404/403, JSON, falha de rede, sigilo da chave, diagnóstico e rejeição de instrumento/moeda/MIC/intervalo divergentes. O código também foi compilado. Respostas externas foram simuladas; não se testou a conta do usuário, a disponibilidade de IVVB11, o banco, a interface Streamlit em execução nem CUDA.

Esta correção não acrescenta modelo preditivo, ordens, coleta automática, ajustes de proventos ou controle de barra encerrada. Os limites científicos e operacionais do protótipo permanecem. Para reproduzir os testes locais: `python -m unittest discover -s tests -v` na pasta deste pacote (biblioteca padrão do Python).

## Fontes consultadas

- https://twelvedata.com/docs — time_series: exchange e mic_code são filtros distintos; symbol_search permite show_plan.
- https://twelvedata.com/markets/251529/etf/bovespa/bova11 — BOVA11 listado em BOVESPA, MIC BVMF.

Não há garantia de acesso gratuito aos dois ETFs por haver uma página pública. O teste autenticado da conta é necessário para concluir.
