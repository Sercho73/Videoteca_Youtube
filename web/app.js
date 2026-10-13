'use strict';
const $ = id => document.getElementById(id);
let state = {playlists: [], channels: [], tags: []};
let playlist = '', favorite = false, token = '', currentVideos = [], editing = null, requestNumber = 0;
let importer = null;
let dateTimer;
function showDateProgress(job) {
  clearTimeout(dateTimer);
  $('update-dates').disabled=!!job.running || !state.total;
  $('date-progress').textContent=job.running?'Consultando fechas: '+job.done+' de '+job.total:job.rate_limited?'YouTube ha limitado las consultas. Puedes reintentar más tarde.':job.total?'Fechas recuperadas: '+job.found+' de '+job.total:'';
  if(job.running) dateTimer=setTimeout(async()=>{try{const next=await api('/api/publication-dates');showDateProgress(next);if(!next.running)await refreshView();}catch(error){toast(error.message,true);$('update-dates').disabled=false;}},1500);
}
let syncTimer;
function showSync(job) {
  state.youtube_sync=job;
  clearTimeout(syncTimer);
  $('youtube-connect').textContent=job.configured?'Conexión YouTube':'Conectar YouTube';
  $('youtube-connect').disabled=!!job.running;
  $('youtube-update').disabled=!!job.running || !job.configured || !state.playlists.length;
  $('youtube-progress').classList.remove('error');
  if(job.running) $('youtube-progress').textContent='Actualizando '+job.current+' · '+job.done+' de '+job.total+' listas';
  else if(!job.configured) $('youtube-progress').textContent='Conecta YouTube para actualizar tus listas completas.';
  else if(job.results.length || job.error) {
    $('youtube-progress').textContent=job.results.map(r=>r.ok?r.title+': '+r.count+' elementos actualizados':r.title+': '+r.error).join(' · ')+(job.error?' · '+job.error:'');
    $('youtube-progress').classList.toggle('error',!!job.error || job.results.some(r=>!r.ok));
  } else $('youtube-progress').textContent=job.auto_sync?'Actualización automática al abrir activada':'Actualización manual';
  if(job.running) syncTimer=setTimeout(async()=>{try{const next=await api('/api/youtube/sync');showSync(next);if(!next.running){await refreshState();await refreshView();}}catch(error){toast(error.message,true);$('youtube-connect').disabled=false;$('youtube-update').disabled=false;}},1200);
}
async function updateYouTube(automatic=false) {
  try{showSync(await api('/api/youtube/sync',{method:'POST',body:JSON.stringify({automatic})}));}catch(error){toast(error.message,true);}
}
function openYouTube() {
  const job=state.youtube_sync;
  $('youtube-key').value='';
  $('youtube-key').required=!job.configured;
  $('youtube-key').placeholder=job.configured?'Deja vacío para conservar tu clave':'Pega aquí tu clave API';
  $('youtube-auto').checked=job.auto_sync;
  $('youtube-disconnect').hidden=!job.configured;
  $('youtube-error').textContent='';
  $('youtube-dialog').showModal();
}
const STATUS = {pending:'Pendiente', watched:'Visto', review:'Revisar'};
const star = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z"/></svg>';

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json', 'X-Videoteca-Token':token, ...options.headers}});
  const body = await response.json();
  if(response.status===401 && location.hostname!=='127.0.0.1'){location.href='/acceso';}
  if (!response.ok) throw new Error(body.error || 'No se ha podido completar la operación.');
  return body;
}

let toastTimer;
function toast(message, error = false) {
  $('toast').textContent = message; $('toast').hidden = false; $('toast').classList.toggle('error', error);
  clearTimeout(toastTimer); toastTimer = setTimeout(() => {$('toast').hidden = true;}, 4500);
}

function options(id, values, label) {
  const selected = $(id).value;
  $(id).replaceChildren(new Option(label, ''));
  values.forEach(value => $(id).add(new Option(value, value)));
  if (values.includes(selected)) $(id).value = selected;
}

