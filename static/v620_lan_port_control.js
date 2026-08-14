(() => {
  'use strict';
  if (window.__MESH_V620_LAN_PORT_CONTROL__) return;
  window.__MESH_V620_LAN_PORT_CONTROL__ = true;

  const API = '/api/v620/lan-ports';
  const POLL_MS = 5000;
  let state = {blocked: {}, protected: {}};
  let loading = false;

  function normalizePort(value) {
    const m = String(value || '').trim().match(/^LAN([1-4])$/i);
    return m ? `lan${m[1]}` : '';
  }

  function isBlocked(ip, port) {
    return Array.isArray(state.blocked?.[ip]) && state.blocked[ip].includes(port);
  }

  function protectedNames(ip, port) {
    const names = state.protected?.[ip]?.[port];
    return Array.isArray(names) ? names.filter(Boolean) : [];
  }

  function tileInfo(tile) {
    if (!tile) return null;
    const section = tile.closest('.router-ports');
    if (!section) return null;
    const ip = (section.querySelector('.router-ports-head span')?.textContent || '').trim();
    const port = normalizePort(tile.querySelector('strong')?.textContent || '');
    if (!/^192\.168\.30\.[1-5]$/.test(ip) || !port) return null;
    return {ip, port};
  }

  function decorate() {
    document.querySelectorAll('.router-ports .port-tile').forEach(tile => {
      const info = tileInfo(tile);
      if (!info) return;
      const blocked = isBlocked(info.ip, info.port);
      const protectedBy = protectedNames(info.ip, info.port);
      tile.dataset.v620Ip = info.ip;
      tile.dataset.v620Port = info.port;
      tile.classList.toggle('v620-port-blocked', blocked);
      tile.classList.toggle('v620-port-protected', protectedBy.length > 0);

      const wantedBadge = blocked ? 'BLOKOVÁN' : (protectedBy.length ? `CHRÁNĚN · ${protectedBy.join(' + ')}` : '');
      let badge = tile.querySelector('.v620-port-badge');
      if (wantedBadge) {
        if (!badge) {
          badge = document.createElement('div');
          badge.className = 'v620-port-badge';
          tile.appendChild(badge);
        }
        if (badge.textContent !== wantedBadge) badge.textContent = wantedBadge;
      } else if (badge) {
        badge.remove();
      }

      const status = tile.querySelector(':scope > b');
      if (status) {
        if (!status.dataset.v620Original) status.dataset.v620Original = status.textContent || '';
        const wantedStatus = blocked ? 'BLOKOVÁN' : status.dataset.v620Original;
        if (status.textContent !== wantedStatus) status.textContent = wantedStatus;
      }

      if (blocked) {
        tile.title = `${info.ip} / ${info.port.toUpperCase()} · dvojklik = povolit port`;
      } else if (protectedBy.length) {
        tile.title = `${info.ip} / ${info.port.toUpperCase()} · chráněný port: ${protectedBy.join(', ')}`;
      } else {
        tile.title = `${info.ip} / ${info.port.toUpperCase()} · dvojklik = zablokovat port`;
      }
    });
  }

  async function loadState() {
    if (loading) return;
    loading = true;
    try {
      const response = await fetch(API, {cache: 'no-store'});
      if (!response.ok) throw new Error(await response.text());
      state = await response.json();
      decorate();
    } catch (err) {
      console.error('v6.2.0 LAN port state:', err);
    } finally {
      loading = false;
    }
  }

  async function toggle(tile) {
    const info = tileInfo(tile);
    if (!info) return;
    const protectedBy = protectedNames(info.ip, info.port);
    const blocked = isBlocked(info.ip, info.port);

    if (!blocked && protectedBy.length) {
      alert(`Port ${info.port.toUpperCase()} nelze zablokovat.\n\nChráněné zařízení: ${protectedBy.join(', ')}`);
      return;
    }

    const next = !blocked;
    const question = next
      ? `Zablokovat ${info.port.toUpperCase()} na ${info.ip}?\n\nPort bude vypnut pouze runtime. OpenWrt konfigurace se nezmění a Controller blokaci po restartu routeru znovu aplikuje.`
      : `Povolit ${info.port.toUpperCase()} na ${info.ip}?`;
    if (!confirm(question)) return;

    tile.classList.add('v620-port-working');
    try {
      const response = await fetch(API, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ip: info.ip, port: info.port, blocked: next}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        throw new Error(data.error || 'Změnu LAN portu se nepodařilo provést.');
      }
      await loadState();
      try { await fetch('/api/refresh', {method: 'POST'}); } catch (_err) {}
    } catch (err) {
      alert(err.message || 'Změnu LAN portu se nepodařilo provést.');
      await loadState();
    } finally {
      tile.classList.remove('v620-port-working');
    }
  }

  document.addEventListener('dblclick', event => {
    const tile = event.target.closest?.('.router-ports .port-tile');
    if (!tile) return;
    event.preventDefault();
    event.stopPropagation();
    toggle(tile);
  }, true);

  const observer = new MutationObserver(() => decorate());
  const start = () => {
    const grid = document.getElementById('portsGrid');
    if (grid) observer.observe(grid, {childList: true, subtree: true});
    loadState();
    setInterval(loadState, POLL_MS);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
