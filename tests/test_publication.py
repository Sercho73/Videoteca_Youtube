import unittest
import tempfile
import time
from pathlib import Path
from http.client import IncompleteRead
from unittest.mock import patch

from youtubelibrary.publication import extract_publication_date, PublicationDates, PublicationRateLimit
from youtubelibrary.catalog import Catalog
from test_catalog import payload


class PublicationTests(unittest.TestCase):
    def test_incomplete_response_leaves_video_pending_and_continues_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog=Catalog(Path(directory)/'catalog.sqlite3')
            catalog.import_data(payload())
            job=PublicationDates(catalog)
            with patch('youtubelibrary.publication.fetch_publication_date', side_effect=[IncompleteRead(b''),'2026-10-12']):
                job.start()
                deadline=time.monotonic()+3
                while job.snapshot()['running'] and time.monotonic()<deadline: time.sleep(.01)
                self.assertFalse(job.snapshot()['running'])
                self.assertEqual(job.snapshot()['done'],2)
                self.assertEqual(job.snapshot()['found'],1)
                with catalog.connect() as db:
                    self.assertEqual(db.execute('SELECT count(publication_checked_at) FROM videos').fetchone()[0],1)

    def test_rate_limit_stops_requests_without_marking_dates_as_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog=Catalog(Path(directory)/'catalog.sqlite3')
            catalog.import_data(payload())
            job=PublicationDates(catalog)
            with patch('youtubelibrary.publication.fetch_publication_date', side_effect=PublicationRateLimit) as fetch:
                job.start()
                deadline=time.monotonic()+3
                while job.snapshot()['running'] and time.monotonic()<deadline: time.sleep(.01)
                self.assertTrue(job.snapshot()['rate_limited'])
                self.assertEqual(fetch.call_count,1)
                with catalog.connect() as db:
                    self.assertEqual(db.execute('SELECT count(publication_checked_at) FROM videos').fetchone()[0],0)

    def test_worker_persists_dates_and_retries_only_missing_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog=Catalog(Path(directory)/'catalog.sqlite3')
            catalog.import_data(payload())
            job=PublicationDates(catalog)
            with patch('youtubelibrary.publication.fetch_publication_date', side_effect=lambda vid:'2026-10-12' if vid=='9YMuBrnNM-4' else None) as fetch:
                job.start()
                deadline=time.monotonic()+3
                while job.snapshot()['running'] and time.monotonic()<deadline: time.sleep(.01)
                self.assertFalse(job.snapshot()['running'])
                self.assertEqual(job.snapshot()['found'],1)
                self.assertEqual(fetch.call_count,2)
                job.start()
                self.assertEqual(fetch.call_count,2)
                job.start(retry=True)
                deadline=time.monotonic()+3
                while job.snapshot()['running'] and time.monotonic()<deadline: time.sleep(.01)
                self.assertEqual(fetch.call_count,3)
                self.assertEqual(catalog.list_videos({})['videos'][0]['published_at'],'2026-10-12')

    def test_publication_date_is_used_instead_of_upload_date(self):
        html = '<meta itemprop="datePublished" content="2026-10-12T12:17:18-07:00"><script>{"uploadDate":"2026-09-01T10:00:00Z"}</script>'
        self.assertEqual(extract_publication_date(html), '2026-10-12T12:17:18-07:00')

    def test_json_publication_date_and_calendar_validation(self):
        self.assertEqual(extract_publication_date('{"publishDate":"2026-10-12T12:17:18-07:00"}'), '2026-10-12T12:17:18-07:00')
        self.assertIsNone(extract_publication_date('{"publishDate":"2026-02-30"}'))

    def test_upload_date_and_relative_labels_are_not_publication_dates(self):
        self.assertIsNone(extract_publication_date('{"uploadDate":"2026-10-12"} hace 2 días'))


if __name__ == '__main__':
    unittest.main()
