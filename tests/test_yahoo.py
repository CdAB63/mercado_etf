import json
import sys
import tempfile
import types
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd
import collectors
import core
import market_data as md
from model import prepare_windows

ASSET={'id':'BOVA11','symbol':'BOVA11','exchange':'BVMF','kind':'ETF','currency':'BRL','timezone':'America/Sao_Paulo'}
NOW=pd.Timestamp('2026-10-27 17:00:00Z')


class LazyMetadata(Mapping):
    """Metadados com acesso tardio, como HistoryMetadata do yfinance."""
    def __init__(self, values):
        self.values_by_key = values
        self.accessed = []

    def __getitem__(self, key):
        self.accessed.append(key)
        if key == 'tradingPeriods':
            raise AssertionError('A validação não deve buscar horários de pregão.')
        return self.values_by_key[key]

    def __iter__(self):
        return iter([*self.values_by_key, 'tradingPeriods'])

    def __len__(self):
        return len(self.values_by_key) + 1


def history():
    return pd.DataFrame({'Open':[201.13,140.,174.5], 'High':[202.67,175.82,175.66],
        'Low':[200.23,140.,171.97], 'Close':[201.69,172.42,172.92],
        'Adj Close':[200.69,171.42,171.92], 'Volume':[8000330,23799393,6396669],
        'Dividends':[0.,0.,0.], 'Stock Splits':[0.,0.,0.]},
        index=pd.DatetimeIndex(['2026-10-23','2026-10-26','2026-10-27'],tz='America/Sao_Paulo'))


def training_data():
    rng=np.random.default_rng(2)
    close=100*np.cumprod(1+rng.normal(0.001,0.005,400))
    return pd.DataFrame({'observed_at':pd.date_range('2024-01-01',periods=400,freq='B',tz='UTC'),
        'close':close,'adjusted_close':close*0.99,'is_final':True})


