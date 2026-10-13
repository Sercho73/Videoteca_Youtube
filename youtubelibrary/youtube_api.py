"""Read complete public/unlisted playlists using YouTube Data API v3."""
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .catalog import normalize_import
from .publication import valid_publication_date


class YouTubeAPIError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class SyncSettings:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {'api_key':'', 'auto_sync':True, 'last_attempt':None, 'last_success':None, 'results':[]}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text()))

    def snapshot(self):
        with self.lock:
            return {k:v for k,v in self.data.items() if k != 'api_key'} | {'configured':bool(self.data['api_key'])}

    def key(self):
        with self.lock:
            return self.data['api_key']

    def update(self, **fields):
        with self.lock:
            data=dict(self.data, **fields)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.youtube-api-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(data, stream, ensure_ascii=False)
                os.replace(name, self.path)
                self.data=data
            finally:
                if os.path.exists(name): os.unlink(name)

    def save(self, key, auto_sync):
        if not isinstance(key,str) or (key and not re.fullmatch(r'[A-Za-z0-9_-]{20,200}',key)) or type(auto_sync) is not bool:
            raise YouTubeAPIError('Revisa que hayas copiado la clave API completa, sin espacios.')
        self.update(api_key=key, auto_sync=auto_sync, last_attempt=None, results=[])


def duration_seconds(value):
    match=re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?',value or '')
    if not match: return None
    days,hours,minutes,seconds=(int(v or 0) for v in match.groups())
    result=days*86400+hours*3600+minutes*60+seconds
    return result if result<=604800 else None


class YouTubeAPI:
    def __init__(self, key, request=None):
        self.api_key=key
        self.request=request or self.get

    def get(self, resource, params):
        if resource not in {'playlists','playlistItems','videos'}:
            raise YouTubeAPIError('Consulta de YouTube no válida.')
        url='https://www.googleapis.com/youtube/v3/'+resource+'?'+urlencode(dict(params,key=self.api_key))
        try:
            with urlopen(Request(url,headers={'Accept':'application/json'}), timeout=20) as response:
                value=json.loads(response.read(8*1024*1024))
            if not isinstance(value,dict) or 'error' in value: raise YouTubeAPIError('YouTube ha rechazado la consulta.')
            return value
        except HTTPError as error:
            messages={400:'YouTube ha rechazado la consulta. Revisa la clave API.',
                      401:'La clave API no es válida.',
                      403:'YouTube ha rechazado el acceso. Revisa la clave, la activación de YouTube Data API v3, sus restricciones y la cuota.',
                      404:'La lista no está disponible. Comprueba que siga pública u oculta.',
                      429:'YouTube ha limitado las consultas. Reintenta más tarde.'}
            raise YouTubeAPIError(messages.get(error.code,'YouTube no responde correctamente. Reintenta más tarde.')) from None
        except (OSError, HTTPException, ValueError) as error:
            if isinstance(error,YouTubeAPIError): raise
            raise YouTubeAPIError('No se ha podido consultar YouTube. Reintenta más tarde.') from None

    def metadata(self, pid):
        result=self.request('playlists',{'part':'snippet,contentDetails','id':pid})
        items=result.get('items',[])
        if len(items)!=1: raise YouTubeAPIError('La lista no está disponible. Comprueba que siga pública u oculta.')
        title=items[0].get('snippet',{}).get('title')
        total=items[0].get('contentDetails',{}).get('itemCount')
        if not isinstance(title,str) or type(total) is not int or not 0<=total<=10000:
            raise YouTubeAPIError('YouTube no ha devuelto un contador de lista válido.')
        return title,total

    def playlist(self, pid):
        if not re.fullmatch(r'[A-Za-z0-9_-]{2,160}',pid): raise YouTubeAPIError('Identificador de lista no válido.')
        title,expected=self.metadata(pid)
        rows=[]; page=''; seen=set()
        while True:
            params={'part':'snippet,contentDetails','playlistId':pid,'maxResults':50}
            if page: params['pageToken']=page
            response=self.request('playlistItems',params)
            items=response.get('items')
            if not isinstance(items,list): raise YouTubeAPIError('YouTube ha devuelto una página de lista no válida.')
            for item in items:
                snippet=item.get('snippet',{}); details=item.get('contentDetails',{})
                vid=details.get('videoId') or snippet.get('resourceId',{}).get('videoId')
                rows.append({'id':vid,'position':snippet.get('position'),'title':snippet.get('title') or 'Vídeo no disponible',
                             'channel':snippet.get('videoOwnerChannelTitle') or '',
                             'published_at':valid_publication_date(details.get('videoPublishedAt'))})
            if len(rows)>10000: raise YouTubeAPIError('La lista supera el máximo de 10.000 elementos del piloto.')
            page=response.get('nextPageToken')
            if not page: break
            if not isinstance(page,str) or page in seen or len(seen)>=200:
                raise YouTubeAPIError('YouTube ha repetido una página. Se conserva la lista anterior.')
            seen.add(page)
        # Validate all pages before retrieving details or changing the local catalog.
        result={'format':'youtube-library/v1','playlist':{'id':pid,'title':title,'title_verified':True,'expected_count':expected},'videos':rows}
        if normalize_import(result)['coverage']!='complete':
            raise YouTubeAPIError('YouTube no ha devuelto la lista completa. Se conserva la lista anterior.')
        ids=list(dict.fromkeys(r['id'] for r in rows if r['id']))
        details={}
        for offset in range(0,len(ids),50):
            response=self.request('videos',{'part':'snippet,contentDetails','id':','.join(ids[offset:offset+50])})
            if not isinstance(response.get('items'),list): raise YouTubeAPIError('YouTube no ha devuelto los detalles de vídeo.')
            details.update({v['id']:v for v in response['items']})
        for row in rows:
            video=details.get(row['id']); row['available']=bool(video)
            if video:
                snippet=video.get('snippet',{})
                row.update(title=snippet.get('title') or row['title'],channel=snippet.get('channelTitle') or row['channel'],
                           published_at=valid_publication_date(snippet.get('publishedAt')) or row['published_at'],
                           duration_seconds=duration_seconds(video.get('contentDetails',{}).get('duration')),
                           thumbnail_url='https://i.ytimg.com/vi/'+row['id']+'/mqdefault.jpg')
        if self.metadata(pid)[1]!=expected:
            raise YouTubeAPIError('La lista ha cambiado durante la consulta. Se conserva la anterior; vuelve a actualizar.')
        return result


