(() => {
  'use strict';
  if (window.__MESH_V505_LIVE_TOPOLOGY__) return;
  window.__MESH_V505_LIVE_TOPOLOGY__ = true;

  const API = '/api/v503/live-topology';
  const REFRESH_MS = 5000;
  const NODE_POS = {
    '192.168.30.1': [50, 50],
    '192.168.30.2': [12, 14],
    '192.168.30.3': [84, 14],
    '192.168.30.4': [84, 84],
    '192.168.30.5': [12, 84]
  };
  // Křivost v px – záměrně rozprostře 10 možných spojů K5 podobně jako původní grafika.
  const CURVE = {
    '1-2': -28, '1-3': 28, '1-4': -24, '1-5': 24,
    '2-3': -56, '3-4': 58, '4-5': 56, '2-5': 58,
    '2-4': -48, '3-5': 48
  };

  let panel = null;
  let stage = null;
  let svg = null;
  let status = null;
  let nodes = new Map();
  let lastPayload = null;
  let polling = false;
  let resizeObserver = null;

  function exactTextElement(text) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if ((n.nodeValue || '').trim().toUpperCase() === text.toUpperCase()) {
        return n.parentElement;
      }
    }
    return null;
  }

  function findTopologyPanel() {
    const heading = exactTextElement('TOPOLOGIE');
    if (!heading) return null;
    let cur = heading.parentElement;
    for (let i = 0; cur && i < 7; i += 1, cur = cur.parentElement) {
      const r = cur.getBoundingClientRect();
      if (r.width > 500 && r.height > 260) return {panel: cur, heading};
    }
    return null;
  }

  function positionStage(heading) {
    if (!panel || !stage || !heading) return;
    const pr = panel.getBoundingClientRect();
    const hr = heading.getBoundingClientRect();
    const top = Math.max(40, Math.round(hr.bottom - pr.top + 9));
    stage.style.left = '12px';
    stage.style.right = '12px';
    stage.style.top = `${top}px`;
    stage.style.bottom = '12px';
  }

  function buildNode(ip, name) {
    const pos = NODE_POS[ip] || [50, 50];
    const el = document.createElement('div');
    el.className = 'v503-node offline';
    el.dataset.ip = ip;
    el.style.left = `${pos[0]}%`;
    el.style.top = `${pos[1]}%`;
    el.innerHTML = `
      <div class="v503-node-name">${name}</div>
      <div class="v503-node-ip">${ip}</div>
      <div class="v503-node-state">ČEKÁM NA DATA</div>
      <div class="v503-node-rule"></div>
      <div class="v503-node-health">
        <div>CPU <b data-k="cpu">—</b></div>
        <div>UPTIME <b data-k="uptime">—</b></div>
      </div>`;
    stage.appendChild(el);
    nodes.set(ip, el);
  }

  function suppressLegacyTopology() {
    if (!panel || !stage) return;
    // Původní renderer může mít vlastní absolutně pozicované uzly nad novou
    // vrstvou. Zvedneme live stage nad celý starý graf a staré karty s IP
    // routerů výslovně označíme jako legacy, aby se jejich CPU/UPTIME
    // nemohly překrývat s živými hodnotami v5.0.4.
    const routerIps = new Set(Object.keys(NODE_POS));
    for (const el of Array.from(panel.querySelectorAll('div,section,article'))) {
      if (el === stage || stage.contains(el)) continue;
      const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (!text) continue;
      let ipHits = 0;
      for (const ip of routerIps) if (text.includes(ip)) ipHits += 1;
      if (ipHits !== 1) continue;
      if (!/CPU/i.test(text) || !/UPTIME/i.test(text)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 90 || r.width > 260 || r.height < 60 || r.height > 190) continue;
      el.classList.add('v504-legacy-topology-node');
    }
  }

  function mount() {
    if (stage && document.body.contains(stage)) return true;
    const found = findTopologyPanel();
    if (!found) return false;
    panel = found.panel;
    panel.classList.add('v503-topology-host');

    stage = document.createElement('div');
    stage.className = 'v503-live-stage';
    stage.id = 'v503LiveTopology';
    stage.innerHTML = '<svg class="v503-live-svg" aria-hidden="true"></svg><div class="v503-live-status">LIVE v5.0.5 · čekám…</div>';
    panel.appendChild(stage);
    svg = stage.querySelector('.v503-live-svg');
    status = stage.querySelector('.v503-live-status');
    positionStage(found.heading);

    buildNode('192.168.30.2', 'MESH1');
    buildNode('192.168.30.3', 'MESH2');
    buildNode('192.168.30.1', 'ROUTER');
    buildNode('192.168.30.5', 'MESH4');
    buildNode('192.168.30.4', 'MESH3');
    suppressLegacyTopology();

    if ('ResizeObserver' in window) {
      resizeObserver = new ResizeObserver(() => {
        positionStage(found.heading);
        if (lastPayload) drawLinks(lastPayload.links || []);
      });
      resizeObserver.observe(panel);
    } else {
      window.addEventListener('resize', () => {
        positionStage(found.heading);
        if (lastPayload) drawLinks(lastPayload.links || []);
      }, {passive: true});
    }
    return true;
  }

  function quality(signal) {
    if (!Number.isFinite(Number(signal))) return 'unknown';
    const s = Number(signal);
    if (s >= -60) return 'good';
    if (s >= -72) return 'mid';
    return 'bad';
  }

  function endpoint(ip) {
    const p = NODE_POS[ip] || [50, 50];
    const w = stage.clientWidth || 1;
    const h = stage.clientHeight || 1;
    return [w * p[0] / 100, h * p[1] / 100];
  }

  function pairKey(a, b) {
    const na = Number(a.split('.').pop());
    const nb = Number(b.split('.').pop());
    return na < nb ? `${na}-${nb}` : `${nb}-${na}`;
  }

  function curveGeometry(a, b) {
    const [x1, y1] = endpoint(a);
    const [x2, y2] = endpoint(b);
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.max(1, Math.hypot(dx, dy));
    const off = CURVE[pairKey(a, b)] || 0;
    const nx = -dy / len;
    const ny = dx / len;
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    const cx = mx + nx * off;
    const cy = my + ny * off;
    // Label posuneme trochu blíž ke kontrolnímu bodu, ale ne úplně na něj.
    const lx = mx + nx * off * 0.72;
    const ly = my + ny * off * 0.72;
    return {x1, y1, x2, y2, cx, cy, lx, ly};
  }

  function drawLinks(links) {
    if (!stage || !svg) return;
    svg.innerHTML = '';
    stage.querySelectorAll('.v503-link-label').forEach(el => el.remove());
    for (const link of links) {
      if (!NODE_POS[link.a] || !NODE_POS[link.b]) continue;
      const q = quality(link.signal_dbm);
      const g = curveGeometry(link.a, link.b);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', `M ${g.x1.toFixed(1)} ${g.y1.toFixed(1)} Q ${g.cx.toFixed(1)} ${g.cy.toFixed(1)} ${g.x2.toFixed(1)} ${g.y2.toFixed(1)}`);
      path.setAttribute('class', `v503-live-link v503-link-${q}`);
      svg.appendChild(path);

      const label = document.createElement('div');
      label.className = `v503-link-label ${q}`;
      label.style.left = `${g.lx}px`;
      label.style.top = `${g.ly}px`;
      const sig = Number.isFinite(Number(link.signal_dbm)) ? `${Number(link.signal_dbm)} dBm` : '— dBm';
      const speed = Number.isFinite(Number(link.speed_mbps)) ? `${Number(link.speed_mbps).toFixed(1)} Mbit/s` : '— Mbit/s';
      label.innerHTML = `<span class="sig">${sig}</span><span>${speed}</span>`;
      stage.appendChild(label);
    }
  }

  function updateNode(data) {
    const el = nodes.get(data.ip);
    if (!el) return;
    el.classList.toggle('offline', !data.online);
    el.classList.toggle('stale', !!data.stale);
    const state = el.querySelector('.v503-node-state');
    if (state) state.textContent = data.online ? `ONLINE · ${Number(data.clients || 0)} klientů` : 'OFFLINE';
    const cpu = el.querySelector('[data-k="cpu"]');
    if (cpu) cpu.textContent = data.online && Number.isFinite(Number(data.cpu_c)) ? `${Number(data.cpu_c)} °C` : '—';
    const up = el.querySelector('[data-k="uptime"]');
    if (up) up.textContent = data.online ? (data.uptime || '—') : '—';
    const title = el.querySelector('.v503-node-name');
    if (title) title.textContent = data.name || data.hostname || data.ip;
    el.title = data.online
      ? `${data.ip} · 2.4 GHz ${data.clients_24 || 0} · 5 GHz ${data.clients_5 || 0} · LAN ${data.lan_clients || 0}`
      : `${data.ip} · ${data.error || 'SSH nedostupné'}`;
  }

  function metricLeaf(labelText) {
    const label = exactTextElement(labelText);
    if (!label) return null;
    let box = label.parentElement;
    for (let i = 0; box && i < 5; i += 1, box = box.parentElement) {
      const r = box.getBoundingClientRect();
      if (r.width >= 100 && r.width <= 420 && r.height >= 42 && r.height <= 110) {
        const leaves = Array.from(box.querySelectorAll('*')).filter(el => {
          if (el.children.length) return false;
          const t = (el.textContent || '').trim();
          if (!t || t.toUpperCase() === labelText.toUpperCase() || t.length > 24) return false;
          const fs = parseFloat(getComputedStyle(el).fontSize || '0');
          return fs >= 13;
        });
        if (leaves.length) {
          leaves.sort((a, b) => parseFloat(getComputedStyle(b).fontSize) - parseFloat(getComputedStyle(a).fontSize));
          return leaves[0];
        }
      }
    }
    return null;
  }

  function mountIhostTile() {
    let tile = document.getElementById('v505IhostTile');
    if (tile && document.body.contains(tile)) return tile;
    const wrap = document.querySelector('.wan-usage-wrap');
    if (!wrap) return null;
    wrap.classList.add('v505-with-ihost');
    tile = document.createElement('div');
    tile.id = 'v505IhostTile';
    tile.className = 'wan-usage-tile v505-ihost-tile';
    tile.title = 'SONOFF iHost · systémové využití Docker hostu';
    tile.innerHTML = `
      <div class="wan-usage-tile-head v505-ihost-head"><span>iHOST</span></div>
      <div class="v505-ihost-values">
        <span>CPU <b data-v505="cpu">—</b></span>
        <span>RAM <b data-v505="ram">—</b></span>
        <span>TEMP <b data-v505="temp">—</b></span>
      </div>`;
    wrap.prepend(tile);
    return tile;
  }

  function updateIhost(stats) {
    const tile = mountIhostTile();
    if (!tile) return;
    const cpu = tile.querySelector('[data-v505="cpu"]');
    const ram = tile.querySelector('[data-v505="ram"]');
    const temp = tile.querySelector('[data-v505="temp"]');
    const cpuVal = Number(stats && stats.cpu_percent);
    const ramVal = Number(stats && stats.ram_percent);
    const tempVal = Number(stats && stats.temp_c);
    if (cpu) cpu.textContent = Number.isFinite(cpuVal) ? `${cpuVal}%` : '—';
    if (ram) ram.textContent = Number.isFinite(ramVal) ? `${ramVal}%` : '—';
    if (temp) temp.textContent = Number.isFinite(tempVal) ? `${tempVal}°C` : '—';
  }

  function updateMetrics(summary, clock) {
    const values = {
      'ONLINE ROUTERY': `${summary.online_routers || 0} / ${summary.router_count || 5}`,
      'MESH SPOJE': String(summary.mesh_links || 0),
      'KLIENTI': String(summary.clients || 0),
      '5 GHZ': String(summary.clients_5 || 0),
      '2.4 GHZ': String(summary.clients_24 || 0),
      '2,4 GHZ': String(summary.clients_24 || 0),
      'OBNOVENO': clock || ''
    };
    for (const [label, value] of Object.entries(values)) {
      const leaf = metricLeaf(label);
      if (leaf) leaf.textContent = value;
    }
  }

  function render(payload) {
    if (!mount()) return;
    lastPayload = payload;
    for (const node of (payload.nodes || [])) updateNode(node);
    drawLinks(payload.links || []);
    updateMetrics(payload.summary || {}, payload.clock || '');
    updateIhost(payload.ihost || {});
    if (status) {
      status.className = `v503-live-status ${payload.ok ? 'ok' : 'error'}`;
      status.textContent = payload.ok
        ? `LIVE v5.0.5 · ${payload.clock || ''} · #${payload.sequence || 0}`
        : `LIVE v5.0.5 · čekám na routery`;
      status.title = `Backend vzorek ${payload.sample_duration_ms || 0} ms · polling ${payload.poll_seconds || 5} s`;
    }
  }

  async function refresh() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(`${API}?_=${Date.now()}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (err) {
      if (status) {
        status.className = 'v503-live-status error';
        status.textContent = 'LIVE v5.0.5 · API nedostupné';
        status.title = String(err);
      }
    } finally {
      polling = false;
    }
  }

  function boot(retries = 40) {
    if (mount()) {
      refresh();
      window.setInterval(refresh, REFRESH_MS);
      return;
    }
    if (retries > 0) window.setTimeout(() => boot(retries - 1), 250);
  }

  document.addEventListener('DOMContentLoaded', () => boot(), {once: true});
})();
