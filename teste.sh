python - <<'PY'
import yfinance as yf

for simbolo in ("BOVA11.SA", "IVVB11.SA"):
    print(f"\n--- {simbolo} ---")
    try:
        dados = yf.Ticker(simbolo).history(
            period="2y",
            interval="1d",
            auto_adjust=False,
            actions=True,
        )
        if dados.empty:
            print("Nenhum dado recebido.")
            continue
        print(f"Registros: {len(dados)}")
        print(f"Período: {dados.index.min()} até {dados.index.max()}")
        print(dados[["Open", "High", "Low", "Close", "Volume"]].tail(3))
    except Exception as erro:
        print(f"Falha: {erro}")
PY
