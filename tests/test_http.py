import http.client
import json
import tempfile
import threading
import unittest
from urllib.parse import unquote

from youtubelibrary.server import make_server
from test_catalog import payload


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = make_server(0, cls.temp.name)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port)
        merged = {'Content-Type': 'application/json'}
        merged.update(headers or {})
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=merged)
        response = connection.getresponse()
        raw = response.read(); status = response.status; ctype = response.getheader('Content-Type')
        connection.close()
        return status, json.loads(raw) if 'application/json' in ctype else raw

    def test_mobile_access_is_disabled_without_configuration(self):
        status,result=self.request('GET','/api/mobile')
        self.assertEqual(status,200)
        self.assertEqual(result,{'enabled':False})

    def test_rejects_cross_site_and_missing_token(self):
        self.assertEqual(self.request('POST', '/api/import', payload())[0], 403)
        token = self.request('GET', '/api/state')[1]['token']
        self.assertEqual(self.request('POST', '/api/import', payload(), {'X-Videoteca-Token': token, 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': 'evil.example'})[0], 403)

    def test_api_connection_is_protected_and_key_never_returned(self):
        key='B'*39
        self.assertEqual(self.request('POST','/api/youtube/settings',{'api_key':key,'auto_sync':False})[0],403)
        token=self.request('GET','/api/state')[1]['token']
        headers={'X-Videoteca-Token':token}
        status,result=self.request('POST','/api/youtube/settings',{'api_key':key,'auto_sync':False},headers)
        self.assertEqual(status,200)
        self.assertTrue(result['configured'])
        self.assertNotIn(key,json.dumps(self.request('GET','/api/state')[1]))
        self.assertNotIn(key,json.dumps(self.request('GET','/api/backup')[1]))
        self.assertEqual(self.request('POST','/api/youtube/settings',{'api_key':'','auto_sync':False},headers)[0],200)
        self.assertEqual(self.request('POST','/api/youtube/sync',{},headers)[0],400)

    def test_import_and_patch_persist_through_http(self):
        token = self.request('GET', '/api/state')[1]['token']
        headers = {'X-Videoteca-Token': token}
        status, result = self.request('POST', '/api/import', payload(), headers)
        self.assertEqual(status, 200); self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(self.request('PATCH', '/api/videos/9YMuBrnNM-4', {'notes': 'Una nota real'}, headers)[0], 200)
        self.assertEqual(self.request('GET', '/api/videos?q=nota')[1]['total'], 1)

    def test_bookmarklet_encodes_source_without_breaking_comments(self):
        status, result = self.request('GET', '/api/bookmarklet')
        self.assertEqual(status, 200)
        self.assertEqual(unquote(result['bookmarklet'][len('javascript:'):]), result['code'])

    def test_rejects_malformed_input_without_leaking_paths(self):
        token = self.request('GET', '/api/state')[1]['token']
        status, result = self.request('POST', '/api/import', {'unexpected': True}, {'X-Videoteca-Token': token})
        self.assertEqual(status, 400); self.assertIn('formato', result['error'])
        self.assertEqual(self.request('GET', '/../catalog.sqlite3')[0], 404)


if __name__ == '__main__': unittest.main()
