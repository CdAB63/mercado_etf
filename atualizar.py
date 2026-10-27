"""Atualiza arquivos do programa, com backup; preserva config.json e banco.

Execute deste pacote: python atualizar.py --dest /caminho/da/instalacao/mercado_etf
"""
import argparse
import shutil
import tempfile
from pathlib import Path

FILES = ['app.py','core.py','market_data.py','collectors.py','model.py','schema.sql',
         'twelvedata_client.py','diagnostico_twelve.py','requirements.txt',
         'config.example.json','README.md']


def update(destination):
    source = Path(__file__).resolve().parent
    target = Path(destination).expanduser().resolve()
    if source == target:
        raise ValueError('Extraia o pacote em outra pasta antes de atualizar a instalação antiga.')
    if not (target/'app.py').is_file() or not (target/'config.json').is_file():
        raise ValueError('Destino precisa conter a instalação anterior: app.py e config.json.')
    for name in FILES:
        if not (source/name).is_file():
            raise ValueError('Pacote incompleto: '+name)
    backup = Path(tempfile.mkdtemp(prefix='backup_antes_v021_',dir=target))
    for name in FILES:
        existing = target/name
        if existing.is_symlink():
            raise ValueError('Atualização interrompida: arquivo de destino é link simbólico: '+name)
        if existing.exists():
            shutil.copy2(existing,backup/name)
    for name in FILES:
        shutil.copy2(source/name,target/name)
    return backup


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest',required=True)
    args=parser.parse_args()
    try:
        print('Atualização concluída. Backup:',update(args.dest))
        print('config.json preservado. Reinicie o Streamlit; o banco receberá colunas adicionais.')
    except (OSError,ValueError) as exc:
        parser.exit(1,str(exc)+'\n')
