"""Autoencoder experimental; não é uma estratégia financeira validada."""
import numpy as np
import pandas as pd


def window_data(df, window=20):
    """Janelas de retornos inteiramente dentro de um segmento contínuo conhecido."""
    if not isinstance(window, int) or window < 1:
        raise ValueError('Tamanho de janela inválido.')
    values = df['close'].to_numpy(dtype=np.float64)
    if len(values) < 251 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('O treino exige pelo menos 251 preços positivos, finitos e sem lacunas.')
    # Os segmentos são identificados por execuções contíguas, sem reconectar IDs repetidos.
    segments = df['segment_id'].to_numpy() if 'segment_id' in df else np.zeros(len(values))
    if any(x is None for x in segments) or np.asarray(segments != segments).any():
        raise ValueError('Identificação de segmento ausente.')
    same = segments[1:] == segments[:-1]
    returns = np.full(len(values)-1, np.nan)
    np.divide(np.diff(values), values[:-1], out=returns, where=same)
    if not np.isfinite(returns[same]).all():
        raise ValueError('Retornos inválidos.')
    ends = np.array([i for i in range(window, len(returns)+1) if same[i-window:i].all()], dtype=int)
    if not len(ends):
        raise ValueError('Nenhuma janela completa disponível entre as lacunas.')
    windows = np.stack([returns[i-window:i] for i in ends])
    return windows, ends


def split_windows(df, window=20):
    windows, ends = window_data(df, window)
    if 'train_end_exclusive' in df.attrs:
        times = pd.to_datetime(df['observed_at'], utc=True)
        boundary = pd.Timestamp(df.attrs['train_end_exclusive'])
        if boundary.tzinfo is None:
            raise ValueError('Limite do treino deve ter fuso.')
        train_mask = (times.iloc[ends] < boundary).to_numpy()
        # Cada janela de teste começa com um preço posterior ao fim do treino.
        # Não usa nem o preço nem os retornos do último dia de treinamento.
        test_mask = (times.iloc[ends-window] >= boundary).to_numpy()
        train, test = windows[train_mask], windows[test_mask]
        test_ends = ends[test_mask]
    else:
        train, test, test_ends = split_by_fraction(windows, ends, window)
    if len(train) < 1:
        raise ValueError('Nenhuma janela completa de treino nas datas escolhidas.')
    if len(test) < 10:
        raise ValueError('São necessárias 10 janelas completas de avaliação após o fim do treino. '
                         'Antecipe o fim do treino ou amplie o fim da avaliação.')
    return train, test, test_ends


def split_by_fraction(windows, ends, window):
    """Compatibilidade para chamadas sem datas explícitas."""
    cut = int(len(windows)*0.75)
    if cut < 1:
        raise ValueError('Histórico insuficiente para treino.')
    train = windows[:cut]
    # Separação por posições originais: nenhum retorno pertence a treino e teste.
    mask = (np.arange(len(windows)) >= cut) & (ends-window >= ends[cut-1])
    return train, windows[mask], ends[mask]


def prepare_windows(df, window=20):
    train, test, _ = split_windows(df, window)
    mean, std = float(train.mean()), float(train.std())
    if std < 1e-8:
        raise ValueError('Retornos quase constantes.')
    return ((train-mean)/std).astype(np.float32), ((test-mean)/std).astype(np.float32), mean, std


def analyze(df, epochs=60, window=20, seed=42):
    import torch
    from torch import nn
    train, test, _, _ = prepare_windows(df, window)
    torch.manual_seed(seed)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = nn.Sequential(nn.Linear(window,12), nn.ReLU(), nn.Linear(12,4), nn.ReLU(),
                          nn.Linear(4,12), nn.ReLU(), nn.Linear(12,window)).to(device)
    x = torch.tensor(train, device=device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    model.train()
    for _ in range(int(epochs)):
        optimizer.zero_grad()
        loss = ((model(x)-x)**2).mean()
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.no_grad():
        tr = ((model(x)-x)**2).mean(dim=1).cpu().numpy()
        xt = torch.tensor(test, device=device)
        te = ((model(xt)-xt)**2).mean(dim=1).cpu().numpy()
    threshold = float(np.quantile(tr, 0.99))
    _, _, test_ends = split_windows(df, window)
    last_at = str(df['observed_at'].iloc[test_ends[-1]]) if 'observed_at' in df else int(test_ends[-1])
    return {'device':device, 'train_n':len(train), 'test_n':len(test),
            'train_mse':float(tr.mean()), 'test_mse':float(te.mean()),
            'threshold':threshold, 'last_mse':float(te[-1]), 'anomalous':bool(te[-1]>threshold),
            'last_evaluated_at':last_at, 'selected_period':df.attrs.get('model_period')}
