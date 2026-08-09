const POS={
  "192.168.30.1":[50,50],
  "192.168.30.2":[15,18],
  "192.168.30.3":[85,18],
  "192.168.30.4":[85,82],
  "192.168.30.5":[15,82]
};
let lastStatus={nodes:[],links:[],clients:[]};
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function jfetch(url,opt={}){const r=await fetch(url,opt);if(!r.ok)throw new Error(await r.text());return r.json();}
function metric(title,value){return `<div class="metric"><small>${title}</small><strong>${value}</strong></div>`}
function renderStatus(s){
  lastStatus=s;
  const online=s.nodes.filter(n=>n.online).length;
  $('#metrics').innerHTML=metric('ONLINE UZLY',`${online} / ${s.nodes.length||5}`)+metric('MESH SPOJE',s.links.length)+metric('KLIENTI',s.clients.length)+metric('ZÁLOHY','/data')+metric('OBNOVENO',s.updated?new Date(s.updated*1000).toLocaleTimeString('cs-CZ'):'—');
  renderTopology(s); renderClients(s.clients||[]);
}
function linkColor(dbm){if(dbm==null)return '#5c6572';return dbm>=-60?'#31d17c':dbm>=-72?'#f0b84b':'#ff5d6c'}
function renderTopology(s){
  const topo=$('#topology'), svg=$('#linkLayer'), nl=$('#nodeLayer'), ll=$('#linkLabels');
  const rect=topo.getBoundingClientRect(), W=rect.width,H=rect.height;
  svg.innerHTML='';nl.innerHTML='';ll.innerHTML='';
  const nodeByIp=Object.fromEntries((s.nodes||[]).map(n=>[n.ip,n]));
  for(const link of (s.links||[])){
    const pa=POS[link.a],pb=POS[link.b]; if(!pa||!pb)continue;
    const x1=W*pa[0]/100,y1=H*pa[1]/100,x2=W*pb[0]/100,y2=H*pb[1]/100;
    const line=document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1',x1);line.setAttribute('y1',y1);line.setAttribute('x2',x2);line.setAttribute('y2',y2);line.setAttribute('stroke',linkColor(link.dbm));line.setAttribute('stroke-width','4');line.setAttribute('stroke-linecap','round');svg.appendChild(line);
    // štítek schválně není uprostřed spoje: 32 % od uzlu A + kolmý odsazení
    const t=.32, bx=x1+(x2-x1)*t, by=y1+(y2-y1)*t, dx=x2-x1,dy=y2-y1,len=Math.hypot(dx,dy)||1;
    const x=bx+(-dy/len)*18,y=by+(dx/len)*18;
    const parts=[]; if(link.dbm!=null)parts.push(`${link.dbm} dBm`); if(link.speed_mbps!=null)parts.push(`${Number(link.speed_mbps).toFixed(link.speed_mbps%1?1:0)} Mbit/s`); if(link.mhz!=null)parts.push(`${link.mhz} MHz`);
    const d=document.createElement('div');d.className='link-label';d.style.left=`${x}px`;d.style.top=`${y}px`;d.style.borderColor=linkColor(link.dbm);d.textContent=parts.join(' · ')||'mesh';ll.appendChild(d);
  }
  for(const [ip,pos] of Object.entries(POS)){
    const n=nodeByIp[ip]||{ip,name:ip,online:false,clients:0};const d=document.createElement('div');d.className=`node ${n.online?'online':'offline'}`;d.style.left=`${pos[0]}%`;d.style.top=`${pos[1]}%`;d.innerHTML=`<b>${esc(n.name)}</b><small>${esc(ip)}</small><div class="state">${n.online?'ONLINE':'OFFLINE'} · ${n.clients||0} klientů</div>`;nl.appendChild(d);
  }
}
function renderClients(clients){$('#clientsBody').innerHTML=clients.length?clients.map(c=>`<tr><td>${esc(c.node)}</td><td>${esc(c.ip)}</td><td>${esc(c.mac)}</td><td>${esc(c.type)}</td></tr>`).join(''):`<tr><td colspan="4" style="color:var(--muted)">Žádní klienti nejsou právě v tabulce sousedů.</td></tr>`}
async function loadStatus(){try{renderStatus(await jfetch('/api/status'))}catch(e){console.error(e)}}
function stateClass(s){return s==='HOTOVO'?'state-ok':s==='CHYBA'?'state-err':s==='PROBÍHÁ'?'state-run':'state-wait'}
async function loadOperation(){
  try{const o=await jfetch('/api/operation');$('#opPercent').textContent=`${o.percent||0} %`;$('#progressBar').style.width=`${o.percent||0}%`;$('#opCurrent').textContent=o.current||'Připraveno';$('#opResult').textContent=o.result||'';const sec=o.elapsed||0;$('#opTime').textContent=`Čas: ${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;
    $('#opNodes').innerHTML=Object.entries(o.nodes||{}).map(([ip,n])=>`<div class="op-node"><b>${esc(n.name)}</b><small>${esc(n.detail||ip)}</small><strong class="${stateClass(n.state)}">${esc(n.state)}</strong></div>`).join('');$('#opLog').textContent=(o.log||[]).join('\n');$('#opLog').scrollTop=$('#opLog').scrollHeight;$$('[data-action]').forEach(b=>b.disabled=!!o.running);
    if(!o.running && o.finished){loadBackups();loadStatus();}
  }catch(e){console.error(e)}
}
async function runAction(name){
  const body=(name==='led_on'||name==='led_off')?{target:$('#ledTarget').value}:{};
  try{await jfetch(`/api/action/${name}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});loadOperation()}catch(e){console.error(e)}
}
async function loadBackups(){
  try{const sets=await jfetch('/api/backups');const box=$('#backupList');if(!sets.length){box.innerHTML='<div style="color:var(--muted);padding:8px 0">Zatím není vytvořená žádná záloha.</div>';return}
    box.innerHTML=sets.map(s=>`<div class="backup-set"><div class="backup-main"><strong>${esc(s.created)}</strong><span>${s.count}/5 souborů</span><a class="mini good-btn" href="/api/backups/${encodeURIComponent(s.id)}.zip">STÁHNOUT ZIP</a><button class="mini danger" onclick="deleteBackup('${esc(s.id)}')">SMAZAT</button></div><div class="backup-files">${s.files.map(f=>`<a href="/api/backups/${encodeURIComponent(s.id)}/${encodeURIComponent(f.name)}">${esc(f.name)} · ${(f.size/1024).toFixed(0)} kB</a>`).join('')}</div></div>`).join('');
  }catch(e){console.error(e)}
}
async function deleteBackup(id){if(!confirm('Opravdu smazat tuto sadu záloh?'))return;await fetch(`/api/backups/${encodeURIComponent(id)}`,{method:'DELETE'});loadBackups()}
$$('[data-action]').forEach(b=>b.addEventListener('click',()=>runAction(b.dataset.action)));
$('#refreshBtn').addEventListener('click',async()=>{await fetch('/api/refresh',{method:'POST'});setTimeout(loadStatus,1200)});
window.addEventListener('resize',()=>renderTopology(lastStatus));
loadStatus();loadOperation();loadBackups();setInterval(loadOperation,1000);setInterval(loadStatus,30000);setInterval(loadBackups,15000);
