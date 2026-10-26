"""Autoencoder de janelas diárias: demonstração experimental, sem emissão de ordens."""
import numpy as np
import torch
from torch import nn

def analyze(df, epochs=60, window=20, seed=42):
    torch.manual_seed(seed); np.random.seed(seed)
    returns=df.close.pct_change().dropna().to_numpy(dtype=np.float32)
    if len(returns)<250: raise ValueError('São necessários ao menos 251 fechamentos para a demonstração.')
    windows=np.stack([returns[i-window:i] for i in range(window,len(returns)+1)])
    # Divisão por tempo, com exclusão de janelas compartilhadas na fronteira.
    cut=int(len(windows)*0.75); train=windows[:cut]; test=windows[cut+window-1:]
    if len(test)<10: raise ValueError('Histórico insuficiente para validação temporal.')
    mean=float(train.mean()); std=float(train.std())
    if std < 1e-8: raise ValueError('Retornos quase constantes: não é possível normalizar.')
    train=(train-mean)/std; test=(test-mean)/std
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model=nn.Sequential(nn.Linear(window,12),nn.ReLU(),nn.Linear(12,4),nn.ReLU(),nn.Linear(4,12),nn.ReLU(),nn.Linear(12,window)).to(device)
    x=torch.tensor(train,device=device); optimizer=torch.optim.Adam(model.parameters(),lr=0.001)
    model.train()
    for _ in range(int(epochs)):
        optimizer.zero_grad(); loss=((model(x)-x)**2).mean(); loss.backward(); optimizer.step()
    model.eval()
    with torch.no_grad():
        tr=((model(x)-x)**2).mean(dim=1).cpu().numpy()
        xt=torch.tensor(test,device=device); te=((model(xt)-xt)**2).mean(dim=1).cpu().numpy()
    threshold=float(np.quantile(tr,0.99))
    return {'device':device,'train_n':len(train),'test_n':len(test),'train_mse':float(tr.mean()),'test_mse':float(te.mean()),'threshold':threshold,'last_mse':float(te[-1]),'anomalous':bool(te[-1]>threshold)}
