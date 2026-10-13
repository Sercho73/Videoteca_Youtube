import http.client
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode

from youtubelibrary.server import make_server
from youtubelibrary.mobile import make_mobile_server, load_mobile_config, MobileAccess


class MobileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = make_server(0, self.temp.name)
        threading.Thread(target=self.backend.serve_forever, daemon=True).start()
        self.gateway = make_mobile_server('127.0.0.1', 0, '127.0.0.0/8', 'mobile-test-password-1234', self.backend.server_port)
        threading.Thread(target=self.gateway.serve_forever, daemon=True).start()

    def tearDown(self):
        self.gateway.shutdown(); self.gateway.server_close()
        self.backend.shutdown(); self.backend.server_close()
        self.temp.cleanup()

    def request(self, method='GET', path='/', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.gateway.server_port)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        status, response_headers, contents = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, contents

    def login(self):
        status, headers, _ = self.request('POST', '/acceso', urlencode({'password': 'mobile-test-password-1234'}), {'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(status, 303)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        cookie = SimpleCookie(headers['Set-Cookie'])
        return 'videoteca_mobile=' + cookie['videoteca_mobile'].value

    def test_password_required_for_pages_catalog_and_backups(self):
        self.assertEqual(self.request()[0], 303)
        self.assertEqual(self.request(path='/api/state')[0], 401)
        self.assertEqual(self.request(path='/api/backup')[0], 401)
        self.assertEqual(self.request(path='/acceso')[0], 200)
        self.assertEqual(self.request(path='/api/state', headers={'Cookie': 'videoteca_mobile=forged'})[0], 401)

    def test_login_can_return_json_for_inline_form(self):
        status, headers, body = self.request('POST', '/acceso', urlencode({'password': 'mobile-test-password-1234'}), {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'ok': True})
        self.assertIn('HttpOnly', headers['Set-Cookie'])

    def test_authenticated_reads_and_mutations_keep_csrf_checks(self):
        cookie = self.login()
        status, _, raw = self.request(path='/api/state', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        token = json.loads(raw)['token']
        values = {'Cookie': cookie, 'Content-Type': 'application/json', 'X-Videoteca-Token': token}
        self.assertEqual(self.request('POST', '/api/youtube/sync', '{}', values)[0], 400)
        self.assertEqual(self.request('POST', '/api/youtube/sync', '{}', dict(values, Origin='https://evil.example'))[0], 403)
        values.pop('X-Videoteca-Token')
        self.assertEqual(self.request('POST', '/api/youtube/sync', '{}', values)[0], 403)

    def test_local_credentials_and_network_administration_never_proxied(self):
        cookie = self.login()
        for path in ('/api/mobile', '/api/youtube/settings', '/api/%6dobile'):
            self.assertEqual(self.request(path=path, headers={'Cookie': cookie})[0], 403)
        self.assertEqual(self.request(path='/api/state', headers={'Cookie': cookie, 'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/acceso', 'password=x', {'Content-Type': 'application/x-www-form-urlencoded', 'Origin': 'https://evil.example'})[0], 403)

    def test_wrong_password_and_attempt_limit(self):
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        for _ in range(5):
            self.assertEqual(self.request('POST', '/acceso', 'password=wrong', headers)[0], 401)
        self.assertEqual(self.request('POST', '/acceso', 'password=wrong', headers)[0], 429)

    def test_expired_session_is_rejected(self):
        cookie = self.login()
        with patch('youtubelibrary.mobile.time.monotonic', return_value=time.monotonic() + 13 * 3600):
            self.assertEqual(self.request(path='/api/state', headers={'Cookie': cookie})[0], 401)

    def test_client_outside_subnet_is_rejected_before_login(self):
        self.gateway.shutdown(); self.gateway.server_close()
        self.gateway = make_mobile_server('127.0.0.1', 0, '127.0.0.2/32', 'mobile-test-password-1234', self.backend.server_port)
        threading.Thread(target=self.gateway.serve_forever, daemon=True).start()
        self.assertEqual(self.request(path='/acceso')[0], 403)

    def test_public_listening_addresses_are_rejected(self):
        path = Path(self.temp.name) / 'mobile-access.json'
        for host in ('0.0.0.0', '8.8.8.8', '127.0.0.1'):
            path.write_text(json.dumps({'enabled': True, 'host': host, 'network': host + '/32', 'password': 'long-password-for-mobile-test'}))
            with self.subTest(host=host), self.assertRaises(ValueError):
                load_mobile_config(Path(self.temp.name))

    def test_malformed_configuration_disables_only_mobile_gateway(self):
        path = Path(self.temp.name) / 'mobile-access.json'
        access = MobileAccess(Path(self.temp.name), self.backend.server_port)
        for values in ([1], {'enabled': True, 'password': None}, {'enabled': 'yes'}, {'enabled': True, 'interface': []}, {'enabled': True, 'host': 3232235786, 'network': '192.168.1.0/24', 'password': 'mobile-test-password-1234'}):
            path.write_text(json.dumps(values))
            with self.subTest(values=values):
                self.assertFalse(access.refresh()['enabled'])
                self.assertIn('error', access.snapshot())
                connection = http.client.HTTPConnection('127.0.0.1', self.backend.server_port)
                connection.request('GET', '/api/state')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read(); connection.close()

    def test_refresh_recovers_after_network_returns(self):
        access = MobileAccess(Path(self.temp.name), self.backend.server_port)
        with patch('youtubelibrary.mobile.load_mobile_config', side_effect=OSError('Network unavailable')):
            self.assertFalse(access.refresh()['enabled'])
        current = {'host': '127.0.0.1', 'port': 0, 'network': '127.0.0.0/8', 'password': 'mobile-test-password-1234'}
        with patch('youtubelibrary.mobile.load_mobile_config', return_value=current):
            result = access.refresh()
        self.assertTrue(result['enabled'])
        self.assertEqual(result['url'], 'http://127.0.0.1:' + str(access.server.server_port) + '/')
        connection = http.client.HTTPConnection('127.0.0.1', access.server.server_port)
        connection.request('GET', '/api/state')
        response = connection.getresponse()
        self.assertEqual(response.status, 401)
        response.read(); connection.close()
        access.close()



if __name__ == '__main__': unittest.main()
