let data={summary:{},nodes:{},links:[],clients:[],routers:[]};
let filter='Vše';
let operation={status:'idle',progress:0,nodes:{},logs:[]};
const $=id=>document.getElementById(id);

function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(msg,bad=false){let t=$('toast');t.textContent=typeof msg==='string'?msg:JSON.stringify(msg,null,2);t.style.display='block';t.style.borderColor=bad?'#ff4d5e':'#353540';setTimeout(()=>t.style.display='none',6500)}
function metric(title,val){return `<div class="metric"><small>${title}</small><strong>${val}</strong></div>`}
function formatElapsed(sec){sec=Math.max(0,Number(sec)||0);let m=Math.floor(sec/60),s=sec%60;return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}

async function fetchStatus(){
  try{
    let r=await fetch('/api/status');
    data=await r.json();
    render();
  }catch(e){toast('Nelze načíst stav: '+e,true)}
}

function render(){
  let s=data.summary||{};
  $('metrics').innerHTML=
    metric('ONLINE UZLY',`${s.online||0} / ${s.total_nodes||5}`)+
    metric('KLIENTI',s.clients||0)+
    metric('WI‑FI',s.wifi||0)+
    metric('LAN POTVRZ.',s.lan||0)+
    metric('NEURČENÉ',s.unknown||0)+
    metric('MESH SPOJE',s.mesh_links||0)+
    metric('DHCP LEASES',s.leases||0);
  $('lastRefresh').textContent='Poslední načtení: '+(s.last_refresh||'zatím neproběhlo');
  renderMap();renderClients();renderPorts();
}

function setFilter(v){filter=v;renderClients()}

function renderClients(){
  let q=($('search')?.value||'').toLowerCase();
  let rows=(data.clients||[]).filter(c=>(filter==='Vše'||c.connection_type===filter)&&JSON.stringify(c).toLowerCase().includes(q));
  $('clientsBody').innerHTML=rows.map(c=>{
    let cls=c.connection_type==='Wi-Fi'?'wifi':c.connection_type==='LAN'?'lan':'unknown';
    let detail=c.connection_type==='Wi-Fi'?`${c.band||''} · ${c.signal??'?'} dBm · ${c.tx_bitrate||''}`:`${c.link_speed||''} · ${c.detection_source||''}`;
    return `<tr><td>${esc(c.node_ip.split('.').pop())}</td><td class="${cls}">${esc(c.connection_type)}</td><td>${esc(c.hostname||'—')}</td><td>${esc(c.ip||'—')}</td><td>${esc(c.mac)}</td><td>${esc(c.port||c.interface||'—')}</td><td>${esc(detail)}</td></tr>`
  }).join('')||'<tr><td colspan="7">Žádní klienti.</td></tr>';
}

function positions(){
  return {
    '192.168.30.1':[500,310],
    '192.168.30.2':[130,100],
    '192.168.30.3':[870,100],
    '192.168.30.4':[870,520],
    '192.168.30.5':[130,520]
  };
}
function linkColor(sig){if(sig==null)return '#778';if(sig>=-60)return '#00d86f';if(sig>=-72)return '#f4b942';return '#ff4d5e'}

function renderMap(){
  let p=positions(),svg=$('meshMap'),links='',nodes='';
  for(let l of(data.links||[])){
    let a=p[l.a_ip],b=p[l.b_ip];if(!a||!b)continue;
    let mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2;
    links+=`<line class="link" x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${linkColor(l.signal)}"/>`+
      `<rect class="linkLabelBg" x="${mx-66}" y="${my-15}" width="132" height="28" rx="9"/>`+
      `<text class="linkLabel" x="${mx}" y="${my+4}" text-anchor="middle">${esc(l.label||'mesh')}</text>`;
  }
  for(let r of(data.routers||[])){
    let [x,y]=p[r.ip]||[50,50],n=data.nodes?.[r.ip],on=!!n?.online,nodeNo=esc(r.ip.split('.').pop());
    nodes+=`<g class="nodeGroup">`+
      `<rect class="nodeCard" x="${x-84}" y="${y-50}" width="168" height="100" rx="20" stroke="${on?'#00d86f':'#ff4d5e'}"/>`+
      `<circle class="statusDot" cx="${x-61}" cy="${y-27}" r="6" fill="${on?'#00d86f':'#ff4d5e'}"/>`+
      `<path class="wifiArc" d="M ${x+38} ${y-25} q 17 -15 34 0 M ${x+45} ${y-17} q 10 -9 20 0 M ${x+54} ${y-9} q 1 -1 2 0"/>`+
      `<text class="nodeTitle" x="${x}" y="${y-10}" text-anchor="middle">UZEL .${nodeNo}</text>`+
      `<text class="nodeSub" x="${x}" y="${y+12}" text-anchor="middle">${esc(n?.hostname||r.name)}</text>`+
      `<text class="nodeSub" x="${x}" y="${y+31}" text-anchor="middle">${on?esc(n.uptime||'online'):'OFFLINE'}</text>`+
      `</g>`;
  }
  svg.innerHTML=links+nodes;
}

