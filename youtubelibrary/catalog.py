import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .publication import valid_publication_date


class ImportError(ValueError):
    pass


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value).casefold()) if not unicodedata.combining(c))


def text(value, limit=1000):
    return str(value or '').strip()[:limit]


def normalize_import(data):
    if not isinstance(data, dict) or data.get('format') != 'youtube-library/v1':
        raise ImportError('El archivo no tiene el formato del importador de Videoteca.')
    playlist = data.get('playlist')
    if not isinstance(playlist, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{2,160}', str(playlist.get('id', ''))):
        raise ImportError('No se reconoce el identificador de la lista.')
    pid = playlist['id']
    rows = data.get('videos')
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ImportError('Se admite una lista de hasta 10.000 elementos por archivo.')
    expected = playlist.get('expected_count')
    if expected is not None and (type(expected) is not int or not 0 <= expected <= 10000):
        raise ImportError('El contador esperado no es válido.')
    videos, positions = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ImportError('Hay una entrada de vídeo no válida.')
        pos = row.get('position')
        if type(pos) is not int or not 0 <= pos < 10000 or pos in positions:
            raise ImportError('Hay posiciones repetidas o no válidas. Vuelve a exportar la lista.')
        positions.add(pos)
        vid = row.get('id')
        if vid is not None and not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(vid)):
            raise ImportError('Hay un identificador de vídeo no válido.')
        duration = row.get('duration_seconds')
        if duration is not None and (type(duration) is not int or not 0 <= duration <= 604800):
            raise ImportError('Hay una duración no válida.')
        published_at = row.get('published_at')
        if published_at is not None and not valid_publication_date(published_at):
            raise ImportError('Hay una fecha de publicación no válida.')
        available = row.get('available', bool(vid))
        if type(available) is not bool or (available and not vid):
            raise ImportError('La disponibilidad del vídeo no es válida.')
        thumb = text(row.get('thumbnail_url'), 1000)
        parsed = urlparse(thumb)
        if parsed.scheme != 'https' or parsed.hostname not in {'i.ytimg.com', 'img.youtube.com'}:
            thumb = ''
        videos.append({'id': vid or 'missing:{}:{}'.format(pid, pos), 'position': pos,
                       'title': text(row.get('title')) or 'Vídeo no disponible',
                       'channel': text(row.get('channel'), 300), 'duration_seconds': duration,
                       'thumbnail_url': thumb, 'available': available, 'published_at': published_at})
    coverage = 'unverified' if expected is None else (
        'complete' if len(videos) == expected and positions == set(range(expected)) else 'partial')
    title = text(playlist.get('title'), 300)
    title_verified = playlist.get('title_verified')
    if title_verified is None:
        title_verified = bool(title) and title not in {v['title'] for v in videos}
    elif type(title_verified) is not bool:
        raise ImportError('La verificación del nombre de la lista no es válida.')
    return {'id': pid, 'title': title or 'Lista de YouTube', 'title_verified': bool(title) and title_verified,
            'expected_count': expected, 'coverage': coverage, 'videos': videos,
            'source_url': 'https://www.youtube.com/playlist?list=' + pid}


