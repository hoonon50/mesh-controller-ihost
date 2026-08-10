(() => {
  'use strict';

  const API = '/api/wan-usage';
  const REFRESH_MS = 30000;

  function formatTraffic(bytes) {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n < 0) return '—';
    const gb = n / 1_000_000_000;
    if (gb >= 1000) return `${(gb / 1000).toFixed(2)} TB`;
    return `${gb.toFixed(2)} GB`;
  }

  function findHeader() {
    const candidates = Array.from(document.querySelectorAll('header, .header, .topbar, .top-bar, .brand, [class*="header"], body > div'));
    for (const el of candidates) {
      if ((el.textContent || '').includes('OpenWRT MESH CONTROLLER PRO')) return el;
    }
    const textNode = Array.from(document.querySelectorAll('h1, h2, h3, strong, div, span'))
      .find(el => (el.textContent || '').trim().includes('OpenWRT MESH CONTROLLER PRO'));
    if (!textNode) return null;
    return textNode.parentElement || textNode;
  }

  function makeTile(label, icon, id, kind) {
    const tile = document.createElement('div');
    tile.className = `wan-usage-tile wan-usage-${kind}`;
    tile.innerHTML = `
      <div class="wan-usage-tile-head"><span class="wan-usage-icon">${icon}</span><span>${label}</span></div>
      <div class="wan-usage-value" id="${id}">0.00 GB</div>
      <div class="wan-usage-note">WAN · ROUTER .1</div>`;
    return tile;
  }

  function mount() {
    if (document.getElementById('wanUsageTiles')) return true;
    const header = findHeader();
    if (!header) return false;

    header.classList.add('wan-header-enhanced');
    const wrap = document.createElement('div');
    wrap.id = 'wanUsageTiles';
    wrap.className = 'wan-usage-wrap';
    wrap.appendChild(makeTile('DOWNLOAD', '↓', 'wanDownloadValue', 'download'));
    wrap.appendChild(makeTile('UPLOAD', '↑', 'wanUploadValue', 'upload'));
    header.appendChild(wrap);
    return true;
  }

  async function refresh() {
    if (!mount()) return;
    const d = document.getElementById('wanDownloadValue');
    const u = document.getElementById('wanUploadValue');
    const wrap = document.getElementById('wanUsageTiles');
    try {
      const response = await fetch(API, {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (d) d.textContent = formatTraffic(data.download_bytes);
      if (u) u.textContent = formatTraffic(data.upload_bytes);
      if (wrap) {
        wrap.classList.toggle('wan-usage-stale', !data.ok);
        const detail = data.ok
          ? `WAN ${data.wan_device || ''} · aktualizováno ${data.updated_at || ''}`
          : `Poslední součet zachován · ${data.error || 'router momentálně nedostupný'}`;
        wrap.title = detail;
      }
    } catch (err) {
      if (wrap) {
        wrap.classList.add('wan-usage-stale');
        wrap.title = `WAN statistika je dočasně nedostupná: ${err}`;
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    mount();
    refresh();
    window.setInterval(refresh, REFRESH_MS);
  }, {once: true});
})();
