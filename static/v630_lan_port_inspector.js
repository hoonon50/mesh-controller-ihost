(() => {
  'use strict';
  if (window.__MESH_V630_LAN_PORT_INSPECTOR__) return;
  window.__MESH_V630_LAN_PORT_INSPECTOR__ = true;

  const API = '/api/v630/lan-port-devices';
  const SINGLE_CLICK_DELAY = 420;
  let clickTimer = null;
  let requestSeq = 0;
  let panel = null;

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function normalizePort(value) {
    const m = String(value || '').trim().match(/^LAN([1-4])$/i);
    return m ? `lan${m[1]}` : '';
  }

  function tileInfo(tile) {
    if (!tile) return null;
    const section = tile.closest('.router-ports');
    if (!section) return null;
    const ip = (section.querySelector('.router-ports-head span')?.textContent || '').trim();
    const port = normalizePort(tile.querySelector('strong')?.textContent || '');
    if (!/^192\.168\.30\.[1-5]$/.test(ip) || !port) return null;
    const routerName = (section.querySelector('.router-ports-head strong')?.textContent || ip).trim();
    const speed = (tile.querySelector(':scope > span')?.textContent || '—').trim();
    return {ip, port, routerName, speed};
  }

  function tileInspectable(tile) {
    if (!tile || tile.classList.contains('v620-port-blocked')) return false;
    const status = (tile.querySelector(':scope > b')?.textContent || '').trim().toUpperCase();
    return status === 'UP';
  }

  function cancelSingleClick() {
    if (clickTimer) clearTimeout(clickTimer);
    clickTimer = null;
  }

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return panel;
    panel = document.createElement('div');
    panel.id = 'v630LanInspector';
    panel.className = 'v630-lan-inspector';
    panel.hidden = true;
    panel.innerHTML = `
      <div class="v630-inspector-head">
        <div>
          <strong data-k="title">LAN PORT</strong>
          <span data-k="subtitle">—</span>
        </div>
        <button type="button" class="v630-inspector-close" aria-label="Zavřít">×</button>
      </div>
      <div class="v630-inspector-body" data-k="body"></div>`;
    document.body.appendChild(panel);
    panel.querySelector('.v630-inspector-close')?.addEventListener('click', closePanel);
    return panel;
  }

  function closePanel() {
    requestSeq += 1;
    if (panel) panel.hidden = true;
  }

  function positionPanel(tile) {
    if (!panel || !tile) return;
    const rect = tile.getBoundingClientRect();
    const width = Math.min(390, Math.max(300, window.innerWidth - 24));
    panel.style.width = `${width}px`;
    panel.style.left = '0px';
    panel.style.top = '0px';
    panel.hidden = false;
    const measured = panel.getBoundingClientRect();
    let left = rect.left + rect.width / 2 - measured.width / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - measured.width - 12));
    let top = rect.bottom + 9;
    if (top + measured.height > window.innerHeight - 12) top = Math.max(12, rect.top - measured.height - 9);
    panel.style.left = `${Math.round(left)}px`;
    panel.style.top = `${Math.round(top)}px`;
  }

  function renderDevices(data) {
    const body = panel?.querySelector('[data-k="body"]');
    if (!body) return;
    const devices = Array.isArray(data.devices) ? data.devices : [];
    const speed = data.speed_mbps ? `${data.speed_mbps} Mbit/s` : (data.up ? 'RYCHLOST ?' : '—');
    if (!devices.length) {
      body.innerHTML = '<div class="v630-inspector-empty"><strong>Žádné zařízení</strong><span>Na tomto fyzickém portu není nyní nalezena žádná klientská MAC/IP.</span></div>';
      return;
    }
    body.innerHTML = `
      <div class="v630-device-summary"><span>${devices.length} zařízení</span><b>${esc(speed)}</b></div>
      <div class="v630-device-list">
        ${devices.map(device => `
          <div class="v630-device-row">
            <div class="v630-device-main">
              <strong>${esc(device.ip || 'IP neznámá')}</strong>
              <span>${esc(device.hostname || 'hostname neznámý')}</span>
            </div>
            <code>${esc(device.mac || '—')}</code>
          </div>`).join('')}
      </div>`;
  }

  async function openFor(tile) {
    if (!document.body.contains(tile) || !tileInspectable(tile)) return;
    const info = tileInfo(tile);
    if (!info) return;
    const seq = ++requestSeq;
    const p = ensurePanel();
    const title = p.querySelector('[data-k="title"]');
    const subtitle = p.querySelector('[data-k="subtitle"]');
    const body = p.querySelector('[data-k="body"]');
    if (title) title.textContent = `${info.routerName} · ${info.port.toUpperCase()}`;
    if (subtitle) subtitle.textContent = `${info.ip} · ${info.speed}`;
    if (body) body.innerHTML = '<div class="v630-inspector-loading">Načítám zařízení…</div>';
    positionPanel(tile);

    try {
      const url = `${API}?ip=${encodeURIComponent(info.ip)}&port=${encodeURIComponent(info.port)}`;
      const response = await fetch(url, {cache: 'no-store'});
      const data = await response.json().catch(() => ({}));
      if (seq !== requestSeq) return;
      if (!response.ok || !data.ok) throw new Error(data.error || 'Zařízení na portu se nepodařilo načíst.');
      if (!data.up) {
        closePanel();
        return;
      }
      renderDevices(data);
      positionPanel(tile);
    } catch (err) {
      if (seq !== requestSeq) return;
      if (body) body.innerHTML = `<div class="v630-inspector-error"><strong>Nelze načíst port</strong><span>${esc(err.message || 'Neznámá chyba')}</span></div>`;
      positionPanel(tile);
    }
  }

  document.addEventListener('click', event => {
    const tile = event.target.closest?.('.router-ports .port-tile');
    if (tile) {
      if (!tileInspectable(tile)) {
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
        openFor(tile);
      }, SINGLE_CLICK_DELAY);
      return;
    }
    if (event.target.closest?.('#v630LanInspector')) return;
    cancelSingleClick();
    closePanel();
  }, true);

  document.addEventListener('dblclick', event => {
    const tile = event.target.closest?.('.router-ports .port-tile');
    if (!tile) return;
    cancelSingleClick();
    closePanel();
  }, true);

  window.addEventListener('resize', closePanel, {passive: true});
  window.addEventListener('scroll', event => {
    if (event.target?.closest?.('#v630LanInspector')) return;
    closePanel();
  }, {passive: true, capture: true});
})();
