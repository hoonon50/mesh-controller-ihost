const POS={"192.168.30.1":[50,50],"192.168.30.2":[13,16],"192.168.30.3":[87,16],"192.168.30.4":[87,84],"192.168.30.5":[13,84]};
let lastStatus={nodes:[],links:[],clients:[]};
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function jfetch(url,opt={}){const r=await fetch(url,opt);if(!r.ok)throw new Error(await r.text());return r.json();}
function metric(title,value){return `<div class="metric"><small>${title}</small><strong>${value}</strong></div>`}
function renderStatus(s){lastStatus=s;const online=s.nodes.filter(n=>n.online).length;$('#metrics').innerHTML=metric('ONLINE UZLY',`${online} / ${s.nodes.length||5}`)+metric('MESH SPOJE',s.links.length)+metric('KLIENTI',s.clients.length)+metric('ZÁLOHY','/data')+metric('OBNOVENO',s.updated?new Date(s.updated*1000).toLocaleTimeString('cs-CZ'):'—');renderTopology(s);renderPorts(s.nodes||[]);renderClients(s.clients||[]);}
function linkColor(dbm){if(dbm==null)return '#77818e';return dbm>=-60?'#31d17c':dbm>=-72?'#f0b84b':'#ff5d6c'}
function intersects(a,b,pad=5){return !(a.r+pad<b.l||a.l-pad>b.r||a.b+pad<b.t||a.t-pad>b.b)}
function clamp(v,min,max){return Math.max(min,Math.min(max,v))}
function renderTopology(s){
  const topo=$('#topology'),svg=$('#linkLayer'),nl=$('#nodeLayer'),ll=$('#linkLabels');const rect=topo.getBoundingClientRect(),W=rect.width,H=rect.height;svg.innerHTML='';nl.innerHTML='';ll.innerHTML='';
  const nodeByIp=Object.fromEntries((s.nodes||[]).map(n=>[n.ip,n]));const occupied=[];
  for(const pos of Object.values(POS)){const cx=W*pos[0]/100,cy=H*pos[1]/100;occupied.push({l:cx-82,r:cx+82,t:cy-48,b:cy+48});}
  (s.links||[]).forEach((link,index)=>{const pa=POS[link.a],pb=POS[link.b];if(!pa||!pb)return;const x1=W*pa[0]/100,y1=H*pa[1]/100,x2=W*pb[0]/100,y2=H*pb[1]/100;
    const line=document.createElementNS('http://www.w3.org/2000/svg','line');line.setAttribute('x1',x1);line.setAttribute('y1',y1);line.setAttribute('x2',x2);line.setAttribute('y2',y2);line.setAttribute('stroke',linkColor(link.dbm));line.setAttribute('stroke-width','3');line.setAttribute('stroke-opacity','.86');line.setAttribute('stroke-linecap','round');svg.appendChild(line);
    const parts=[];if(link.dbm!=null)parts.push(`${link.dbm} dBm`);if(link.speed_mbps!=null)parts.push(`${Number(link.speed_mbps).toFixed(link.speed_mbps%1?1:0)} Mbit/s`);const text=parts.join(' · ')||'mesh';
    const dx=x2-x1,dy=y2-y1,len=Math.hypot(dx,dy)||1,nx=-dy/len,ny=dx/len,estW=Math.max(92,text.length*6.7+18),estH=28;const ts=index%2?[.66,.34,.76,.24,.52]:[.34,.66,.24,.76,.48],offs=index%2?[24,-24,38,-38]:[-24,24,-38,38];let chosen=null;
    outer:for(const t of ts){for(const off of offs){let x=clamp(x1+dx*t+nx*off,estW/2+7,W-estW/2-7),y=clamp(y1+dy*t+ny*off,estH/2+7,H-estH/2-7);const box={l:x-estW/2,r:x+estW/2,t:y-estH/2,b:y+estH/2};if(!occupied.some(o=>intersects(box,o))){chosen={x,y,box};break outer;}}}
    if(!chosen){const t=index%2?.64:.36,off=index%2?30:-30,x=clamp(x1+dx*t+nx*off,estW/2+7,W-estW/2-7),y=clamp(y1+dy*t+ny*off,estH/2+7,H-estH/2-7);chosen={x,y,box:{l:x-estW/2,r:x+estW/2,t:y-estH/2,b:y+estH/2}};}
    occupied.push(chosen.box);const d=document.createElement('div');d.className='link-label';d.style.left=`${chosen.x}px`;d.style.top=`${chosen.y}px`;d.style.setProperty('--link-color',linkColor(link.dbm));d.textContent=text;ll.appendChild(d);
  });
  for(const [ip,pos] of Object.entries(POS)){const n=nodeByIp[ip]||{ip,name:ip,online:false,clients:0},d=document.createElement('div');d.className=`node ${n.online?'online':'offline'}`;d.style.left=`${pos[0]}%`;d.style.top=`${pos[1]}%`;d.innerHTML=`<b>${esc(n.name)}</b><small>${esc(ip)}</small><div class="state">${n.online?'ONLINE':'OFFLINE'} · ${n.clients||0} klientů</div>`;nl.appendChild(d);}
}

