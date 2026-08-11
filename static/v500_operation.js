(() => {
  'use strict';
  if (window.__MESH_V500_OPERATION__) return;
  window.__MESH_V500_OPERATION__ = true;

  const API = '/api/v500/operation';
  let starting = false;

  async function api(path, options={}) {
    const opts = {cache:'no-store', ...options};
    if (opts.body && !opts.headers) opts.headers = {'Content-Type':'application/json'};
    const response = await fetch(path, opts);
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok || data.ok === false) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    return data;
  }

  function normalize(text) {
    return (text || '').replace(/\s+/g, ' ').trim().toUpperCase();
  }

  function isRebootButton(btn) {
    const t = normalize(btn.textContent);
    return t === 'REBOOT' || t === 'RESTART VŠECH' || t === 'RESTART VŠECH ROUTERŮ' || t === 'RESTARTOVAT VŠECHNY ROUTERY';
  }

  function isOwutUpgradeButton(btn) {
    const t = normalize(btn.textContent);
    if (!t.includes('OWUT')) return false;
    if (t.includes('KONTROLA') || t.includes('CHECK')) return false;
    return t.includes('AKTUALIZACE') || t.includes('UPGRADE') || t.includes('SYSUPGRADE');
  }

  async function start(path) {
    if (starting) return;
    starting = true;
    try {
      await api(path, {method:'POST', body:'{}'});
      await refresh();
    } catch (err) {
      console.error('v5 operation start:', err);
    } finally {
      starting = false;
    }
  }

  // Capture fáze zastaví staré onclick/fetch handlery a pošle akci do v5 manageru.
  document.addEventListener('click', (event) => {
    const btn = event.target.closest && event.target.closest('button');
    if (!btn) return;
    if (isRebootButton(btn)) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      start('/api/v500/reboot');
      return;
    }
    if (isOwutUpgradeButton(btn)) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      start('/api/v500/owut');
    }
  }, true);

  function findOperationPanel() {
    const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,strong,b,div,span'));
    for (const node of nodes) {
      const text = normalize(node.textContent);
      if (text !== 'PRŮBĚH OPERACE' && text !== 'PRUBEH OPERACE') continue;
      let p = node.parentElement;
      for (let i=0; p && i<6; i++, p=p.parentElement) {
        const r = p.getBoundingClientRect();
        if (r.width > 320 && r.height > 180) return p;
      }
    }
    return null;
  }

  function ensurePanel() {
    if (document.getElementById('v500OperationCard')) return document.getElementById('v500OperationCard');
    const host = findOperationPanel();
    if (!host) return null;
    const card = document.createElement('div');
    card.id = 'v500OperationCard';
    card.className = 'v500-operation-card';
    card.innerHTML = `
      <div class="v500-op-head">
        <div><b>OPERATION MANAGER</b><span class="v500-version">v5.0.1</span></div>
        <div class="v500-op-actions">
          <button id="v500ResumeBtn" type="button">POKRAČOVAT</button>
          <button id="v500CancelBtn" type="button">ZASTAVIT</button>
        </div>
      </div>
      <div class="v500-op-status"><span id="v500OpState">PŘIPRAVENO</span><span id="v500OpPct">0 %</span></div>
      <div class="v500-op-bar"><i id="v500OpBar"></i></div>
      <div class="v500-op-message" id="v500OpMessage">Připraveno</div>
      <div class="v500-op-nodes" id="v500OpNodes"></div>`;
    host.appendChild(card);
    card.querySelector('#v500ResumeBtn').addEventListener('click', async (e) => {
      e.preventDefault(); e.stopPropagation();
      try { await api('/api/v500/resume', {method:'POST', body:'{}'}); } catch (err) { console.error(err); }
      refresh();
    });
    card.querySelector('#v500CancelBtn').addEventListener('click', async (e) => {
      e.preventDefault(); e.stopPropagation();
      try { await api('/api/v500/cancel', {method:'POST', body:'{}'}); } catch (err) { console.error(err); }
      refresh();
    });
    return card;
  }

  function nodeLabel(row) {
    const s = normalize(row.status);
    if (s === 'DONE' || s === 'ONLINE') return 'HOTOVO';
    if (s === 'NO_UPDATE') return 'BEZ UPDATE';
    if (s.includes('WAIT')) return 'ČEKÁM';
    if (s === 'ERROR' || s === 'PAUSED') return 'CHYBA';
    if (s === 'PENDING') return 'ČEKÁ';
    return s || 'ČEKÁ';
  }

  function render(state) {
    const card = ensurePanel();
    if (!card || !state) return;
    const pct = Math.max(0, Math.min(100, Number(state.progress || 0)));
    const status = normalize(state.status || 'idle');
    card.dataset.status = status.toLowerCase();
    card.querySelector('#v500OpState').textContent = `${normalize(state.kind || 'PŘIPRAVENO')} · ${status}`;
    card.querySelector('#v500OpPct').textContent = `${pct} %`;
    card.querySelector('#v500OpBar').style.width = `${pct}%`;
    card.querySelector('#v500OpMessage').textContent = state.message || 'Připraveno';
    const nodes = card.querySelector('#v500OpNodes');
    nodes.innerHTML = '';
    for (const row of (state.nodes || [])) {
      const el = document.createElement('div');
      el.className = `v500-node v500-node-${String(row.status || 'pending').toLowerCase()}`;
      el.innerHTML = `<b>${row.name || ''}</b><span>${row.ip || ''}</span><em>${nodeLabel(row)}</em>`;
      nodes.appendChild(el);
    }
    const resume = card.querySelector('#v500ResumeBtn');
    const cancel = card.querySelector('#v500CancelBtn');
    resume.style.display = status === 'PAUSED' || status === 'ERROR' ? '' : 'none';
    cancel.style.display = status === 'RUNNING' || status === 'WAITING' || status === 'PAUSED' ? '' : 'none';
  }

  async function refresh() {
    try {
      const data = await api(API);
      render(data.state);
    } catch (err) {
      const card = ensurePanel();
      if (card) card.querySelector('#v500OpMessage').textContent = 'Operation Manager dočasně nedostupný';
    }
  }

  function boot(retries=30) {
    if (ensurePanel()) {
      refresh();
      setInterval(refresh, 2000);
      return;
    }
    if (retries > 0) setTimeout(() => boot(retries-1), 250);
  }
  document.addEventListener('DOMContentLoaded', () => boot(), {once:true});
})();
