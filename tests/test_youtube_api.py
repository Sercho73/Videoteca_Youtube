import json
import tempfile
import unittest
import time
import sqlite3
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from youtubelibrary.catalog import Catalog
from test_catalog import payload


class YouTubeAPITests(unittest.TestCase):
    def client(self, request):
        from youtubelibrary.youtube_api import YouTubeAPI
        return YouTubeAPI('A'*39, request=request)

    def test_all_pages_including_more_than_fifteen_new_videos_are_imported(self):
        def request(resource, params):
            if resource=='playlists':
                return {'items':[{'id':'PLtest','snippet':{'title':'IA'},'contentDetails':{'itemCount':60}}]}
            if resource=='playlistItems':
                start,end=(50,60) if params.get('pageToken') else (0,50)
                result={'items':[{'snippet':{'position':i,'title':'Video '+str(i),'resourceId':{'videoId':str(i).zfill(11)},'videoOwnerChannelTitle':'Canal'},'contentDetails':{'videoId':str(i).zfill(11)}} for i in range(start,end)]}
                if not start: result['nextPageToken']='second'
                return result
            if resource=='videos':
                return {'items':[{'id':vid,'snippet':{'title':'Video '+vid,'channelTitle':'Canal','publishedAt':'2026-10-12T10:00:00Z'},'contentDetails':{'duration':'PT1H2M3S'}} for vid in params['id'].split(',')]}
            raise AssertionError(resource)
        result=self.client(request).playlist('PLtest')
        with tempfile.TemporaryDirectory() as directory:
            catalog=Catalog(Path(directory)/'catalog.sqlite3')
            catalog.import_data(payload())
            catalog.update_video('9YMuBrnNM-4',{'notes':'Conservar aunque ya no pertenezca a IA'})
            imported=catalog.import_data(result)
            self.assertEqual(imported['coverage'],'complete')
            self.assertEqual(catalog.list_videos({'playlist':'PLtest'})['total'],60)
            self.assertEqual(catalog.list_videos({})['videos'][-1]['id'],'00000000059')
            self.assertEqual(catalog.list_videos({})['videos'][0]['duration_seconds'],3723)
            with catalog.connect() as db:
                self.assertEqual(db.execute('SELECT notes FROM videos WHERE id=?',('9YMuBrnNM-4',)).fetchone()[0],'Conservar aunque ya no pertenezca a IA')

    def test_failed_later_page_never_returns_partial_data_for_import(self):
        from youtubelibrary.youtube_api import YouTubeAPIError
        def request(resource,params):
            if resource=='playlists': return {'items':[{'snippet':{'title':'IA'},'contentDetails':{'itemCount':60}}]}
            if params.get('pageToken'): raise YouTubeAPIError('Fallo de conexión')
            return {'items':[],'nextPageToken':'second'}
        with self.assertRaises(YouTubeAPIError): self.client(request).playlist('PLtest')

    def test_repeated_page_token_and_changed_total_are_rejected(self):
        from youtubelibrary.youtube_api import YouTubeAPIError
        def request(resource,params):
            if resource=='playlists': return {'items':[{'snippet':{'title':'IA'},'contentDetails':{'itemCount':1}}]}
            return {'items':[],'nextPageToken':'same'}
        with self.assertRaises(YouTubeAPIError): self.client(request).playlist('PLtest')

    def test_key_is_private_and_excluded_from_status_and_catalog_backup(self):
        from youtubelibrary.youtube_api import SyncSettings
        with tempfile.TemporaryDirectory() as directory:
            settings=SyncSettings(Path(directory)/'youtube-api.json')
            with self.assertRaises(ValueError): settings.save('bad key',True)
            settings.save('A'*39,True)
            self.assertTrue(settings.snapshot()['configured'])
            self.assertNotIn('A'*39,json.dumps(settings.snapshot()))
            self.assertEqual((settings.path.stat().st_mode & 0o777),0o600)
            self.assertTrue(SyncSettings(settings.path).snapshot()['auto_sync'])
            settings.save('',False)
            self.assertFalse(settings.snapshot()['configured'])

    def test_sync_keeps_failed_list_and_annotations_while_updating_other_list(self):
        from youtubelibrary.youtube_api import SyncSettings, PlaylistSync, YouTubeAPI, YouTubeAPIError
        with tempfile.TemporaryDirectory() as directory:
            catalog=Catalog(Path(directory)/'catalog.sqlite3')
            catalog.import_data(payload())
            catalog.import_data(payload(pid='PLother'))
            catalog.update_video('9YMuBrnNM-4',{'favorite':True,'notes':'Conservar nota'})
            settings=SyncSettings(Path(directory)/'settings.json');settings.save('A'*39,True)
            sync=PlaylistSync(catalog,settings)
            def remote(client,pid):
                if pid=='PLtest': raise YouTubeAPIError('Error remoto')
                return payload(pid='PLother',expected=1,rows=[payload()['videos'][0]])
            with patch.object(YouTubeAPI,'playlist',remote):
                sync.start()
                deadline=time.monotonic()+3
                while sync.snapshot()['running'] and time.monotonic()<deadline: time.sleep(.01)
            self.assertFalse(sync.snapshot()['running'])
            self.assertEqual(catalog.list_videos({'playlist':'PLtest'})['total'],2)
            self.assertEqual(catalog.list_videos({'playlist':'PLother'})['total'],1)
            video=catalog.list_videos({})['videos'][0]
            self.assertEqual(video['notes'],'Conservar nota');self.assertTrue(video['favorite'])
            self.assertEqual(sum(r['ok'] for r in sync.snapshot()['results']),1)
            previous=json.dumps(sync.snapshot()['results'])
            sync.start(automatic=True)
            self.assertFalse(sync.snapshot()['running'])
            self.assertEqual(json.dumps(sync.snapshot()['results']),previous)

    def test_settings_write_failure_does_not_leave_sync_running(self):
        from youtubelibrary.youtube_api import SyncSettings, PlaylistSync
        with tempfile.TemporaryDirectory() as directory:
            catalog=Catalog(Path(directory)/'catalog.sqlite3');catalog.import_data(payload())
            settings=SyncSettings(Path(directory)/'settings.json');settings.save('A'*39,True)
            sync=PlaylistSync(catalog,settings)
            with patch.object(settings,'update',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):sync.start()
            self.assertFalse(sync.snapshot()['running'])
            sync.configure('',False)
            self.assertFalse(sync.snapshot()['configured'])

    def test_sqlite_failure_does_not_skip_other_lists_and_results_survive_settings_failure(self):
        from youtubelibrary.youtube_api import SyncSettings, PlaylistSync, YouTubeAPI
        with tempfile.TemporaryDirectory() as directory:
            catalog=Catalog(Path(directory)/'catalog.sqlite3');catalog.import_data(payload());catalog.import_data(payload(pid='PLother'))
            settings=SyncSettings(Path(directory)/'settings.json');settings.save('A'*39,True)
            sync=PlaylistSync(catalog,settings)
            real_import=catalog.import_data
            def apply(data):
                if data['playlist']['id']=='PLtest':raise sqlite3.OperationalError('database locked SECRET')
                return real_import(data)
            def remote(client,pid):return payload(pid=pid)
            real_update=settings.update
            def save(**fields):
                if 'results' in fields and 'last_attempt' not in fields:raise OSError('disk full SECRET')
                return real_update(**fields)
            with patch.object(catalog,'import_data',apply),patch.object(YouTubeAPI,'playlist',remote),patch.object(settings,'update',save):
                sync.start()
                deadline=time.monotonic()+3
                while sync.snapshot()['running'] and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(sync.snapshot()['done'],2)
            self.assertEqual(sum(r['ok'] for r in sync.snapshot()['results']),1)
            self.assertNotIn('SECRET',json.dumps(sync.snapshot()))
            self.assertTrue(sync.snapshot()['error'])

    def test_empty_playlist_is_complete_but_count_change_cancels_import(self):
        from youtubelibrary.youtube_api import YouTubeAPIError
        counts=iter([0,1])
        def request(resource,params):
            if resource=='playlists': return {'items':[{'snippet':{'title':'IA'},'contentDetails':{'itemCount':next(counts)}}]}
            return {'items':[]}
        with self.assertRaises(YouTubeAPIError):self.client(request).playlist('PLtest')
        def empty(resource,params):
            if resource=='playlists':return {'items':[{'snippet':{'title':'IA'},'contentDetails':{'itemCount':0}}]}
            return {'items':[]}
        result=self.client(empty).playlist('PLtest')
        self.assertEqual(result['videos'],[])
        self.assertEqual(result['playlist']['expected_count'],0)

    def test_api_error_does_not_expose_key_or_google_error_text(self):
        from youtubelibrary.youtube_api import YouTubeAPI,YouTubeAPIError
        with patch('youtubelibrary.youtube_api.urlopen',side_effect=HTTPError('https://example/?key=SECRET',403,'SECRET',{},None)):
            with self.assertRaises(YouTubeAPIError) as caught: YouTubeAPI('A'*39).get('playlists',{'id':'PLtest'})
        self.assertNotIn('SECRET',str(caught.exception))
        self.assertNotIn('A'*39,str(caught.exception))


if __name__=='__main__': unittest.main()