async function refreshState() {
  state = await api('/api/state'); token = state.token;
  showDateProgress(state.publication_dates);
  showSync(state.youtube_sync);
  $('all-count').textContent = state.total || '';
  $('favorite-count').textContent = state.favorites || '';
  $('backup').disabled = !state.playlists.length;
  options('tag', state.tags, 'Etiqueta');
  $('playlists').replaceChildren();
  if (!state.playlists.length) {
    const p = document.createElement('p'); p.className='muted sidebar-empty'; p.textContent='Ninguna lista importada'; $('playlists').append(p);
  }
  state.playlists.forEach(p => {
    const b=document.createElement('button'); b.className='nav-item playlist-nav'; b.classList.toggle('active', playlist===p.id);
    b.append(document.createTextNode(p.title));
    const count=document.createElement('span'); count.textContent=p.item_count; count.classList.toggle('incomplete',p.coverage!=='complete'); b.append(count);
    b.title=p.title+(p.coverage==='complete'?'':' · importación '+(p.coverage==='partial'?'parcial':'sin total verificado'));
    b.onclick=()=>{playlist=p.id;favorite=false;refreshView();}; $('playlists').append(b);
  });
}

function duration(seconds) {
  if (seconds===null) return '';
  const h=Math.floor(seconds/3600), m=Math.floor(seconds%3600/60), s=seconds%60;
  return (h ? h+':'+String(m).padStart(2,'0') : String(m))+':'+String(s).padStart(2,'0');
}

function videoRow(v) {
  const row=document.createElement('article'); row.className='video-row'; row.dataset.videoId=v.id;
  const membership=v.playlists.find(p=>p.id===playlist) || v.playlists[0];
  const url=v.available?'https://www.youtube.com/watch?v='+encodeURIComponent(v.id)+(membership?'&list='+encodeURIComponent(membership.id):''):'';
  const thumbnail=document.createElement(v.available?'a':'div'); thumbnail.className='thumbnail';
  if(v.available){thumbnail.href=url;thumbnail.target='_blank';thumbnail.rel='noopener noreferrer';thumbnail.setAttribute('aria-label','Ver '+v.title);}
  if(v.thumbnail_url){const img=document.createElement('img');img.src=v.thumbnail_url;img.alt='';img.loading='lazy';thumbnail.append(img);}
  else {thumbnail.classList.add('unavailable');thumbnail.textContent=v.available?'YouTube':'No disponible';}
  if(v.duration_seconds!==null){const badge=document.createElement('span');badge.className='duration';badge.textContent=duration(v.duration_seconds);thumbnail.append(badge);}
  const info=document.createElement('div');info.className='video-info';
  const title=document.createElement(v.available?'a':'span');title.className='video-title';title.textContent=v.title;
  if(v.available){title.href=url;title.target='_blank';title.rel='noopener noreferrer';}info.append(title);
  const meta=document.createElement('div');meta.className='video-meta';meta.textContent=v.channel || (v.available?'Canal no identificado':'Vídeo privado o eliminado');info.append(meta);
  const published=document.createElement('div');published.className='video-meta publication-date';
  published.textContent=v.published_at?'Publicado: '+new Date(v.published_at.length===10?v.published_at+'T12:00:00':v.published_at).toLocaleDateString('es-ES',{day:'numeric',month:'short',year:'numeric'}):'Fecha desconocida';info.append(published);
  const lists=document.createElement('div');lists.className='memberships';lists.textContent=v.playlists.map(p=>p.title).join(' · ');info.append(lists);
  if(v.tags.length){const tags=document.createElement('div');tags.className='video-tags';v.tags.forEach(tag=>{const b=document.createElement('button');b.className='tag-chip';b.textContent=tag;b.onclick=()=>{$('tag').value=tag;refreshView();};tags.append(b);});info.append(tags);}
  if(v.notes){const note=document.createElement('p');note.className='saved-note';note.textContent=v.notes;info.append(note);}
  const notes=document.createElement('button');notes.className='notes-button';notes.textContent=v.notes||v.tags.length?'Editar etiquetas y notas':'Añadir etiquetas y notas';notes.onclick=()=>openNotes(v);info.append(notes);
  const actions=document.createElement('div');actions.className='row-actions';
  const select=document.createElement('select');select.setAttribute('aria-label','Estado de '+v.title);Object.entries(STATUS).forEach(([value,label])=>select.add(new Option(label,value)));select.value=v.status;
  select.onchange=async()=>{select.disabled=true;try{await api('/api/videos/'+encodeURIComponent(v.id),{method:'PATCH',body:JSON.stringify({status:select.value})});v.status=select.value;await refreshView();}catch(error){select.value=v.status;toast(error.message,true);}finally{select.disabled=false;}};
  const fav=document.createElement('button');fav.className='icon-button';fav.classList.toggle('favorited',v.favorite);fav.innerHTML=star;fav.title=v.favorite?'Quitar de favoritos':'Añadir a favoritos';fav.setAttribute('aria-label',fav.title+': '+v.title);fav.setAttribute('aria-pressed',String(v.favorite));
  fav.onclick=async()=>{fav.disabled=true;try{await api('/api/videos/'+encodeURIComponent(v.id),{method:'PATCH',body:JSON.stringify({favorite:!v.favorite})});await refreshState();await refreshView();}catch(error){toast(error.message,true);}finally{fav.disabled=false;}};
  actions.append(select,fav);row.append(thumbnail,info,actions);return row;
}

