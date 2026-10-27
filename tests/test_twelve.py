import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import twelvedata_client as td

KEY = 'secret-test-key-012345'
ASSET = {'id': 'BOVA11', 'symbol': 'BOVA11', 'exchange': 'BVMF', 'currency': 'BRL'}
PROVIDER = {'api_key_env': 'TEST_TWELVE_KEY', 'timezone': 'UTC'}


def response_payload():
    return {'meta': {'symbol': 'BOVA11', 'mic_code': 'BVMF', 'exchange': 'BOVESPA',
                     'currency': 'BRL', 'interval': '1day'},
            'values': [{'datetime': '2026-10-26', 'open': '100', 'high': '102',
                        'low': '99', 'close': '101', 'volume': '1000'}], 'status': 'ok'}


class Response(io.BytesIO):
    status = 200


class Tests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'TEST_TWELVE_KEY': KEY})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_legacy_bvmf_is_mic_not_exchange(self):
        self.assertEqual(td.instrument_params(ASSET), {'symbol': 'BOVA11', 'mic_code': 'BVMF'})

    def test_legacy_b3_is_mic(self):
        self.assertEqual(td.instrument_params(dict(ASSET, exchange='B3'))['mic_code'], 'BVMF')

    def test_named_exchange_preserved(self):
        self.assertEqual(td.instrument_params(dict(ASSET, exchange='BOVESPA'))['exchange'], 'BOVESPA')

    def test_us_and_fx_unaffected(self):
        self.assertEqual(td.instrument_params({'symbol':'SPY','exchange':'NYSE'}), {'symbol':'SPY','exchange':'NYSE'})
        self.assertEqual(td.instrument_params({'symbol':'USD/BRL'}), {'symbol':'USD/BRL'})

    def test_mic_precedence_and_conflict(self):
        self.assertEqual(td.instrument_params({'symbol':'SPY','exchange':'NYSE','mic_code':'ARCX'}), {'symbol':'SPY','mic_code':'ARCX'})
        with self.assertRaises(td.TwelveDataError):
            td.instrument_params(dict(ASSET, mic_code='ARCX'))

    def test_actual_url_parameters(self):
        def opener(req, timeout):
            params=parse_qs(urlsplit(req.full_url).query)
            self.assertEqual(params['mic_code'], ['BVMF'])
            self.assertNotIn('exchange', params)
            self.assertEqual(params['apikey'], [KEY])
            self.assertEqual(params['interval'], ['1day'])
            return Response(json.dumps(response_payload()).encode())
        with patch.object(td, 'urlopen', side_effect=opener):
            self.assertEqual(td.time_series(ASSET, PROVIDER)['meta']['symbol'], 'BOVA11')

    def test_http404_body_kept_key_removed(self):
        raw=json.dumps({'code':404, 'message':'Unknown symbol, key='+KEY}).encode()
        exc=HTTPError('https://api.twelvedata.com/time_series?apikey='+KEY,404,'Not found',{},io.BytesIO(raw))
        with patch.object(td, 'urlopen', side_effect=exc), self.assertRaises(td.TwelveDataError) as ctx:
            td.time_series(ASSET, PROVIDER)
        self.assertIn('Unknown symbol', str(ctx.exception))
        self.assertIn('404', str(ctx.exception))
        self.assertNotIn(KEY, str(ctx.exception))

    def test_json_error_on_http200(self):
        raw=json.dumps({'status':'error','code':403,'message':'Plan restricted'}).encode()
        with patch.object(td,'urlopen',return_value=Response(raw)), self.assertRaises(td.TwelveDataError) as ctx:
            td.time_series(ASSET,PROVIDER)
        self.assertIn('Plan restricted',str(ctx.exception))

    def test_non_json_error(self):
        exc=HTTPError('url',502,'Bad gateway',{},io.BytesIO(b'<html>Error</html>'))
        with patch.object(td,'urlopen',side_effect=exc), self.assertRaises(td.TwelveDataError) as ctx:
            td.time_series(ASSET,PROVIDER)
        self.assertIn('502',str(ctx.exception))

    def test_network_error_does_not_echo_url(self):
        with patch.object(td,'urlopen',side_effect=URLError('https://x/?apikey='+KEY)), self.assertRaises(td.TwelveDataError) as ctx:
            td.time_series(ASSET,PROVIDER)
        self.assertNotIn(KEY,str(ctx.exception))

    def test_missing_key(self):
        with patch.dict(os.environ, {'TEST_TWELVE_KEY':''}), self.assertRaises(td.TwelveDataError):
            td.time_series(ASSET,PROVIDER)

    def test_wrong_instrument_rejected(self):
        for field, value in [('symbol','IVVB11'),('currency','USD'),('mic_code','ARCX'),('interval','1min')]:
            with self.subTest(field=field):
                payload=response_payload();payload['meta'][field]=value
                with patch.object(td,'request_json',return_value=payload), self.assertRaises(td.TwelveDataError):
                    td.time_series(ASSET,PROVIDER)

    def test_missing_metadata_rejected(self):
        payload=response_payload(); del payload['meta']['mic_code']
        with patch.object(td,'request_json',return_value=payload), self.assertRaises(td.TwelveDataError):
            td.time_series(ASSET,PROVIDER)

    def test_forex_metadata_without_currency_iso(self):
        payload=response_payload()
        payload['meta']={'symbol':'USD/BRL', 'currency_base':'US Dollar',
                         'currency_quote':'Brazilian Real', 'interval':'1day'}
        with patch.object(td,'request_json',return_value=payload):
            result=td.time_series({'symbol':'USD/BRL','kind':'FX','currency':'BRL'},PROVIDER)
        self.assertEqual(result['meta']['symbol'],'USD/BRL')

    def test_diagnostic_catalog_and_history(self):
        catalog={'data':[{'symbol':'BOVA11','exchange':'BOVESPA','mic_code':'BVMF','access':{'plan':'Grow'}}]}
        with patch.object(td,'request_json',side_effect=[catalog,response_payload()]) as request:
            report=td.diagnose(ASSET,PROVIDER)
        self.assertEqual(request.call_count,2)
        self.assertEqual(report['consulta_diaria']['resultado'],'OK')
        self.assertEqual(report['catalogo_correspondencias_exatas'][0]['access']['plan'],'Grow')

    def test_diagnostic_does_not_guess_other_asset(self):
        catalog={'data':[{'symbol':'BOVA39','currency':'BRL'}]}
        with patch.object(td,'request_json',side_effect=[catalog,td.TwelveDataError('404 unknown')]):
            report=td.diagnose(ASSET,PROVIDER)
        self.assertEqual(report['catalogo_correspondencias_exatas'],[])
        self.assertEqual(report['consulta_diaria']['resultado'],'FALHOU')


if __name__ == '__main__':
    unittest.main()