function portClass(p){
  if(!p.up)return 'port-down';
  const speed=Number(p.speed_mbps||0);
  if(speed>=1000)return 'port-gigabit';
  if(speed>0)return 'port-fast';
  return 'port-up';
}
function prettyPortName(name){
  const n=String(name||'').trim();
  const m=n.match(/^lan(\d+)$/i);
  return m?`LAN${m[1]}`:n.toUpperCase();
}
function renderPorts(nodes){
  const box=$('#portsGrid');
  if(!box)return;
  box.innerHTML=(nodes||[]).map(n=>{
    const ports=n.ports||[];
    const tiles=ports.length?ports.map(p=>{
      const speed=p.up?(p.speed_mbps?`${p.speed_mbps} Mbit/s`:'RYCHLOST ?'):'—';
      return `<div class="port-tile ${portClass(p)}"><strong>${esc(prettyPortName(p.name))}</strong><span>${esc(speed)}</span><b>${p.up?'UP':'DOWN'}</b></div>`;
    }).join(''):`<div class="port-empty">${n.online?'Fyzické LAN porty nebyly nalezeny.':'Uzel je offline.'}</div>`;
    return `<section class="router-ports"><div class="router-ports-head"><strong>${esc(n.name)}</strong><span>${esc(n.ip)}</span></div><div class="port-tiles">${tiles}</div></section>`;
  }).join('');
}

function renderClients(clients){$('#clientsBody').innerHTML=clients.length?clients.map(c=>`<tr><td>${esc(c.node)}</td><td>${esc(c.hostname||'')}</td><td>${esc(c.ip)}</td><td>${esc(c.mac)}</td><td>${esc(c.type)}</td><td>${esc(c.detail||'')}</td></tr>`).join(''):`<tr><td colspan="6" style="color:var(--muted)">Žádní klienti nebyli nalezeni přes Wi-Fi, FDB, ARP ani DHCP.</td></tr>`}
async function loadStatus(){try{renderStatus(await jfetch('/api/status'))}catch(e){console.error(e)}}
function stateClass(s){return s==='HOTOVO'?'state-ok':s==='CHYBA'?'state-err':s==='PROBÍHÁ'?'state-run':'state-wait'}
async function loadOperation(){try{const o=await jfetch('/api/operation');$('#opPercent').textContent=`${o.percent||0} %`;$('#progressBar').style.width=`${o.percent||0}%`;$('#opCurrent').textContent=o.current||'Připraveno';$('#opResult').textContent=o.result||'';const sec=o.elapsed||0;$('#opTime').textContent=`Čas: ${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;$('#opNodes').innerHTML=Object.entries(o.nodes||{}).map(([ip,n])=>`<div class="op-node"><b>${esc(n.name)}</b><small>${esc(n.detail||ip)}</small><strong class="${stateClass(n.state)}">${esc(n.state)}</strong></div>`).join('');$('#opLog').textContent=(o.log||[]).join('\n');$('#opLog').scrollTop=$('#opLog').scrollHeight;$$('[data-action]').forEach(b=>b.disabled=!!o.running);if(!o.running&&o.finished){loadBackups();loadStatus();}}catch(e){console.error(e)}}
async function runAction(name){const body=(name==='led_on'||name==='led_off')?{target:$('#ledTarget').value}:{};try{await jfetch(`/api/action/${name}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});loadOperation()}catch(e){console.error(e)}}
async function loadBackups(){try{const sets=await jfetch('/api/backups'),box=$('#backupList');if(!sets.length){box.innerHTML='<div style="color:var(--muted);padding:8px 0">Zatím není vytvořená žádná záloha.</div>';return}box.innerHTML=sets.map(s=>`<div class="backup-set"><div class="backup-main"><strong>${esc(s.created)}</strong><span>${s.count}/5 souborů</span><a class="mini good-btn" href="/api/backups/${encodeURIComponent(s.id)}.zip">STÁHNOUT ZIP</a><button class="mini danger" onclick="deleteBackup('${esc(s.id)}')">SMAZAT</button></div><div class="backup-files">${s.files.map(f=>`<a href="/api/backups/${encodeURIComponent(s.id)}/${encodeURIComponent(f.name)}">${esc(f.name)} · ${(f.size/1024).toFixed(0)} kB</a>`).join('')}</div></div>`).join('');}catch(e){console.error(e)}}
async function deleteBackup(id){if(!confirm('Opravdu smazat tuto sadu záloh?'))return;await fetch(`/api/backups/${encodeURIComponent(id)}`,{method:'DELETE'});loadBackups()}
$$('[data-action]').forEach(b=>b.addEventListener('click',()=>runAction(b.dataset.action)));$('#refreshBtn').addEventListener('click',async()=>{await fetch('/api/refresh',{method:'POST'});setTimeout(loadStatus,1800)});window.addEventListener('resize',()=>renderTopology(lastStatus));loadStatus();loadOperation();loadBackups();setInterval(loadOperation,1000);setInterval(loadStatus,30000);setInterval(loadBackups,15000);