async function refreshView() {
  const seq=++requestNumber;
  const selected=state.playlists.find(p=>p.id===playlist);
  $('heading').textContent=selected?selected.title:(favorite?'Favoritos':'Videoteca');
  $('subtitle').textContent=selected?'Importada '+new Date(selected.imported_at).toLocaleDateString('es-ES'):(state.playlists.length?state.playlists.length+' lista'+(state.playlists.length===1?'':'s')+' en tu biblioteca':'');
  $('all-videos').classList.toggle('active',!playlist&&!favorite);$('favorites').classList.toggle('active',!playlist&&favorite);
  document.querySelectorAll('.playlist-nav').forEach((b,i)=>b.classList.toggle('active',state.playlists[i].id===playlist));
  const unverified=(selected?[selected]:state.playlists).filter(p=>p.coverage!=='complete');
  $('coverage').hidden=!unverified.length;
  $('coverage').textContent=unverified.map(p=>p.title+': última recogida '+p.last_collected_count+(p.expected_count===null?' · total sin verificar':' de '+p.expected_count)+'. '+(p.coverage==='partial'?'La importación es parcial.':'No se ha podido verificar el total.')).join(' ');
  const durationValue=$('duration').value;
  const params=new URLSearchParams({q:$('search').value,playlist,favorite:favorite?'1':'',channel:$('channel').value,max_duration:durationValue.startsWith('min:')?'':durationValue,min_duration:durationValue.startsWith('min:')?durationValue.slice(4):'',status:$('status').value,tag:$('tag').value,sort:$('sort').value});
  $('clear-filters').hidden=!['search','channel','duration','status','tag'].some(id=>$(id).value);
  try {
    const result=await api('/api/videos?'+params);
    if(seq!==requestNumber)return;
    const previousChannel=$('channel').value;
    options('channel',result.channels,'Canal');
    if(previousChannel && !$('channel').value){return refreshView();}
    currentVideos=result.videos;
    $('empty-state').hidden=!!state.playlists.length;
    $('no-results').hidden=!state.playlists.length||!!result.total;
    $('results-summary').textContent=state.playlists.length?result.total+' vídeo'+(result.total===1?'':'s')+' único'+(result.total===1?'':'s')+(result.appearance_count!==result.total?' · '+result.appearance_count+' apariciones':''):'';
    $('videos').replaceChildren(...result.videos.map(videoRow));
  } catch(error){toast(error.message,true);}
}

