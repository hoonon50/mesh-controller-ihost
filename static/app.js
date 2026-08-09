const POS={"192.168.30.1":[50,50],"192.168.30.2":[12,14],"192.168.30.3":[88,14],"192.168.30.4":[88,86],"192.168.30.5":[12,86]};
let lastStatus={nodes:[],links:[],clients:[]};
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function jfetch(url,opt={}){const r=await fetch(url,opt);if(!r.ok)throw new Error(await r.text());return r.json();}
function metric(title,value){return `<div class="metric"><small>${title}</small><strong>${value}</strong></div>`}
function displayName(n){return n?.hostname||n?.name||n?.ip||'Router'}
function renderStatus(s){
  lastStatus=s;
  const online=s.nodes.filter(n=>n.online).length;
  $('#metrics').innerHTML=metric('ONLINE ROUTERY',`${online} / ${s.nodes.length||5}`)+metric('MESH SPOJE',s.links.length)+metric('KLIENTI',s.clients.length)+metric('ZÁLOHY','/data')+metric('OBNOVENO',s.updated?new Date(s.updated*1000).toLocaleTimeString('cs-CZ'):'—');
  renderTopology(s);renderPorts(s.nodes||[]);renderClients(s.clients||[]);renderLedTargets(s.nodes||[]);
}
function linkColor(dbm){if(dbm==null)return '#77818e';return dbm>=-60?'#31d17c':dbm>=-72?'#f0b84b':'#ff5d6c'}
function intersects(a,b,pad=7){return !(a.r+pad<b.l||a.l-pad>b.r||a.b+pad<b.t||a.t-pad>b.b)}
function clamp(v,min,max){return Math.max(min,Math.min(max,v))}
function qPoint(p0,p1,p2,t){const u=1-t;return {x:u*u*p0.x+2*u*t*p1.x+t*t*p2.x,y:u*u*p0.y+2*u*t*p1.y+t*t*p2.y}}
function pairHash(a,b){return [...`${a}|${b}`].reduce((v,c)=>(v*33+c.charCodeAt(0))>>>0,5381)}
function renderTopology(s){
  const topo=$('#topology'),svg=$('#linkLayer'),nl=$('#nodeLayer'),ll=$('#linkLabels');
  const rect=topo.getBoundingClientRect(),W=rect.width,H=rect.height;svg.innerHTML='';nl.innerHTML='';ll.innerHTML='';
  const nodeByIp=Object.fromEntries((s.nodes||[]).map(n=>[n.ip,n]));
  const occupied=[];
  for(const pos of Object.values(POS)){const cx=W*pos[0]/100,cy=H*pos[1]/100;occupied.push({l:cx-88,r:cx+88,t:cy-52,b:cy+52});}

  (s.links||[]).forEach((link,index)=>{
    const pa=POS[link.a],pb=POS[link.b];if(!pa||!pb)return;
    const p0={x:W*pa[0]/100,y:H*pa[1]/100},p2={x:W*pb[0]/100,y:H*pb[1]/100};
    const dx=p2.x-p0.x,dy=p2.y-p0.y,len=Math.hypot(dx,dy)||1,nx=-dy/len,ny=dx/len;
    const hash=pairHash(link.a,link.b);
    const touchesCenter=link.a==='192.168.30.1'||link.b==='192.168.30.1';
    const sign=(hash&1)?1:-1;
    const bend=(touchesCenter?Math.min(34,len*.075):Math.min(72,len*.14))*sign;
    const p1={x:(p0.x+p2.x)/2+nx*bend,y:(p0.y+p2.y)/2+ny*bend};
    const d=`M ${p0.x.toFixed(1)} ${p0.y.toFixed(1)} Q ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;

    const halo=document.createElementNS('http://www.w3.org/2000/svg','path');
    halo.setAttribute('d',d);halo.setAttribute('class','mesh-link-halo');svg.appendChild(halo);
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',d);path.setAttribute('class','mesh-link');path.setAttribute('stroke',linkColor(link.dbm));svg.appendChild(path);

    const parts=[];
    if(link.dbm!=null)parts.push(`${link.dbm} dBm`);
    if(link.speed_mbps!=null)parts.push(`${Number(link.speed_mbps).toFixed(link.speed_mbps%1?1:0)} Mbit/s`);
    const text=parts.join('  •  ')||'mesh';
    const estW=Math.max(115,text.length*7.2+24),estH=31;
    const tCandidates=(index%2)?[.27,.73,.34,.66,.43,.57]:[.73,.27,.66,.34,.57,.43];
    const offsets=[0,22,-22,38,-38,54,-54];
    let chosen=null;
    outer:for(const t of tCandidates){
      const q=qPoint(p0,p1,p2,t);
      for(const off of offsets){
        const x=clamp(q.x+nx*off,estW/2+8,W-estW/2-8),y=clamp(q.y+ny*off,estH/2+8,H-estH/2-8);
        const box={l:x-estW/2,r:x+estW/2,t:y-estH/2,b:y+estH/2};
        if(!occupied.some(o=>intersects(box,o))){chosen={x,y,box};break outer;}
      }
    }
    if(!chosen){
      const q=qPoint(p0,p1,p2,index%2?.30:.70),off=index%2?42:-42;
      const x=clamp(q.x+nx*off,estW/2+8,W-estW/2-8),y=clamp(q.y+ny*off,estH/2+8,H-estH/2-8);
      chosen={x,y,box:{l:x-estW/2,r:x+estW/2,t:y-estH/2,b:y+estH/2}};
    }
    occupied.push(chosen.box);
    const badge=document.createElement('div');badge.className='link-label';badge.style.left=`${chosen.x}px`;badge.style.top=`${chosen.y}px`;badge.style.setProperty('--link-color',linkColor(link.dbm));
    const sig=link.dbm!=null?`<strong>${esc(link.dbm)} dBm</strong>`:'';
    const speed=link.speed_mbps!=null?`<span>${esc(Number(link.speed_mbps).toFixed(link.speed_mbps%1?1:0))} Mbit/s</span>`:'';
    badge.innerHTML=`${sig}${speed}`;ll.appendChild(badge);
  });

  for(const [ip,pos] of Object.entries(POS)){
    const n=nodeByIp[ip]||{ip,name:ip,hostname:'',online:false,clients:0},d=document.createElement('div');
    d.className=`node ${n.online?'online':'offline'}`;d.style.left=`${pos[0]}%`;d.style.top=`${pos[1]}%`;
    d.innerHTML=`<b>${esc(displayName(n))}</b><small>${esc(ip)}</small><div class="state">${n.online?'ONLINE':'OFFLINE'} · ${n.clients||0} klientů</div>`;nl.appendChild(d);
  }
}
function portClass(p){if(!p.up)return 'port-down';const speed=Number(p.speed_mbps||0);if(speed>=1000)return 'port-gigabit';if(speed>0)return 'port-fast';return 'port-up';}
function prettyPortName(name){const n=String(name||'').trim(),m=n.match(/^lan(\d+)$/i);return m?`LAN${m[1]}`:n.toUpperCase();}
function renderPorts(nodes){
  const box=$('#portsGrid');if(!box)return;
  box.innerHTML=(nodes||[]).map(n=>{
    const ports=n.ports||[];
    const tiles=ports.length?ports.map(p=>{const speed=p.up?(p.speed_mbps?`${p.speed_mbps} Mbit/s`:'RYCHLOST ?'):'—';return `<div class="port-tile ${portClass(p)}"><strong>${esc(prettyPortName(p.name))}</strong><span>${esc(speed)}</span><b>${p.up?'UP':'DOWN'}</b></div>`;}).join(''):`<div class="port-empty">${n.online?'Fyzické LAN porty nebyly nalezeny.':'Router je offline.'}</div>`;
    return `<section class="router-ports"><div class="router-ports-head"><strong>${esc(displayName(n))}</strong><span>${esc(n.ip)}</span></div><div class="port-tiles">${tiles}</div></section>`;
  }).join('');
}
function renderLedTargets(nodes){
  const sel=$('#ledTarget');if(!sel)return;const current=sel.value;
  sel.innerHTML='<option value="all">Všechny routery</option>'+nodes.map(n=>`<option value="${esc(n.ip)}">${esc(displayName(n))} · ${esc(n.ip)}</option>`).join('');
  if([...sel.options].some(o=>o.value===current))sel.value=current;
}
function renderClients(clients){$('#clientsBody').innerHTML=clients.length?clients.map(c=>`<tr><td>${esc(c.node)}</td><td>${esc(c.hostname||'')}</td><td>${esc(c.ip)}</td><td>${esc(c.mac)}</td><td>${esc(c.type)}</td><td>${esc(c.detail||'')}</td></tr>`).join(''):`<tr><td colspan="6" style="color:var(--muted)">Žádní klienti nebyli nalezeni přes Wi-Fi, FDB, ARP ani DHCP.</td></tr>`}
async function loadStatus(){try{renderStatus(await jfetch('/api/status'))}catch(e){console.error(e)}}
function stateClass(s){return s==='HOTOVO'?'state-ok':s==='CHYBA'?'state-err':s==='PROBÍHÁ'?'state-run':'state-wait'}
async function loadOperation(){try{const o=await jfetch('/api/operation');$('#opPercent').textContent=`${o.percent||0} %`;$('#progressBar').style.width=`${o.percent||0}%`;$('#opCurrent').textContent=o.current||'Připraveno';$('#opResult').textContent=o.result||'';const sec=o.elapsed||0;$('#opTime').textContent=`Čas: ${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;$('#opNodes').innerHTML=Object.entries(o.nodes||{}).map(([ip,n])=>`<div class="op-node"><b>${esc(n.name)}</b><small>${esc(n.detail||ip)}</small><strong class="${stateClass(n.state)}">${esc(n.state)}</strong></div>`).join('');$('#opLog').textContent=(o.log||[]).join('\n');$('#opLog').scrollTop=$('#opLog').scrollHeight;$$('[data-action]').forEach(b=>b.disabled=!!o.running);if(!o.running&&o.finished){loadBackups();loadStatus();}}catch(e){console.error(e)}}
async function runAction(name){const body=(name==='led_on'||name==='led_off')?{target:$('#ledTarget').value}:{};try{await jfetch(`/api/action/${name}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});loadOperation()}catch(e){console.error(e)}}
async function loadBackups(){try{const sets=await jfetch('/api/backups'),box=$('#backupList');if(!sets.length){box.innerHTML='<div style="color:var(--muted);padding:8px 0">Zatím není vytvořená žádná záloha.</div>';return}box.innerHTML=sets.map(s=>`<div class="backup-set"><div class="backup-main"><strong>${esc(s.created)}</strong><span>${s.count}/5 souborů</span><a class="mini good-btn" href="/api/backups/${encodeURIComponent(s.id)}.zip">STÁHNOUT ZIP</a><button class="mini danger" onclick="deleteBackup('${esc(s.id)}')">SMAZAT</button></div><div class="backup-files">${s.files.map(f=>`<a href="/api/backups/${encodeURIComponent(s.id)}/${encodeURIComponent(f.name)}">${esc(f.name)} · ${(f.size/1024).toFixed(0)} kB</a>`).join('')}</div></div>`).join('');}catch(e){console.error(e)}}
async function deleteBackup(id){if(!confirm('Opravdu smazat tuto sadu záloh?'))return;await fetch(`/api/backups/${encodeURIComponent(id)}`,{method:'DELETE'});loadBackups()}
$$('[data-action]').forEach(b=>b.addEventListener('click',()=>runAction(b.dataset.action)));$('#refreshBtn').addEventListener('click',async()=>{await fetch('/api/refresh',{method:'POST'});setTimeout(loadStatus,1800)});window.addEventListener('resize',()=>renderTopology(lastStatus));loadStatus();loadOperation();loadBackups();setInterval(loadOperation,1000);setInterval(loadStatus,30000);setInterval(loadBackups,15000);
