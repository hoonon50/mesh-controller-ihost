(() => {
  'use strict';
  if (window.__MESH_V631_TOPOLOGY_INSPECTOR__) return;
  window.__MESH_V631_TOPOLOGY_INSPECTOR__ = true;

  const API = '/api/v631/topology-node-devices';
  const SINGLE_CLICK_DELAY = 320;
  let clickTimer = null;
  let requestSeq = 0;
  let panel = null;

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function cancelSingleClick() {
    if (clickTimer) clearTimeout(clickTimer);
    clickTimer = null;
  }

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return panel;
    panel = document.createElement('div');
    panel.id = 'v631TopologyInspector';
    panel.className = 'v631-topology-inspector';
    panel.hidden = true;
    panel.innerHTML = `
      <div class="v631-inspector-head">
        <div>
          <strong data-k="title">TOPOLOGIE</strong>
          <span data-k="subtitle">—</span>
        </div>
        <button type="button" class="v631-inspector-close" aria-label="Zavřít">×</button>
      </div>
      <div class="v631-inspector-body" data-k="body"></div>`;
    document.body.appendChild(panel);
    panel.querySelector('.v631-inspector-close')?.addEventListener('click', closePanel);
    return panel;
  }

  function closePanel() {
    requestSeq += 1;
    if (panel) panel.hidden = true;
  }

  function positionPanel(node) {
    if (!panel || !node) return;
    const rect = node.getBoundingClientRect();
    const width = Math.min(410, Math.max(310, window.innerWidth - 24));
    panel.style.width = `${width}px`;
    panel.style.left = '0px';
    panel.style.top = '0px';
    panel.hidden = false;
    const measured = panel.getBoundingClientRect();
    let left = rect.left + rect.width / 2 - measured.width / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - measured.width - 12));
    let top = rect.bottom + 9;
    if (top + measured.height > window.innerHeight - 12) {
      top = Math.max(12, rect.top - measured.height - 9);
    }
    panel.style.left = `${Math.round(left)}px`;
    panel.style.top = `${Math.round(top)}px`;
  }

  function renderGroups(data) {
    const body = panel?.querySelector('[data-k="body"]');
    if (!body) return;
    if (data.online === false) {
      body.innerHTML = '<div class="v631-inspector-empty"><strong>Router je OFFLINE</strong><span>Klienty nyní nelze načíst.</span></div>';
      return;
    }

    const groups = Array.isArray(data.groups) ? data.groups.filter(g => Array.isArray(g.devices) && g.devices.length) : [];
    if (!groups.length) {
      body.innerHTML = '<div class="v631-inspector-empty"><strong>Žádní klienti</strong><span>Na tomto uzlu nejsou nyní nalezena žádná zařízení.</span></div>';
      return;
    }

    body.innerHTML = `
      <div class="v631-total">CELKEM <b>${Number(data.count || 0)}</b></div>
      ${groups.map(group => `
        <section class="v631-device-group">
          <div class="v631-group-head">
            <strong>${esc(group.label || '')}</strong>
            <span>${Number(group.count || group.devices.length)}</span>
          </div>
          <div class="v631-device-list">
            ${group.devices.map(device => `
              <div class="v631-device-row">
                <div class="v631-device-main">
                  <strong>${esc(device.ip || 'IP neznámá')}</strong>
                  <span>${esc(device.hostname || 'hostname neznámý')}</span>
                </div>
                <code>${esc(device.mac || '—')}</code>
              </div>`).join('')}
          </div>
        </section>`).join('')}`;
  }

  async function openFor(node) {
    if (!document.body.contains(node) || node.classList.contains('offline')) return;
    const ip = String(node.dataset.ip || '').trim();
    if (!/^192\.168\.30\.[1-5]$/.test(ip)) return;
    const name = (node.querySelector('.v503-node-name')?.textContent || ip).trim();
    const seq = ++requestSeq;
    const p = ensurePanel();
    const title = p.querySelector('[data-k="title"]');
    const subtitle = p.querySelector('[data-k="subtitle"]');
    const body = p.querySelector('[data-k="body"]');
    if (title) title.textContent = name;
    if (subtitle) subtitle.textContent = ip;
    if (body) body.innerHTML = '<div class="v631-inspector-loading">Načítám klienty…</div>';
    positionPanel(node);

    try {
      const response = await fetch(`${API}?ip=${encodeURIComponent(ip)}`, {cache: 'no-store'});
      const data = await response.json().catch(() => ({}));
      if (seq !== requestSeq) return;
      if (!response.ok || !data.ok) throw new Error(data.error || 'Klienty uzlu se nepodařilo načíst.');
      if (title) title.textContent = data.router_name || name;
      renderGroups(data);
      positionPanel(node);
    } catch (err) {
      if (seq !== requestSeq) return;
      if (body) body.innerHTML = `<div class="v631-inspector-error"><strong>Nelze načíst klienty</strong><span>${esc(err.message || 'Neznámá chyba')}</span></div>`;
      positionPanel(node);
    }
  }

  document.addEventListener('click', event => {
    const node = event.target.closest?.('.v503-node[data-ip]');
    if (node) {
      if (node.classList.contains('offline')) {
        cancelSingleClick();
        closePanel();
        return;
      }
      if (Number(event.detail || 1) >= 2) {
        cancelSingleClick();
        return;
      }
      cancelSingleClick();
      clickTimer = setTimeout(() => {
        clickTimer = null;
        openFor(node);
      }, SINGLE_CLICK_DELAY);
      return;
    }
    if (event.target.closest?.('#v631TopologyInspector')) return;
    cancelSingleClick();
    closePanel();
  }, true);

  document.addEventListener('dblclick', event => {
    const node = event.target.closest?.('.v503-node[data-ip]');
    if (!node) return;
    cancelSingleClick();
    closePanel();
  }, true);

  window.addEventListener('resize', closePanel, {passive: true});
  window.addEventListener('scroll', event => {
    if (event.target?.closest?.('#v631TopologyInspector')) return;
    closePanel();
  }, {passive: true, capture: true});
})();