function clearFilters(){['search','channel','duration','status','tag'].forEach(id=>{$(id).value='';});$('sort').value='position';refreshView();}
async function openImport(){
  $('import-status').textContent='';$('import-status').className='';
  $('import-dialog').showModal();
  if(!importer){try{importer=await api('/api/bookmarklet');$('bookmarklet').href=importer.bookmarklet;}catch(error){$('import-status').textContent=error.message;}}
}

async function importFile(file){
  if(!file)return;
  if(!$('import-dialog').open)$('import-dialog').showModal();
  $('import-status').className='muted';$('import-status').textContent='Leyendo e importando '+file.name+'…';
  try{
    if(file.size>8*1024*1024)throw new Error('El archivo supera 8 MB.');
    const contents=JSON.parse(await file.text());
    const imported=await api('/api/import',{method:'POST',body:JSON.stringify(contents)});
    playlist=imported.id;favorite=false;clearFilters();await refreshState();await refreshView();
    $('import-status').className='success';$('import-status').textContent=imported.title+': '+imported.count+' elementos importados. '+(imported.coverage==='complete'?'Lista completa.':imported.coverage==='partial'?'Importación parcial: revisa el aviso del catálogo.':'Total sin verificar: revisa el aviso del catálogo.');
    toast('Importados '+imported.count+' elementos de '+imported.title);
  }catch(error){$('import-status').className='error';$('import-status').textContent=error instanceof SyntaxError?'El archivo no contiene un JSON válido.':error.message;}
  finally{$('import-file').value='';}
}

