"""Read public publication dates, without credentials or a YouTube API key."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPException
import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class PublicationRateLimit(Exception):
    pass


def valid_publication_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T[0-9:.]+(?:Z|[+-]\d{2}:\d{2}))?', value):
        return None
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value
    except ValueError:
        return None


class PublicationMeta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.value = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('itemprop') == 'datePublished':
            self.value = valid_publication_date(attrs.get('content'))


def extract_publication_date(html):
    parser = PublicationMeta()
    parser.feed(html)
    if parser.value:
        return parser.value
    match = re.search(r'"publishDate"\s*:\s*"([^"\\]+)"', html)
    return valid_publication_date(match.group(1)) if match else None


def fetch_publication_date(vid):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
        return None
    request = Request('https://www.youtube.com/watch?v=' + vid,
                      headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'es-ES,es;q=0.9'})
    try:
        with urlopen(request, timeout=15) as response:
            html = response.read(6 * 1024 * 1024).decode('utf-8', errors='replace')
        return extract_publication_date(html)
    except HTTPError as error:
        if error.code == 429:
            raise PublicationRateLimit()
        return None
    except (OSError, ValueError):
        return None


class PublicationDates:
    def __init__(self, catalog):
        self.catalog = catalog
        self.lock = threading.Lock()
        self.pending = False
        self.state = {'running': False, 'done': 0, 'total': 0, 'found': 0, 'rate_limited': False}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, retry=False):
        with self.lock:
            if self.state['running']:
                self.pending = True
                return dict(self.state)
            with self.catalog.connect() as db:
                ids = [r['id'] for r in db.execute('''SELECT DISTINCT v.id FROM videos v JOIN items i ON v.id=i.video_id
                    WHERE v.published_at IS NULL AND v.available=1''' + ('' if retry else ' AND v.publication_checked_at IS NULL'))
                       if re.fullmatch(r'[A-Za-z0-9_-]{11}', r['id'])]
            self.state = {'running': bool(ids), 'done': 0, 'total': len(ids), 'found': 0, 'rate_limited': False}
            if ids:
                self.pending = False
                threading.Thread(target=self.run, args=(ids,), daemon=True).start()
            return dict(self.state)

    def run(self, ids):
        try:
            for index, vid in enumerate(ids):
                if index:
                    time.sleep(1)
                try:
                    value = fetch_publication_date(vid)
                except PublicationRateLimit:
                    with self.lock:
                        self.state['rate_limited'] = True
                    break
                except HTTPException:
                    with self.lock:
                        self.state['done'] += 1
                    continue
                with self.catalog.connect() as db:
                    db.execute('''UPDATE videos SET published_at=COALESCE(?,published_at),publication_checked_at=? WHERE id=?''',
                               (value, datetime.now(timezone.utc).isoformat(), vid))
                with self.lock:
                    self.state['done'] += 1
                    self.state['found'] += int(value is not None)
        finally:
            with self.lock:
                self.state['running'] = False
                pending = self.pending and not self.state['rate_limited']
                self.pending = False
        if pending:
            self.start()