function renderPorts(){
  let rows=[];
  for(let [ip,n] of Object.entries(data.nodes||{})){
    for(let p of(n.lan_ports||[])){
      let state=p.carrier||p.operstate==='up'||(p.client_macs||[]).length?'UP':'DOWN';
      rows.push(`<div class="portrow"><b>.${esc(ip.split('.').pop())}</b><span class="${p.is_uplink?'uplink':''}">${esc(p.port)}${p.is_uplink?' (uplink)':''}</span><span class="${state==='UP'?'up':'down'}">${state}</span><span>${esc(p.speed||'—')}</span></div>`)
    }
  }
  $('ports').innerHTML=rows.join('')||'<span class="muted">Porty zatím nenačteny.</span>';
}

async function post(url,payload){
  let r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:payload?JSON.stringify(payload):'{}'});
  let j=await r.json();
  if(!r.ok||j.ok===false)throw new Error(j.error||'Operace selhala');
  return j;
}

async function startOperation(url,payload=null,question=null){
  if(question&&!confirm(question))return;
  try{
    let j=await post(url,payload||{});
    operation=j.operation||operation;
    renderOperation();
    toast('Operace spuštěna. Průběh vidíš v panelu Průběh operace.');
    pollOperation();
  }catch(e){toast(e.message,true)}
}

async function startLed(mode){
  if(!confirm(`Nastavit LED režim '${mode}' na všech uzlech?`))return;
  return startOperation('/api/led',{mode});
}

async function maintenance(){
  try{
    let r=await fetch('/api/maintenance');let j=await r.json();
    $('maintenanceBox').textContent=JSON.stringify(j,null,2);
  }catch(e){$('maintenanceBox').textContent=e.message}
}

function nodeStatusLabel(status){
  return {
    queued:['○','ČEKÁ'],running:['●','PROBÍHÁ'],done:['✓','HOTOVO'],error:['✕','CHYBA']
  }[status]||['○',String(status||'ČEKÁ').toUpperCase()];
}

function renderOperation(){
  let o=operation||{},running=o.status==='running';
  let percent=Math.max(0,Math.min(100,Number(o.progress)||0));
  $('operationStatusText').textContent=o.title||'Připraveno';
  $('operationPercent').textContent=`${percent} %`;
  $('operationElapsed').textContent=formatElapsed(o.elapsed_seconds||0);
  $('operationBar').style.width=`${percent}%`;
  $('operationBar').className='progressBar '+(o.status||'idle');
  $('operationMessage').textContent=o.message||'Žádná operace neběží.';
  $('operationCard').dataset.status=o.status||'idle';

  let routers=data.routers||[];
  let nodes=o.nodes||{};
  let rows=[];
  for(let r of routers){
    let n=nodes[r.ip];
    if(!n&&o.status==='idle')continue;
    n=n||{status:'queued',detail:'Čeká na spuštění.'};
    let [icon,label]=nodeStatusLabel(n.status);
    rows.push(`<div class="nodeOpRow ${esc(n.status)}"><div class="nodeOpIp">.${esc(r.ip.split('.').pop())}</div><div class="nodeOpName"><b>${esc(r.name)}</b><small>${esc(n.detail||'')}</small></div><div class="nodeOpStatus"><span>${icon}</span> ${label}</div></div>`);
  }
  $('operationNodes').innerHTML=rows.join('')||(o.status==='idle'?'<div class="operationEmpty">Po spuštění operace se zde zobrazí stav jednotlivých routerů.</div>':'');
  $('operationLog').textContent=(o.logs||[]).join('\n')||'Připraveno.';
  $('operationLog').scrollTop=$('operationLog').scrollHeight;
  $('clearOperationButton').disabled=running||o.status==='idle';
  document.querySelectorAll('.opAction').forEach(btn=>btn.disabled=running);
}

async function pollOperation(){
  try{
    let r=await fetch('/api/operation');
    operation=await r.json();
    renderOperation();
    if(operation.status==='done'||operation.status==='error'){
      await fetchStatus();loadLogs();
    }
  }catch(e){}
}

async function clearOperation(){
  try{await post('/api/operation/clear',{});await pollOperation()}catch(e){toast(e.message,true)}
}

async function loadLogs(){
  try{
    let r=await fetch('/api/logs?limit=300');let j=await r.json();
    $('logBox').textContent=(j.logs||[]).join('\n');
    $('logBox').scrollTop=$('logBox').scrollHeight;
  }catch(e){}
}

fetchStatus();pollOperation();loadLogs();
setInterval(fetchStatus,Math.max(15,window.REFRESH_SECONDS||30)*1000);
setInterval(pollOperation,1000);
setInterval(loadLogs,5000);