class Catalog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS playlists (
                    id TEXT PRIMARY KEY, title TEXT, source_url TEXT,
                    expected_count INTEGER, last_collected_count INTEGER,
                    coverage TEXT, imported_at TEXT);
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY, title TEXT, channel TEXT, duration_seconds INTEGER,
                    thumbnail_url TEXT, available INTEGER, status TEXT DEFAULT 'pending',
                    favorite INTEGER DEFAULT 0, tags TEXT DEFAULT '[]', notes TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS items (
                    playlist_id TEXT REFERENCES playlists(id), position INTEGER,
                    video_id TEXT REFERENCES videos(id), PRIMARY KEY(playlist_id, position));
                CREATE INDEX IF NOT EXISTS items_video ON items(video_id);
            ''')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(videos)')}
            for column in ('published_at', 'publication_checked_at'):
                if column not in columns:
                    db.execute('ALTER TABLE videos ADD COLUMN ' + column + ' TEXT')
        self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def import_data(self, data):
        normalized = normalize_import(data)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('''INSERT INTO playlists VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=CASE WHEN ? THEN excluded.title ELSE playlists.title END,
                source_url=excluded.source_url,
                expected_count=excluded.expected_count,last_collected_count=excluded.last_collected_count,
                coverage=excluded.coverage,imported_at=excluded.imported_at''',
                       (normalized['id'], normalized['title'] if normalized['title_verified'] else 'Lista de YouTube', normalized['source_url'],
                        normalized['expected_count'], len(normalized['videos']), normalized['coverage'], now,
                        normalized['title_verified']))
            existing = db.execute('SELECT video_id FROM items WHERE playlist_id=? ORDER BY position', (normalized['id'],)).fetchall()
            incoming = sorted(normalized['videos'], key=lambda v: v['position'])
            membership = [v['id'] for v in incoming]
            if normalized['coverage'] != 'complete':
                remaining = Counter(membership)
                for row in existing:
                    if remaining[row['video_id']]:
                        remaining[row['video_id']] -= 1
                    else:
                        membership.append(row['video_id'])
            for v in normalized['videos']:
                db.execute('''INSERT INTO videos(id,title,channel,duration_seconds,thumbnail_url,available,published_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                    channel=COALESCE(NULLIF(excluded.channel,''),videos.channel),
                    duration_seconds=COALESCE(excluded.duration_seconds,videos.duration_seconds),
                    thumbnail_url=COALESCE(NULLIF(excluded.thumbnail_url,''),videos.thumbnail_url),
                    available=excluded.available,published_at=COALESCE(excluded.published_at,videos.published_at)''',
                           (v['id'], v['title'], v['channel'], v['duration_seconds'], v['thumbnail_url'], v['available'], v['published_at']))
            db.execute('DELETE FROM items WHERE playlist_id=?', (normalized['id'],))
            db.executemany('INSERT INTO items VALUES(?,?,?)',
                           [(normalized['id'], pos, vid) for pos, vid in enumerate(membership)])
            actual_title = db.execute('SELECT title FROM playlists WHERE id=?', (normalized['id'],)).fetchone()['title']
        return {'title': actual_title, 'count': len(normalized['videos']),
                'expected_count': normalized['expected_count'], 'coverage': normalized['coverage'], 'id': normalized['id']}

    def overview(self):
        with self.connect() as db:
            playlists = [dict(r) for r in db.execute('''SELECT p.*,COUNT(i.position) AS item_count,
                COUNT(DISTINCT i.video_id) AS unique_count FROM playlists p
                LEFT JOIN items i ON i.playlist_id=p.id GROUP BY p.id ORDER BY p.title COLLATE NOCASE''')]
            rows = db.execute('SELECT DISTINCT v.* FROM videos v JOIN items i ON i.video_id=v.id').fetchall()
        tags = sorted({tag for r in rows for tag in json.loads(r['tags'])}, key=fold)
        channels = sorted({r['channel'] for r in rows if r['channel']}, key=fold)
        return {'playlists': playlists, 'total': len(rows), 'favorites': sum(bool(r['favorite']) for r in rows),
                'channels': channels, 'tags': tags}

    def list_videos(self, params):
        with self.connect() as db:
            items = db.execute('''SELECT i.*,p.title AS playlist_title,p.source_url
                FROM items i JOIN playlists p ON p.id=i.playlist_id ORDER BY i.position''').fetchall()
            all_videos = db.execute('SELECT * FROM videos').fetchall()
        memberships, selected = {}, {}
        for row in items:
            memberships.setdefault(row['video_id'], {})[row['playlist_id']] = {
                'id': row['playlist_id'], 'title': row['playlist_title'], 'url': row['source_url']}
            if not params.get('playlist') or row['playlist_id'] == params['playlist']:
                selected[row['video_id']] = min(selected.get(row['video_id'], 10000), row['position'])
        channels = sorted({r['channel'] for r in all_videos if r['id'] in selected and r['channel']}, key=fold)
        query = fold(params.get('q', ''))
        result = []
        for row in all_videos:
            if row['id'] not in selected:
                continue
            v = dict(row)
            v['tags'] = json.loads(v['tags'])
            v['favorite'], v['available'] = bool(v['favorite']), bool(v['available'])
            v['playlists'] = list(memberships.get(v['id'], {}).values())
            v['position'] = selected[v['id']]
            if query and not all(word in fold(' '.join([v['title'], v['channel'], v['notes']] + v['tags'])) for word in query.split()):
                continue
            if params.get('channel') and v['channel'] != params['channel']:
                continue
            if params.get('status') and v['status'] != params['status']:
                continue
            if params.get('tag') and params['tag'] not in v['tags']:
                continue
            if params.get('favorite') == '1' and not v['favorite']:
                continue
            if params.get('max_duration'):
                try: maximum = int(params['max_duration'])
                except ValueError: maximum = 0
                if v['duration_seconds'] is None or v['duration_seconds'] > maximum:
                    continue
            if params.get('min_duration'):
                try: minimum = int(params['min_duration'])
                except ValueError: minimum = 0
                if v['duration_seconds'] is None or v['duration_seconds'] <= minimum:
                    continue
            result.append(v)
        sort = params.get('sort', 'position')
        if sort in {'title', 'title_desc'}: result.sort(key=lambda v: fold(v['title']), reverse=sort == 'title_desc')
        elif sort in {'duration', 'duration_desc'}:
            result.sort(key=lambda v: (v['duration_seconds'] is None, -(v['duration_seconds'] or 0) if sort == 'duration_desc' else (v['duration_seconds'] or 0)))
        elif sort in {'published_desc', 'published_asc'}:
            def publication_key(v):
                value = datetime.fromisoformat(v['published_at'].replace('Z', '+00:00')) if v['published_at'] else None
                stamp = (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp() if value else 0
                return (not bool(v['published_at']), -stamp if sort == 'published_desc' else stamp)
            result.sort(key=publication_key)
        else: result.sort(key=lambda v: (v['position'], fold(v['title'])))
        ids = {v['id'] for v in result}
        appearances = sum(1 for r in items if r['video_id'] in ids and (not params.get('playlist') or r['playlist_id'] == params['playlist']))
        return {'videos': result, 'total': len(result), 'appearance_count': appearances, 'channels': channels}

    def update_video(self, vid, data):
        allowed = {'status', 'favorite', 'tags', 'notes'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise ImportError('Los campos de la anotación no son válidos.')
        values = {}
        if 'status' in data:
            if data['status'] not in {'pending', 'watched', 'review'}:
                raise ImportError('Estado no válido.')
            values['status'] = data['status']
        if 'favorite' in data:
            if type(data['favorite']) is not bool: raise ImportError('Favorito no válido.')
            values['favorite'] = int(data['favorite'])
        if 'notes' in data:
            values['notes'] = text(data['notes'], 20000)
        if 'tags' in data:
            if not isinstance(data['tags'], list) or len(data['tags']) > 50:
                raise ImportError('Se admiten hasta 50 etiquetas por vídeo.')
            values['tags'] = json.dumps(list(dict.fromkeys(text(t, 80) for t in data['tags'] if text(t, 80))), ensure_ascii=False)
        if values:
            with self.connect() as db:
                cur = db.execute('UPDATE videos SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?', tuple(values.values()) + (vid,))
                if cur.rowcount != 1: raise ImportError('Ese vídeo ya no está en el catálogo.')
        return {'ok': True}

    def backup(self):
        with self.connect() as db:
            return {'format': 'youtube-library-backup/v1', 'exported_at': datetime.now(timezone.utc).isoformat(),
                    'playlists': [dict(r) for r in db.execute('SELECT * FROM playlists')],
                    'videos': [dict(r) for r in db.execute('SELECT * FROM videos')],
                    'items': [dict(r) for r in db.execute('SELECT * FROM items')]}
