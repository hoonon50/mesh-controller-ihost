(() => {
  'use strict';

  let healthByIp = {};
  let injectTimer = null;

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function findNodeCard(ip) {
    const roots = [
      document.querySelector('#topology'),
      document.querySelector('#topologySvg'),
      document.querySelector('.topology'),
      document.querySelector('.topology-wrap'),
      document
    ].filter(Boolean);

    for (const root of roots) {
      const candidates = Array.from(root.querySelectorAll('*')).filter(el => {
        const txt = (el.textContent || '').trim();
        if (!txt.includes(ip) || !txt.includes('ONLINE')) return false;
        if (txt.length > 260) return false;
        if (el.closest && el.closest('#lanPorts, .lan-ports, .ports-grid')) return false;
        return true;
      });

      // Nejmenší element, který obsahuje IP + ONLINE, bývá vlastní dlaždice routeru.
      candidates.sort((a, b) => (a.textContent || '').length - (b.textContent || '').length);
      if (candidates.length) return candidates[0];
    }
    return null;
  }

  function injectHealth() {
    for (const [ip, item] of Object.entries(healthByIp)) {
      const card = findNodeCard(ip);
      if (!card) continue;

      let box = card.querySelector(':scope > .v369-health');
      if (!box) {
        box = document.createElement('div');
        box.className = 'v369-health';
        box.style.marginTop = '4px';
        box.style.paddingTop = '3px';
        box.style.borderTop = '1px solid rgba(255,255,255,.10)';
        box.style.fontSize = '10px';
        box.style.lineHeight = '1.35';
        box.style.color = '#e8e8ec';
        box.style.whiteSpace = 'nowrap';
        box.style.textAlign = 'left';
        card.appendChild(box);
      }

      const temp = item && item.cpu_temp !== null && item.cpu_temp !== undefined
        ? `${esc(item.cpu_temp)} °C`
        : '—';
      const uptime = item && item.uptime ? esc(item.uptime) : '—';

      const wanted =
        `<div><strong style="color:#92929e">CPU</strong> ${temp}</div>` +
        `<div><strong style="color:#92929e">UPTIME</strong> ${uptime}</div>`;
      if (box.innerHTML !== wanted) box.innerHTML = wanted;
    }
  }

  async function loadHealth() {
    try {
      const r = await fetch('/api/v369/router-health', {cache: 'no-store'});
      if (!r.ok) return;
      const data = await r.json();
      healthByIp = {};
      for (const item of (data.routers || [])) {
        if (item && item.ip) healthByIp[item.ip] = item;
      }
      injectHealth();
    } catch (_) {}
  }

  function scheduleInject() {
    if (injectTimer) clearTimeout(injectTimer);
    injectTimer = setTimeout(injectHealth, 120);
  }

  document.addEventListener('DOMContentLoaded', () => {
    loadHealth();
    setInterval(loadHealth, 600000);

    const observer = new MutationObserver((mutations) => {
      // Neodpovídej na vlastní změny CPU/UPTIME boxu – jinak vzniká zbytečná
      // smyčka překreslování, která může působit jako blikání dlaždic.
      const externalChange = mutations.some(m => {
        const target = m.target && m.target.nodeType === 1 ? m.target : null;
        if (target && target.closest && target.closest('.v369-health')) return false;
        return Array.from(m.addedNodes || []).some(n => {
          if (!n || n.nodeType !== 1) return true;
          return !(n.matches?.('.v369-health') || n.closest?.('.v369-health'));
        }) || Array.from(m.removedNodes || []).some(n => {
          if (!n || n.nodeType !== 1) return true;
          return !(n.matches?.('.v369-health') || n.closest?.('.v369-health'));
        });
      });
      if (externalChange) scheduleInject();
    });
    observer.observe(document.body, {subtree: true, childList: true});
  });
})();
