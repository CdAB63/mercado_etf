"""Execute: python diagnostico_twelve.py --config config.json

Usa a chave em variável de ambiente; não requer banco, pandas ou Streamlit.
"""
import argparse
import json
import os
import sys
from twelvedata_client import diagnose, TwelveDataError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.environ.get('MERCADO_CONFIG', 'config.json'))
    parser.add_argument('--assets', nargs='+', default=['BOVA11', 'IVVB11'])
    args = parser.parse_args()
    try:
        with open(args.config, encoding='utf-8') as f:
            config = json.load(f)
        assets = {a['id']: a for a in config['assets']}
        reports = []
        for asset_id in args.assets:
            if asset_id not in assets:
                raise TwelveDataError('Ativo ausente no config.json: '+asset_id)
            reports.append(diagnose(assets[asset_id], config['provider']))
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return 0 if all(x['consulta_diaria']['resultado'] == 'OK' for x in reports) else 1
    except (OSError, ValueError, KeyError, TwelveDataError) as exc:
        print('Diagnóstico não executado: '+str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
