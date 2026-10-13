"""Password-protected gateway bound to one private LAN interface."""
import hmac
import http.client
import ipaddress
import json
import secrets
import subprocess
import threading
import time
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, unquote


def load_mobile_config(data_dir):
    path = data_dir / 'mobile-access.json'
    if not path.exists():
        return None
    values = json.loads(path.read_text())
    if not isinstance(values, dict) or type(values.get('enabled', False)) is not bool:
        raise ValueError('Configuración móvil no válida.')
    if not values.get('enabled'):
        return None
    interface = values.get('interface')
    if interface is not None and (not isinstance(interface, str) or interface not in {'en0', 'en1', 'en2'}):
        raise ValueError('Interfaz de red no válida.')
    if interface:
        host = subprocess.check_output(['ipconfig', 'getifaddr', interface], text=True, timeout=3).strip()
        mask = subprocess.check_output(['ipconfig', 'getoption', interface, 'subnet_mask'], text=True, timeout=3).strip()
        values.update(host=host, network=str(ipaddress.ip_network(host + '/' + mask, strict=False)))
    if not isinstance(values.get('host'), str) or not isinstance(values.get('network'), str):
        raise ValueError('Configuración de red no válida.')
    address = ipaddress.ip_address(values.get('host'))
    network = ipaddress.ip_network(values.get('network'))
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast or address.is_reserved or address not in network:
        raise ValueError('Se requiere una dirección de red local.')
    if not network.is_private or network.version != 4:
        raise ValueError('Se requiere una subred privada.')
    password, port = values.get('password'), values.get('port', 8792)
    if not isinstance(password, str) or not 20 <= len(password) <= 200 or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Configuración móvil no válida.')
    return values


class MobileAccess:
    def __init__(self, data_dir, backend_port):
        self.data_dir, self.backend_port = data_dir, backend_port
        self.server, self.state = None, {'enabled': False}
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def _close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def close(self):
        with self.lock:
            self._close()
            self.state = {'enabled': False}

    def refresh(self):
        with self.lock:
            self._close()
            self.state = {'enabled': False}
            try:
                values = load_mobile_config(self.data_dir)
                if values:
                    self.server = make_mobile_server(values['host'], values.get('port', 8792), values['network'], values['password'], self.backend_port)
                    threading.Thread(target=self.server.serve_forever, daemon=True).start()
                    self.state = {'enabled': True, 'url': 'http://' + values['host'] + ':' + str(self.server.server_port) + '/', 'password': values['password']}
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                self.state = {'enabled': False, 'error': 'No se ha podido activar el acceso móvil. Revisa la conexión de red del Mac y pulsa Actualizar dirección.'}
            return dict(self.state)


