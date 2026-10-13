import argparse
import json
import mimetypes
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .catalog import Catalog, ImportError
from .publication import PublicationDates
from .youtube_api import SyncSettings, PlaylistSync
from .mobile import MobileAccess

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = Path.home() / 'Library' / 'Application Support' / 'YouTube Biblioteca'


def make_server(port, data_dir, automatic_dates=False):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    catalog = Catalog(data_dir / 'catalog.sqlite3')
    publication_dates = PublicationDates(catalog)
    playlist_sync = PlaylistSync(catalog, SyncSettings(data_dir / 'youtube-api.json'))
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def safe_request(self, mutation=False):
            host = self.headers.get('Host', '')
            expected = '127.0.0.1:{}'.format(self.server.server_port)
            if host != expected:
                self.reply({'error': 'Abre la aplicación mediante 127.0.0.1.'}, 403)
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                self.reply({'error': 'Origen no permitido.'}, 403)
                return False
            if mutation and not secrets.compare_digest(self.headers.get('X-Videoteca-Token', ''), token):
                self.reply({'error': 'Recarga la página antes de guardar.'}, 403)
                return False
            return True

        def reply(self, value, status=200, content_type='application/json; charset=utf-8'):
            body = json.dumps(value, ensure_ascii=False).encode('utf-8') if content_type.startswith('application/json') else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://i.ytimg.com https://img.youtube.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.safe_request(): return
            parsed = urlparse(self.path)
            if parsed.path == '/api/state':
                self.reply(dict(catalog.overview(), token=token, version='0.1.0', publication_dates=publication_dates.snapshot(), youtube_sync=playlist_sync.snapshot()))
            elif parsed.path == '/api/youtube/sync':
                self.reply(playlist_sync.snapshot())
            elif parsed.path == '/api/mobile':
                self.reply(self.server.mobile_access.snapshot())
            elif parsed.path == '/api/publication-dates':
                self.reply(publication_dates.snapshot())
            elif parsed.path == '/api/videos':
                self.reply(catalog.list_videos({k: v[0] for k, v in parse_qs(parsed.query).items()}))
            elif parsed.path == '/api/backup':
                self.reply(catalog.backup())
            elif parsed.path == '/api/bookmarklet':
                source = (ROOT / 'web' / 'importer.js').read_text()
                self.reply({'code': source, 'bookmarklet': 'javascript:' + quote(source, safe='')})
            elif parsed.path in {'/', '/index.html', '/app.js', '/style.css', '/importer.js', '/favicon.svg', '/guia.html', '/login.js'}:
                target = ROOT / 'web' / ('index.html' if parsed.path == '/' else parsed.path[1:])
                if target.is_file():
                    ctype = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
                    self.reply(target.read_bytes(), content_type=ctype + '; charset=utf-8')
                else: self.reply({'error': 'Archivo no encontrado.'}, 404)
            else: self.reply({'error': 'No encontrado.'}, 404)

        def mutate(self):
            if not self.safe_request(mutation=True): return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 8 * 1024 * 1024:
                    raise ImportError('El archivo está vacío o supera 8 MB.')
                if self.headers.get_content_type() != 'application/json':
                    raise ImportError('Se requiere un archivo JSON.')
                data = json.loads(self.rfile.read(size))
                path = urlparse(self.path).path
                if path == '/api/import' and self.command == 'POST':
                    result = catalog.import_data(data)
                    if automatic_dates:
                        publication_dates.start()
                    self.reply(result)
                elif path == '/api/mobile/restart' and self.command == 'POST':
                    if data != {}:
                        raise ImportError('La solicitud de acceso móvil no es válida.')
                    self.reply(self.server.mobile_access.refresh())
                elif path == '/api/publication-dates' and self.command == 'POST':
                    if not isinstance(data, dict) or set(data) - {'retry'} or type(data.get('retry', False)) is not bool:
                        raise ImportError('La solicitud de fechas no es válida.')
                    self.reply(publication_dates.start(retry=data.get('retry', False)))
                elif path == '/api/youtube/settings' and self.command == 'POST':
                    if not isinstance(data,dict) or set(data)-{'api_key','auto_sync'} or type(data.get('auto_sync')) is not bool:
                        raise ImportError('La conexión de YouTube no es válida.')
                    key=data.get('api_key',playlist_sync.settings.key())
                    self.reply(playlist_sync.configure(key,data['auto_sync']))
                elif path == '/api/youtube/sync' and self.command == 'POST':
                    if not isinstance(data,dict) or set(data)-{'automatic'} or type(data.get('automatic',False)) is not bool:
                        raise ImportError('La solicitud de actualización no es válida.')
                    self.reply(playlist_sync.start(automatic=data.get('automatic',False)))
                elif path.startswith('/api/videos/') and self.command == 'PATCH':
                    self.reply(catalog.update_video(unquote(path[len('/api/videos/'):]), data))
                else: self.reply({'error': 'No encontrado.'}, 404)
            except (ImportError, ValueError, TypeError, UnicodeError) as error:
                self.reply({'error': str(error)}, 400)
            except OSError:
                self.reply({'error': 'No se ha podido guardar la configuración local.'}, 500)

        do_POST = mutate
        do_PATCH = mutate

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.mobile_access = MobileAccess(data_dir, server.server_port)
    return server


def main():
    parser = argparse.ArgumentParser(description='Videoteca local de listas de YouTube')
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        server = make_server(args.port, args.data_dir, automatic_dates=True)
    except OSError as error:
        print('No se puede iniciar Videoteca: {}. Si ya está abierta, visita http://127.0.0.1:{}.'.format(error, args.port), flush=True)
        raise SystemExit(1)
    print('Videoteca disponible en http://127.0.0.1:{}'.format(server.server_port), flush=True)
    server.mobile_access.refresh()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.mobile_access.close()
        server.server_close()


if __name__ == '__main__': main()
