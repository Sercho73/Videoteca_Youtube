(async function () {
  'use strict';
  if (!/(^|\.)youtube\.com$/.test(location.hostname) || location.pathname !== '/playlist' || !new URL(location.href).searchParams.get('list')) {
    alert('Abre la página completa de una lista de YouTube y vuelve a pulsar el marcador.');
    return;
  }
  if (document.getElementById('videoteca-importer')) return;
  const pid = new URL(location.href).searchParams.get('list');
  // BEGIN playlist metadata: restrict headings to the active playlist page.
  function playlistMetadata(doc, data, listId) {
    const page=doc.querySelector('ytd-browse[page-subtype="playlist"]:not([hidden])');
    const headers=page?[...page.querySelectorAll('ytd-playlist-header-renderer, ytd-playlist-sidebar-primary-info-renderer, yt-page-header-renderer, yt-page-header-view-model')].filter(h=>!h.closest('[hidden]')):[];
    let title='', expected=null;
    const count=text=>{const m=text.match(/([\d.,\s]+)\s*v[ií]deos?\b/i);return m?Number(m[1].replace(/\D/g,'')):null;};
    for(const header of headers) {
      const heading=header.querySelector('h1, #title');
      if(!title)title=(heading?.textContent || '').trim();
      const metadata=[...header.querySelectorAll('#stats, .yt-content-metadata-view-model__metadata-row, yt-content-metadata-view-model, #metadata')];
      for(const node of metadata)if(expected===null)expected=count(node.textContent || '');
    }
    const root=data || {}, structured=root.header?.playlistHeaderRenderer;
    const canonical=root.microformat?.microformatDataRenderer?.urlCanonical;
    let same=structured?.playlistId===listId;
    try{same=same || new URL(canonical).searchParams.get('list')===listId;}catch(_){}
    const text=value=>value?.simpleText || value?.runs?.map(r=>r.text).join('') || '';
    if(same) {
      title=title || root.metadata?.playlistMetadataRenderer?.title || text(structured?.title);
      if(expected===null) {
        const sidebar=root.sidebar?.playlistSidebarRenderer?.items?.find(i=>i.playlistSidebarPrimaryInfoRenderer)?.playlistSidebarPrimaryInfoRenderer;
        const raw=text(structured?.numVideosText) || text(sidebar?.stats?.[0]);
        expected=count(raw);
        if(expected===null && /^\s*[\d.,\s]+\s*$/.test(raw))expected=Number(raw.replace(/\D/g,''));
      }
    }
    return {title:title || 'Lista de YouTube', title_verified:!!title, expected_count:expected};
  }
  // END playlist metadata
  const metadata=playlistMetadata(document,window.ytInitialData,pid);
  const {title,title_verified}=metadata;
  const expected=metadata.expected_count;
  const panel = document.createElement('section');
  panel.id = 'videoteca-importer';
  Object.assign(panel.style, {position:'fixed',right:'20px',top:'20px',zIndex:'2147483647',width:'320px',padding:'22px',background:'#181b20',color:'#f2f4fa',border:'1px solid #7094ff',borderRadius:'14px',boxShadow:'0 12px 60px #0008',font:'15px/1.5 -apple-system,BlinkMacSystemFont,sans-serif'});
  const heading = document.createElement('strong'); heading.textContent = 'Importando a Videoteca';
  const progress = document.createElement('p'); progress.setAttribute('role','status');
  const hint = document.createElement('p'); hint.textContent = 'Mantén esta pestaña abierta mientras se cargan los vídeos.'; hint.style.color='#b1b8c6'; hint.style.fontSize='13px';
  const stop = document.createElement('button'); stop.textContent='Cancelar y exportar lo recogido';
  Object.assign(stop.style,{background:'#272c36',color:'#fff',padding:'10px 14px',border:'1px solid #626c7d',borderRadius:'8px',cursor:'pointer',font:'inherit'});
  panel.append(heading,progress,hint,stop); document.body.append(panel);
  let cancelled=false; stop.onclick=()=>{cancelled=true;};
  const collected=new Map();
  const read = () => {
    const nodes = document.querySelectorAll('ytd-playlist-video-renderer');
    nodes.forEach((node, offset) => {
      const anchor = node.querySelector('a#video-title') || node.querySelector('a[href*="/watch?"]');
      let url=null; try { if(anchor?.href) url=new URL(anchor.href,location.origin); } catch (_) {}
      const label=node.querySelector('#index')?.textContent?.trim() || '';
      const ordinal=Number(label.replace(/\D/g,''));
      const position=ordinal>0 ? ordinal-1 : (Number(url?.searchParams.get('index'))>0 ? Number(url.searchParams.get('index'))-1 : offset);
      const id=url?.searchParams.get('v') || null;
      const durationText=(node.querySelector('ytd-thumbnail-overlay-time-status-renderer')?.textContent || '').trim();
      const durationMatch=durationText.match(/\b\d{1,3}:\d{2}(?::\d{2})?\b/);
      let duration=null;
      if(durationMatch) duration=durationMatch[0].split(':').reduce((a,b)=>a*60+Number(b),0);
      const img=node.querySelector('ytd-thumbnail img, img');
      const thumbnail=id ? 'https://i.ytimg.com/vi/'+id+'/mqdefault.jpg' : '';
      collected.set(position,{id,title:(anchor?.getAttribute('title') || anchor?.textContent || node.querySelector('#title')?.textContent || 'Vídeo no disponible').trim(),
        channel:(node.querySelector('ytd-channel-name a')?.textContent || node.querySelector('#byline a')?.textContent || node.querySelector('ytd-channel-name #text')?.textContent || '').trim(),
        duration_seconds:duration,position,thumbnail_url:thumbnail || img?.src || ''});
    });
    progress.textContent=collected.size+' vídeos recogidos'+(expected!==null?' de '+expected:' · total sin verificar');
  };
  let stable=0, previous=-1;
  const started=Date.now();
  while(!cancelled && Date.now()-started<180000) {
    read();
    if(expected!==null && collected.size>=expected) break;
    stable=collected.size===previous ? stable+1 : 0; previous=collected.size;
    if(stable>=10) break;
    window.scrollTo(0,document.scrollingElement.scrollHeight);
    await new Promise(resolve=>setTimeout(resolve,1200));
  }
  read();
  const videos=[...collected.values()].sort((a,b)=>a.position-b.position);
  const complete=expected!==null && videos.length===expected && videos.every((v,i)=>v.position===i);
  const result={format:'youtube-library/v1',playlist:{id:pid,title,title_verified,source_url:'https://www.youtube.com/playlist?list='+pid,expected_count:expected,coverage:complete?'complete':(expected===null?'unverified':'partial'),exported_at:new Date().toISOString()},videos};
  const blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'});
  const objectURL=URL.createObjectURL(blob);
  const download=()=>{const a=document.createElement('a');a.href=objectURL;a.download='videoteca-'+pid+'-'+new Date().toISOString().slice(0,10)+'.json';document.body.append(a);a.click();a.remove();};
  heading.textContent=complete?'Lista recogida completa':'Exportación '+(expected===null?'sin total verificado':'parcial');
  hint.textContent='Abre Videoteca e importa el archivo JSON descargado.';
  stop.textContent='Descargar de nuevo'; stop.onclick=download;
  const close=document.createElement('button');close.textContent='Cerrar';Object.assign(close.style,{marginLeft:'12px',border:'0',background:'none',color:'#b1b8c6',cursor:'pointer',font:'inherit'});close.onclick=()=>{URL.revokeObjectURL(objectURL);panel.remove();};panel.append(close);
  download();
})();