def make_mobile_server(host, port, network, password, backend_port):
    allowed_network = ipaddress.ip_network(network)
    sessions, attempts = {}, {}
    lock = threading.Lock()
    backend_host = '127.0.0.1:' + str(backend_port)
    backend_origin = 'http://' + backend_host

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def reply(self, body=b'', status=200, content_type='text/html; charset=utf-8', headers=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://i.ytimg.com https://img.youtube.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def error(self, message, status=403):
            self.reply(json.dumps({'error': message}, ensure_ascii=False).encode(), status, 'application/json; charset=utf-8')

        def valid_request(self):
            expected = host + ':' + str(self.server.server_port)
            if ipaddress.ip_address(self.client_address[0]) not in allowed_network or self.headers.get('Host') != expected:
                self.error('Acceso limitado a la red local.')
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                self.error('Origen no permitido.')
                return False
            if self.headers.get('Sec-Fetch-Site') == 'cross-site' and self.command != 'GET':
                self.error('Origen no permitido.')
                return False
            return True

        def authenticated(self):
            try:
                cookie = SimpleCookie(self.headers.get('Cookie', ''))
                value = cookie['videoteca_mobile'].value if 'videoteca_mobile' in cookie else ''
            except CookieError:
                return False
            now = time.monotonic()
            with lock:
                for key in list(sessions):
                    if sessions[key] < now:
                        del sessions[key]
                return bool(value) and value in sessions

        def login_page(self, message='', status=200):
            html = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Acceso móvil · Videoteca</title><script src="/login.js" defer></script><link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/style.css"></head><body class="mobile-login"><main><h1>Videoteca</h1><p>Acceso desde tu red local</p><form id="mobile-login-form" action="/acceso" method="post"><label for="password">Contraseña</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="200"><button class="primary" type="submit">Entrar</button></form><p id="login-error" role="alert">''' + message + '''</p><p class="small muted">Encontrarás la contraseña en «Acceso móvil» al abrir Videoteca en el Mac. Utiliza una Wi-Fi de confianza: esta conexión local usa HTTP.</p></main></body></html>'''
            self.reply(html.encode(), status)

        def login(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                size = 0
            if not 0 < size <= 2048 or self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                self.error('Solicitud no válida.', 400)
                return
            peer, now = self.client_address[0], time.monotonic()
            with lock:
                recent = [t for t in attempts.get(peer, []) if now - t < 300]
                attempts[peer] = recent
                limited = len(recent) >= 5
            if limited:
                self.login_page('Demasiados intentos. Espera cinco minutos.', 429)
                return
            try:
                supplied = parse_qs(self.rfile.read(size).decode('utf-8')).get('password', [''])[0]
            except UnicodeError:
                supplied = ''
            if not hmac.compare_digest(supplied.encode(), password.encode()):
                with lock:
                    attempts.setdefault(peer, []).append(now)
                self.login_page('La contraseña no es correcta.', 401)
                return
            session = secrets.token_urlsafe(32)
            with lock:
                attempts.pop(peer, None)
                for key in list(sessions):
                    if sessions[key] < now:
                        del sessions[key]
                if len(sessions) >= 64:
                    del sessions[next(iter(sessions))]
                sessions[session] = now + 12 * 3600
            cookie = 'videoteca_mobile=' + session + '; HttpOnly; SameSite=Strict; Path=/'
            if self.headers.get('Accept') == 'application/json':
                self.reply(b'{"ok":true}', content_type='application/json; charset=utf-8', headers={'Set-Cookie': cookie})
            else:
                self.reply(status=303, headers={'Location': '/', 'Set-Cookie': cookie})

        def proxy(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.error('Solicitud no válida.', 400)
                return
            if not 0 <= size <= 8 * 1024 * 1024:
                self.error('La solicitud supera 8 MB.', 400)
                return
            headers = {'Host': backend_host}
            for name in ('Content-Type', 'X-Videoteca-Token'):
                if name in self.headers:
                    headers[name] = self.headers[name]
            if self.headers.get('Origin'):
                headers['Origin'] = backend_origin
            connection = http.client.HTTPConnection('127.0.0.1', backend_port, timeout=25)
            try:
                connection.request(self.command, self.path, body=self.rfile.read(size) if size else None, headers=headers)
                response = connection.getresponse()
                body = response.read(16 * 1024 * 1024 + 1)
                if len(body) > 16 * 1024 * 1024:
                    self.error('La respuesta es demasiado grande.', 502)
                    return
                self.reply(body, response.status, response.getheader('Content-Type', 'application/octet-stream'))
            except (OSError, http.client.HTTPException):
                self.error('Videoteca no responde en el Mac.', 502)
            finally:
                connection.close()

        def handle_request(self):
            if not self.valid_request():
                return
            path = unquote(urlparse(self.path).path)
            if path.startswith('/api/mobile') or path == '/api/youtube/settings':
                self.error('Gestiona el acceso móvil y la clave de YouTube desde el Mac.')
                return
            if path == '/acceso':
                if self.command == 'GET':
                    self.login_page()
                elif self.command == 'POST':
                    self.login()
                else:
                    self.error('Método no permitido.', 405)
                return
            if self.command == 'GET' and path in {'/style.css', '/favicon.svg', '/login.js'}:
                self.proxy()
                return
            if not self.authenticated():
                if path.startswith('/api/') or self.command != 'GET':
                    self.error('Introduce la contraseña para acceder.', 401)
                else:
                    self.reply(status=303, headers={'Location': '/acceso'})
                return
            self.proxy()

        do_GET = handle_request
        do_POST = handle_request
        do_PATCH = handle_request

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