class PlaylistSync:
    def __init__(self, catalog, settings):
        self.catalog=catalog; self.settings=settings; self.lock=threading.Lock()
        self.state={'running':False,'current':'','done':0,'total':0,'error':'','results':settings.snapshot()['results']}

    def snapshot(self):
        with self.lock:
            return dict(self.settings.snapshot(), **self.state)

    def configure(self, key, auto_sync):
        with self.lock:
            if self.state['running']: raise YouTubeAPIError('Espera a que termine la actualización antes de cambiar la conexión.')
            self.settings.save(key,auto_sync)
            self.state.update(results=[],error='')
        return self.snapshot()

    def start(self, automatic=False):
        with self.lock:
            config=self.settings.snapshot()
            if self.state['running']: return dict(config,**self.state)
            if not config['configured']:
                if automatic: return dict(config,**self.state)
                raise YouTubeAPIError('Conecta YouTube con una clave API antes de actualizar.')
            if automatic:
                if not config['auto_sync']: return dict(config,**self.state)
                last=config['last_attempt']
                if last and (datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()<3600:
                    return dict(config,**self.state)
            playlists=self.catalog.overview()['playlists']
            if playlists:
                self.settings.update(last_attempt=utc_now(),results=[])
                self.state={'running':True,'current':'','done':0,'total':len(playlists),'error':'','results':[]}
                key=self.settings.key()
                try:
                    threading.Thread(target=self.run,args=(playlists,key),daemon=True).start()
                except RuntimeError:
                    self.state['running']=False
                    raise YouTubeAPIError('No se pudo iniciar la actualización. Reintenta más tarde.') from None
            return dict(self.settings.snapshot(),**self.state)

    def run(self, playlists, key):
        results=[]
        try:
            client=YouTubeAPI(key)
            for playlist in playlists:
                with self.lock: self.state['current']=playlist['title']
                try:
                    data=client.playlist(playlist['id'])
                    imported=self.catalog.import_data(data)
                    results.append({'id':playlist['id'],'title':imported['title'],'ok':True,'count':imported['count'],'at':utc_now()})
                except Exception as error:
                    # Do not expose third-party URLs, keys, or response bodies.
                    message=str(error) if isinstance(error,YouTubeAPIError) else 'No se pudo actualizar la lista. Se conserva el catálogo anterior.'
                    results.append({'id':playlist['id'],'title':playlist['title'],'ok':False,'error':message})
                with self.lock:
                    self.state['done']+=1
                    self.state['results']=list(results)
            fields={'results':results}
            if all(r['ok'] for r in results): fields['last_success']=utc_now()
            self.settings.update(**fields)
        except OSError:
            with self.lock:
                self.state['error']='No se pudo guardar el estado de la conexión. Los resultados de esta sesión siguen visibles.'
        finally:
            with self.lock: self.state['running']=False; self.state['current']=''