class YahooTests(unittest.TestCase):
    def test_route_old_config(self):
        self.assertEqual(md.provider_for(ASSET),'yfinance')
        self.assertEqual(md.provider_for(dict(ASSET,id='IVVB11')),'yfinance')
        self.assertEqual(md.provider_for(dict(ASSET,id='SPY')),'twelvedata')
        self.assertEqual(md.provider_for(dict(ASSET,provider='twelvedata')),'twelvedata')
        self.assertEqual(md.yahoo_symbol(ASSET),'BOVA11.SA')

    def test_fetch_settings_metadata_and_finality(self):
        ticker=MagicMock()
        ticker.history.return_value=history()
        ticker.history_metadata={'symbol':'BOVA11.SA','currency':'BRL'}
        yf=types.SimpleNamespace(Ticker=MagicMock(return_value=ticker))
        with patch.dict(sys.modules,{'yfinance':yf}):
            df=collectors.fetch_market(ASSET,{},now=NOW)
        args=ticker.history.call_args.kwargs
        self.assertEqual(args['period'],'2y')
        self.assertFalse(args['auto_adjust'])
        self.assertFalse(args['repair'])
        self.assertTrue(args['actions'])
        self.assertEqual(df.attrs['source'],'yfinance')
        self.assertEqual(df['is_final'].tolist(),[True,True,False])
        self.assertAlmostEqual(df.close.iloc[0],201.69)
        self.assertAlmostEqual(df.adjusted_close.iloc[0],200.69)

    def test_wrong_currency_rejected(self):
        ticker=MagicMock(history_metadata={'symbol':'BOVA11.SA','currency':'USD'})
        ticker.history.return_value=history()
        with patch.dict(sys.modules,{'yfinance':types.SimpleNamespace(Ticker=lambda x:ticker)}):
            with self.assertRaisesRegex(ValueError,'moeda'):
                collectors.fetch_yahoo(ASSET,'1day')

    def test_twelve_route_stays_available(self):
        raw=md.normalize_yahoo(history(),ASSET)
        asset=dict(ASSET,id='SPY',symbol='SPY')
        with patch.object(collectors,'fetch_twelve',return_value=raw) as req, patch.object(collectors,'fetch_yahoo') as yh:
            df=collectors.fetch_market(asset,{'timezone':'UTC'},now=NOW)
        req.assert_called_once();yh.assert_not_called()
        self.assertEqual(df.attrs['source'],'twelvedata')

    def test_lazy_mapping_metadata_accepted_without_loading_other_fields(self):
        for asset_id in ('BOVA11', 'IVVB11'):
            with self.subTest(asset=asset_id):
                asset = dict(ASSET, id=asset_id, symbol=asset_id)
                meta = LazyMetadata({'symbol': asset_id+'.SA', 'currency': 'BRL'})
                ticker = types.SimpleNamespace(history=lambda **kw: history(), history_metadata=meta)
                with patch.dict(sys.modules, {'yfinance': types.SimpleNamespace(Ticker=lambda x: ticker)}):
                    df = collectors.fetch_market(asset, {}, now=NOW)
                self.assertEqual(len(df), 3)
                self.assertEqual(meta.accessed, ['symbol', 'currency'])
                self.assertEqual(df.attrs['source'], 'yfinance')

    def test_lazy_mapping_wrong_identity_rejected(self):
        for values, message in [({'symbol': 'IVVB11.SA', 'currency': 'BRL'}, 'símbolo'),
                                ({'symbol': 'BOVA11.SA', 'currency': 'USD'}, 'moeda')]:
            with self.subTest(values=values):
                ticker = types.SimpleNamespace(history=lambda **kw: history(), history_metadata=LazyMetadata(values))
                with patch.dict(sys.modules, {'yfinance': types.SimpleNamespace(Ticker=lambda x: ticker)}):
                    with self.assertRaisesRegex(ValueError, message):
                        collectors.fetch_market(ASSET, {}, now=NOW)

    def test_missing_identity_rejected_for_dict_and_mapping(self):
        for factory in (dict, LazyMetadata):
            for values in ({}, {'symbol': 'BOVA11.SA'}, {'currency': 'BRL'}):
                with self.subTest(factory=factory.__name__, values=values):
                    ticker = types.SimpleNamespace(history=lambda **kw: history(), history_metadata=factory(values))
                    with patch.dict(sys.modules, {'yfinance': types.SimpleNamespace(Ticker=lambda x: ticker)}):
                        with self.assertRaisesRegex(ValueError, 'símbolo|moeda'):
                            collectors.fetch_market(ASSET, {}, now=NOW)

    def test_invalid_metadata_format_rejected(self):
        for meta in (None, [], 'BOVA11.SA', [('symbol', 'BOVA11.SA'), ('currency', 'BRL')]):
            with self.subTest(meta=meta):
                ticker = types.SimpleNamespace(history=lambda **kw: history(), history_metadata=meta)
                with patch.dict(sys.modules, {'yfinance': types.SimpleNamespace(Ticker=lambda x: ticker)}):
                    with self.assertRaisesRegex(ValueError, 'formato inválido'):
                        collectors.fetch_market(ASSET, {}, now=NOW)

    def test_today_not_final_even_after_close(self):
        df=md.validate_bars(md.normalize_yahoo(history(),ASSET))
        stamped=md.stamp_finality(df,ASSET,'1day',now='2026-10-28T02:00:00Z')
        self.assertFalse(stamped.is_final.iloc[-1]) # 23:00 ainda é dia 27 em SP.
        refreshed=md.stamp_finality(df,ASSET,'1day',now='2026-10-28T12:00:00Z')
        self.assertTrue(refreshed.is_final.iloc[-1])

    def test_partial_stays_partial_without_refetch(self):
        df=training_data()
        df.loc[len(df)-1,'is_final']=False
        trained=md.training_frame(df,now=NOW)
        self.assertEqual(len(trained),len(df)-1)

    def test_invalid_or_missing_ohlc_rejected(self):
        df=md.normalize_yahoo(history(),ASSET)
        for value in [float('nan'),0.,100000.]:
            bad=df.copy();bad.loc[1,'open']=value
            with self.assertRaises(ValueError):md.validate_bars(bad)

    def test_duplicate_dates_rejected(self):
        df=md.normalize_yahoo(history(),ASSET)
        with self.assertRaisesRegex(ValueError,'duplicados'):
            md.validate_bars(pd.concat([df,df]))

    def test_missing_timezone_rejected(self):
        df=history();df.index=df.index.tz_localize(None)
        with self.assertRaisesRegex(ValueError,'fuso'):
            md.normalize_yahoo(df,ASSET)

    def test_future_date_rejected(self):
        df=md.validate_bars(md.normalize_yahoo(history(),ASSET))
        with self.assertRaisesRegex(ValueError,'futura'):
            md.stamp_finality(df,ASSET,'1day',now='2026-10-26T17:00:00Z')

    def test_jumps_flagged_but_never_changed(self):
        df=md.validate_bars(md.normalize_yahoo(history(),ASSET))
        result=md.diagnostics(df)
        self.assertTrue(result.review_move.iloc[1])
        self.assertAlmostEqual(result.close.iloc[1],172.42)
        self.assertEqual(len(result),len(df))

    def test_adjusted_series_never_filled_from_close(self):
        df=training_data();df.loc[20,'adjusted_close']=np.nan
        with self.assertRaisesRegex(ValueError,'lacunas'):
            md.training_frame(df,'adjusted_close',now=NOW)
        good=md.training_frame(df,'close',now=NOW)
        self.assertEqual(len(good),len(df))

    def test_legacy_unconfirmed_prefix_not_internal_gap(self):
        df=training_data();df.loc[0,'is_final']=None
        self.assertEqual(len(md.training_frame(df,now=NOW)),len(df)-1)
        df.loc[15,'is_final']=None
        with self.assertRaisesRegex(ValueError,'entre sessões'):
            md.training_frame(df,now=NOW)

    def test_training_scaler_uses_past_only(self):
        df=training_data()
        a=prepare_windows(df)
        changed=df.copy();changed.loc[len(df)-1,'close']*=10
        b=prepare_windows(changed)
        np.testing.assert_array_equal(a[0],b[0])
        self.assertEqual(a[2:],b[2:])
        self.assertFalse(np.array_equal(a[1],b[1]))

    def test_save_binds_source_adjustment_and_finality(self):
        df=md.stamp_finality(md.validate_bars(md.normalize_yahoo(history(),ASSET)),ASSET,'1day',NOW)
        df.attrs['price_basis']='yahoo_auto_adjust_false_repair_false'
        con=MagicMock();cur=con.__enter__.return_value.cursor.return_value.__enter__.return_value
        with patch.object(core,'connection',return_value=con):
            self.assertEqual(core.save(df,'BOVA11','1day','yfinance'),3)
        sql,rows=cur.executemany.call_args.args
        self.assertIn('adjusted_close',sql)
        self.assertEqual(rows[0][8],'yfinance')
        self.assertAlmostEqual(rows[0][9],200.69)
        self.assertIs(rows[-1][12],False)

    def test_bad_lot_never_opens_transaction(self):
        df=md.normalize_yahoo(history(),ASSET);df.loc[1,'low']=-1
        with patch.object(core,'connection') as con, self.assertRaises(ValueError):
            core.save(df,'BOVA11','1day','yfinance')
        con.assert_not_called()

    def test_updater_preserves_config(self):
        from atualizar import update
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original='{"database":{"host":"my-server"}}'
            (root/'config.json').write_text(original)
            (root/'app.py').write_text('# old user code')
            backup=update(root)
            self.assertEqual((root/'config.json').read_text(),original)
            self.assertEqual((backup/'app.py').read_text(),'# old user code')
            self.assertTrue((root/'collectors.py').exists())


if __name__=='__main__':unittest.main()