function openNotes(v){editing=v;$('notes-title').textContent=v.title;$('edit-tags').value=v.tags.join(', ');$('edit-notes').value=v.notes;$('notes-error').textContent='';$('notes-dialog').showModal();}
$('notes-form').onsubmit=async event=>{event.preventDefault();try{await api('/api/videos/'+encodeURIComponent(editing.id),{method:'PATCH',body:JSON.stringify({tags:$('edit-tags').value.split(',').map(t=>t.trim()).filter(Boolean),notes:$('edit-notes').value})});$('notes-dialog').close();await refreshState();await refreshView();toast('Etiquetas y notas guardadas');}catch(error){$('notes-error').textContent=error.message;}};
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
['import-button','empty-import','how-import'].forEach(id=>$(id).onclick=openImport);
$('bookmarklet').onclick=event=>{event.preventDefault();toast('Arrastra el enlace a la barra de favoritos de Safari.');};
$('copy-importer').onclick=async()=>{try{if(!importer)importer=await api('/api/bookmarklet');await navigator.clipboard.writeText(importer.code);toast('Código copiado');}catch(_){toast('No se ha podido copiar. Prueba con el marcador.',true);}};
$('import-file').onchange=event=>importFile(event.target.files[0]);
const drop=$('import-dialog').querySelector('.dropzone');
drop.ondragover=event=>{event.preventDefault();drop.classList.add('dragging');};drop.ondragleave=()=>drop.classList.remove('dragging');drop.ondrop=event=>{event.preventDefault();drop.classList.remove('dragging');importFile(event.dataTransfer.files[0]);};
document.addEventListener('dragover',event=>{if([...event.dataTransfer.types].includes('Files'))event.preventDefault();});
document.addEventListener('drop',event=>{if(event.dataTransfer.files.length){event.preventDefault();if(event.target.closest('.dropzone'))return;importFile(event.dataTransfer.files[0]);}});
$('all-videos').onclick=()=>{playlist='';favorite=false;refreshView();};$('favorites').onclick=()=>{playlist='';favorite=true;refreshView();};
['channel','duration','status','tag','sort'].forEach(id=>$(id).onchange=refreshView);
let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(refreshView,130);};
['clear-filters','reset-results'].forEach(id=>$(id).onclick=clearFilters);
document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key==='k'){event.preventDefault();$('search').focus();}});
$('backup').onclick=async()=>{try{const data=await api('/api/backup');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='videoteca-copia-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){toast(error.message,true);}};
$('update-dates').onclick=async()=>{try{showDateProgress(await api('/api/publication-dates',{method:'POST',body:JSON.stringify({retry:true})}));}catch(error){toast(error.message,true);}};
$('youtube-connect').onclick=openYouTube;
$('youtube-update').onclick=()=>updateYouTube();
$('youtube-dialog').addEventListener('close',()=>{$('youtube-key').value='';});
$('youtube-form').onsubmit=async event=>{
  event.preventDefault();$('youtube-save').disabled=true;$('youtube-error').textContent='';
  try{
    const values={auto_sync:$('youtube-auto').checked};
    if($('youtube-key').value.trim())values.api_key=$('youtube-key').value.trim();
    showSync(await api('/api/youtube/settings',{method:'POST',body:JSON.stringify(values)}));
    $('youtube-dialog').close();await updateYouTube();
  }catch(error){$('youtube-error').textContent=error.message;}finally{$('youtube-save').disabled=false;}
};
$('youtube-disconnect').onclick=async()=>{try{showSync(await api('/api/youtube/settings',{method:'POST',body:JSON.stringify({api_key:'',auto_sync:false})}));$('youtube-dialog').close();toast('Conexión retirada. Tu catálogo se conserva.');}catch(error){$('youtube-error').textContent=error.message;}};
(async()=>{try{await refreshState();await refreshView();if(state.youtube_sync.configured)await updateYouTube(true);}catch(error){toast('No se puede conectar con Videoteca. '+error.message,true);}})();

const localAccess=location.hostname==='127.0.0.1';
$('mobile-access').hidden=!localAccess;
$('youtube-connect').hidden=!localAccess;
$('local-scope').textContent=localAccess?'Datos en este Mac':'Red local con contraseña';
$('mobile-access').onclick=async()=>{
  $('mobile-password').value='';$('mobile-password').type='password';$('mobile-reveal').textContent='Mostrar contraseña';$('mobile-error').textContent='';$('mobile-url').textContent='Consultando acceso…';$('mobile-url').removeAttribute('href');$('mobile-dialog').showModal();
  try{const mobile=await api('/api/mobile');if(!mobile.enabled){$('mobile-url').textContent='Acceso móvil desactivado';$('mobile-error').textContent=mobile.error||'El acceso desde la red local no está configurado.';return;}$('mobile-url').href=mobile.url;$('mobile-url').textContent=mobile.url;$('mobile-password').value=mobile.password;}catch(error){$('mobile-error').textContent=error.message;}
};
$('mobile-reveal').onclick=()=>{const showing=$('mobile-password').type==='password';$('mobile-password').type=showing?'text':'password';$('mobile-reveal').textContent=showing?'Ocultar contraseña':'Mostrar contraseña';};
$('mobile-dialog').addEventListener('close',()=>{$('mobile-password').value='';$('mobile-password').type='password';});

$('mobile-refresh').onclick=async()=>{
  $('mobile-refresh').disabled=true;
  try{const mobile=await api('/api/mobile/restart',{method:'POST',body:'{}'});$('mobile-password').value=mobile.password||'';$('mobile-password').type='password';$('mobile-reveal').textContent='Mostrar contraseña';$('mobile-url').textContent=mobile.enabled?mobile.url:'Acceso móvil desactivado';if(mobile.enabled)$('mobile-url').href=mobile.url;else $('mobile-url').removeAttribute('href');$('mobile-error').textContent=mobile.error||'Dirección actualizada. Vuelve a entrar desde el móvil.';}catch(error){$('mobile-error').textContent=error.message;}finally{$('mobile-refresh').disabled=false;}
};
