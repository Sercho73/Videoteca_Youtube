import tempfile
import unittest
from pathlib import Path

from youtubelibrary.catalog import Catalog, ImportError, normalize_import


def payload(pid='PLtest', expected=2, rows=None):
    return {'format': 'youtube-library/v1',
            'playlist': {'id': pid, 'title': 'IA', 'expected_count': expected},
            'videos': rows if rows is not None else [
                {'id': '9YMuBrnNM-4', 'title': 'Tecnología IA', 'channel': 'Eric', 'position': 0, 'duration_seconds': 943},
                {'id': 'abcdefghijk', 'title': 'Cómo usar Claude', 'channel': 'Ejemplo', 'position': 1, 'duration_seconds': 600}]}


class ImportValidationTests(unittest.TestCase):
    def test_unavailable_video_keeps_its_id_and_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog=Catalog(Path(directory)/'catalog.sqlite3')
            catalog.import_data(payload())
            catalog.update_video('9YMuBrnNM-4',{'notes':'Conservar'})
            data=payload(); data['videos'][0]['available']=False
            catalog.import_data(data)
            video=catalog.list_videos({})['videos'][0]
            self.assertFalse(video['available'])
            self.assertEqual(video['notes'],'Conservar')

    def test_coverage_requires_contiguous_positions_and_count(self):
        self.assertEqual(normalize_import(payload())['coverage'], 'complete')
        p = payload(); p['videos'][1]['position'] = 3
        self.assertEqual(normalize_import(p)['coverage'], 'partial')
        p['playlist']['expected_count'] = None
        self.assertEqual(normalize_import(p)['coverage'], 'unverified')

    def test_reject_duplicate_position_and_bad_video_id(self):
        p = payload(); p['videos'][1]['position'] = 0
        with self.assertRaises(ImportError): normalize_import(p)
        p = payload(); p['videos'][0]['id'] = '../../secret'
        with self.assertRaises(ImportError): normalize_import(p)

    def test_unavailable_entry_is_preserved(self):
        p = payload(rows=[{'id': None, 'position': 0, 'title': 'Vídeo privado'}], expected=1)
        normalized = normalize_import(p)
        self.assertFalse(normalized['videos'][0]['available'])
        self.assertEqual(normalized['coverage'], 'complete')


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Catalog(Path(self.tmp.name) / 'catalog.sqlite3')

    def tearDown(self): self.tmp.cleanup()

    def test_multi_playlist_search_deduplicates_and_retains_memberships(self):
        self.db.import_data(payload())
        other = payload(pid='PLother', expected=1, rows=payload()['videos'][:1])
        self.db.import_data(other)
        result = self.db.list_videos({})
        self.assertEqual(len(result['videos']), 2)
        self.assertEqual(result['appearance_count'], 3)
        match = self.db.list_videos({'q': 'tecnologia'})['videos']
        self.assertEqual(len(match), 1)
        self.assertEqual(len(match[0]['playlists']), 2)

    def test_reimport_preserves_user_annotations_and_updates_metadata(self):
        self.db.import_data(payload())
        self.db.update_video('9YMuBrnNM-4', {'status': 'watched', 'favorite': True, 'tags': ['Claude'], 'notes': 'Probar el ejemplo'})
        p = payload(); p['videos'][0]['title'] = 'Título actualizado'
        self.db.import_data(p)
        video = self.db.list_videos({'q': 'actualizado'})['videos'][0]
        self.assertEqual(video['status'], 'watched')
        self.assertEqual(video['tags'], ['Claude'])
        self.assertEqual(video['notes'], 'Probar el ejemplo')
        self.assertTrue(video['favorite'])
        reopened = Catalog(Path(self.tmp.name) / 'catalog.sqlite3')
        self.assertEqual(reopened.list_videos({'status': 'watched'})['total'], 1)

    def test_partial_import_does_not_remove_old_entries(self):
        self.db.import_data(payload())
        p = payload(rows=payload()['videos'][:1])
        imported = self.db.import_data(p)
        self.assertEqual(imported['coverage'], 'partial')
        self.assertEqual(self.db.list_videos({})['total'], 2)
        self.assertEqual(self.db.overview()['playlists'][0]['last_collected_count'], 1)

    def test_partial_prepend_retains_unseen_previous_memberships(self):
        self.db.import_data(payload())
        new = {'id': 'newvideo123', 'title': 'Nuevo', 'channel': 'Ejemplo', 'position': 0}
        self.db.import_data(payload(expected=3, rows=[new]))
        self.assertEqual(self.db.list_videos({'playlist':'PLtest'})['total'], 3)

    def test_partial_prepend_shows_new_video_first_without_losing_previous_entries(self):
        self.db.import_data(payload())
        self.db.update_video('abcdefghijk', {'notes': 'Conservar nota'})
        new = {'id': 'newvideo123', 'title': 'Nuevo', 'channel': 'Ejemplo', 'position': 0}
        self.db.import_data(payload(expected=None, rows=[new, dict(payload()['videos'][0], position=1)]))
        result = self.db.list_videos({'playlist': 'PLtest'})
        self.assertEqual([v['id'] for v in result['videos']], ['newvideo123', '9YMuBrnNM-4', 'abcdefghijk'])
        self.assertEqual(result['videos'][-1]['notes'], 'Conservar nota')
        self.assertEqual(result['appearance_count'], 3)

    def test_video_title_from_legacy_export_does_not_rename_playlist(self):
        self.db.import_data(payload())
        broken = payload()
        broken['playlist']['title'] = broken['videos'][0]['title']
        self.db.import_data(broken)
        self.assertEqual(self.db.overview()['playlists'][0]['title'], 'IA')

    def test_verified_playlist_title_can_match_video_title(self):
        self.db.import_data(payload())
        renamed = payload()
        renamed['playlist'].update(title=renamed['videos'][0]['title'], title_verified=True)
        self.db.import_data(renamed)
        self.assertEqual(self.db.overview()['playlists'][0]['title'], renamed['playlist']['title'])

    def test_unverified_title_preserves_existing_name(self):
        self.db.import_data(payload())
        unknown = payload()
        unknown['playlist'].update(title='Nombre dudoso', title_verified=False)
        self.db.import_data(unknown)
        self.assertEqual(self.db.overview()['playlists'][0]['title'], 'IA')

    def test_publication_sort_respects_timezone_offsets(self):
        p=payload()
        p['videos'][0]['published_at']='2026-10-12T12:00:00-07:00'
        p['videos'][1]['published_at']='2026-10-12T18:00:00Z'
        self.db.import_data(p)
        self.assertEqual(self.db.list_videos({'sort':'published_desc'})['videos'][0]['id'],'9YMuBrnNM-4')

    def test_missing_metadata_on_reimport_preserves_known_values_across_lists(self):
        known = payload()
        known['videos'][0]['thumbnail_url'] = 'https://i.ytimg.com/vi/9YMuBrnNM-4/mqdefault.jpg'
        self.db.import_data(known)
        self.db.import_data(payload(pid='PLother', expected=1, rows=known['videos'][:1]))
        for expected in (3, None, 1):
            with self.subTest(expected=expected):
                incomplete = dict(known['videos'][0], title='Título nuevo', channel='',
                                  duration_seconds=None, thumbnail_url='')
                self.db.import_data(payload(expected=expected, rows=[incomplete]))
                match = self.db.list_videos({'playlist': 'PLother', 'channel': 'Eric', 'max_duration': '1000'})
                self.assertEqual(match['total'], 1)
                video = match['videos'][0]
                self.assertEqual(video['title'], 'Título nuevo')
                self.assertEqual(video['duration_seconds'], 943)
                self.assertEqual(video['thumbnail_url'], known['videos'][0]['thumbnail_url'])

    def test_complete_import_removes_only_membership(self):
        self.db.import_data(payload())
        self.db.import_data(payload(pid='PLother'))
        self.db.import_data(payload(expected=1, rows=payload()['videos'][:1]))
        self.assertEqual(self.db.list_videos({'playlist': 'PLtest'})['total'], 1)
        self.assertEqual(self.db.list_videos({})['total'], 2)

    def test_duplicates_are_counted_but_shown_once(self):
        row = payload()['videos'][0]
        self.db.import_data(payload(rows=[row, dict(row, position=1)]))
        result = self.db.list_videos({})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['appearance_count'], 2)

    def test_combined_filters_search_notes_and_accent_fold(self):
        self.db.import_data(payload())
        self.db.update_video('abcdefghijk', {'tags': ['Agentes'], 'favorite': True, 'notes': 'automatización'})
        result = self.db.list_videos({'q': 'automatizacion', 'tag': 'Agentes', 'favorite': '1', 'max_duration': '900'})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['videos'][0]['id'], 'abcdefghijk')

    def test_channel_options_follow_playlist_without_other_filters(self):
        self.db.import_data(payload())
        other = {'id': 'newvideo123', 'title': 'Coctel', 'channel': 'Barman', 'position': 0}
        self.db.import_data(payload(pid='PLother', expected=1, rows=[other]))
        self.assertEqual(self.db.list_videos({'playlist': 'PLother'})['channels'], ['Barman'])
        self.assertEqual(self.db.list_videos({'playlist': 'PLtest', 'q': 'ninguno', 'channel': 'Eric'})['channels'], ['Ejemplo', 'Eric'])
        self.assertEqual(self.db.list_videos({})['channels'], ['Barman', 'Ejemplo', 'Eric'])

    def test_minimum_duration_is_strict_and_excludes_unknown(self):
        rows = [dict(payload()['videos'][0], duration_seconds=3600),
                dict(payload()['videos'][1], duration_seconds=7201),
                {'id': 'newvideo123', 'title': 'Largo', 'position': 2, 'duration_seconds': 10801},
                {'id': 'unknown1234', 'title': 'Desconocido', 'position': 3}]
        self.db.import_data(payload(expected=4, rows=rows))
        for boundary, expected in [('3600', 2), ('7200', 2), ('10800', 1)]:
            with self.subTest(boundary=boundary):
                self.assertEqual(self.db.list_videos({'min_duration': boundary})['total'], expected)

    def test_reverse_sorts_and_unknown_duration_last(self):
        rows = [dict(payload()['videos'][0], title='Árbol', duration_seconds=3600),
                dict(payload()['videos'][1], title='Zorro', duration_seconds=7200),
                {'id': 'newvideo123', 'title': 'Medio', 'position': 2}]
        self.db.import_data(payload(expected=3, rows=rows))
        self.assertEqual([v['title'] for v in self.db.list_videos({'sort': 'title_desc'})['videos']], ['Zorro', 'Medio', 'Árbol'])
        self.assertEqual([v['duration_seconds'] for v in self.db.list_videos({'sort': 'duration_desc'})['videos']], [7200, 3600, None])

    def test_invalid_import_is_atomic(self):
        self.db.import_data(payload())
        p = payload(); p['videos'][1]['position'] = -1
        with self.assertRaises(ImportError): self.db.import_data(p)
        self.assertEqual(self.db.list_videos({})['total'], 2)

    def test_publication_dates_survive_reimport_and_sort_with_unknown_last(self):
        p = payload(expected=3)
        p['videos'][0]['published_at'] = '2026-10-12T12:17:18-07:00'
        p['videos'][1]['published_at'] = '2026-09-01'
        p['videos'].append({'id': 'newvideo123', 'title': 'Sin fecha', 'position': 2})
        self.db.import_data(p)
        self.db.import_data(payload())
        # The third video stays in another list while the complete reimport replaces PLtest.
        self.db.import_data(payload(pid='PLunknown', expected=1, rows=[p['videos'][2]]))
        desc = self.db.list_videos({'sort': 'published_desc'})['videos']
        asc = self.db.list_videos({'sort': 'published_asc'})['videos']
        self.assertEqual([v['id'] for v in desc], ['9YMuBrnNM-4', 'abcdefghijk', 'newvideo123'])
        self.assertEqual([v['id'] for v in asc], ['abcdefghijk', '9YMuBrnNM-4', 'newvideo123'])
        self.assertEqual(desc[0]['published_at'], p['videos'][0]['published_at'])


if __name__ == '__main__': unittest.main()
