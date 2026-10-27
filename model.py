"""Autoencoder experimental; não é uma estratégia financeira validada."""
import numpy as np


def prepare_windows(df, window=20):
    values = df['close'].to_numpy(dtype=np.float64)
    if len(values) < 251 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('O treino exige pelo menos 251 preços positivos, finitos e sem lacunas.')
    returns = np.diff(values) / values[:-1]
    if not np.isfinite(returns).all():
        raise ValueError('Retornos inválidos.')
    windows = np.stack([returns[i-window:i] for i in range(window, len(returns)+1)])
    cut = int(len(windows)*0.75)
    train = windows[:cut]
    # Janelas de treino e teste não compartilham retornos.
    test = windows[cut+window-1:]
    if len(test) < 10:
        raise ValueError('Histórico insuficiente para o teste temporal.')
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
    return {'device':device, 'train_n':len(train), 'test_n':len(test),
            'train_mse':float(tr.mean()), 'test_mse':float(te.mean()),
            'threshold':threshold, 'last_mse':float(te[-1]), 'anomalous':bool(te[-1]>threshold)}
