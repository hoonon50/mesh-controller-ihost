(() => {
  'use strict';

  // Poslední známé hodnoty držíme v JS paměti. Běžný 5s refresh topologie
  // je nesmí shodit – CPU/UPTIME se fyzicky načítá jen jednou za 10 minut.
  const ROUTER_IPS = [
    '192.168.30.1',
    '192.168.30.2',
    '192.168.30.3',
    '192.168.30.4',
    '192.168.30.5'
  ];

  const healthByIp = Object.fromEntries(
    ROUTER_IPS.map(ip => [ip, {ip, cpu_temp: null, uptime: null}])
  );

  let injecting = false;

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
        if (txt.length > 300) return false;
        if (el.closest && el.closest('#lanPorts, .lan-ports, .ports-grid')) return false;
        return true;
      });

      candidates.sort((a, b) => (a.textContent || '').length - (b.textContent || '').length);
      if (candidates.length) return candidates[0];
    }
    return null;
  }

  function healthHtml(item) {
    const temp = item && item.cpu_temp !== null && item.cpu_temp !== undefined
      ? `${esc(item.cpu_temp)} °C`
      : '—';
    const uptime = item && item.uptime ? esc(item.uptime) : '—';

    return (
      `<div><strong>CPU</strong> ${temp}</div>` +
      `<div><strong>UPTIME</strong> ${uptime}</div>`
    );
  }

  function ensureHealthBox(card, item) {
    if (!card) return;

    // Pevný prostor = dlaždice se při normálním refreshi nesmrští a znovu
    // neroztáhne. Hodnoty se jen přepíší uvnitř stejného prostoru.
    card.classList.add('v369-health-card');

    let box = card.querySelector(':scope > .v369-health');
    if (!box) {
      box = document.createElement('div');
      box.className = 'v369-health';
      card.appendChild(box);
    }

    const wanted = healthHtml(item);
    if (box.innerHTML !== wanted) box.innerHTML = wanted;
  }

  function injectHealth() {
    if (injecting) return;
    injecting = true;
    try {
      for (const ip of ROUTER_IPS) {
        const card = findNodeCard(ip);
        if (!card) continue;
        ensureHealthBox(card, healthByIp[ip]);
      }
    } finally {
      injecting = false;
    }
  }

  async function loadHealth() {
    try {
      const r = await fetch('/api/v369/router-health', {cache: 'no-store'});
      if (!r.ok) return;
      const data = await r.json();
      for (const item of (data.routers || [])) {
        if (!item || !item.ip || !healthByIp[item.ip]) continue;

        // Když jeden 10min dotaz selže, zachováme poslední známou hodnotu.
        // Nevracíme dlaždici zpět na prázdný stav.
        if (item.cpu_temp !== null && item.cpu_temp !== undefined) {
          healthByIp[item.ip].cpu_temp = item.cpu_temp;
        }
        if (item.uptime) healthByIp[item.ip].uptime = item.uptime;
      }
      injectHealth();
    } catch (_) {
      // Síťová chyba nesmí odstranit poslední hodnoty z dlaždic.
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    // Rezervujeme prostor okamžitě, ještě před prvním SSH výsledkem.
    injectHealth();
    loadHealth();

    // Skutečný health refresh: 10 minut.
    setInterval(loadHealth, 600000);

    // Hlavní aplikace překresluje topologii každých 5 sekund. MutationObserver běží
    // ještě před vykreslením dalšího frame, proto hodnoty vložíme PŘÍMO,
    // bez předchozí 120ms prodlevy a bez viditelného bliknutí.
    const observer = new MutationObserver((mutations) => {
      if (injecting) return;
      const externalChange = mutations.some(m => {
        const target = m.target && m.target.nodeType === 1 ? m.target : null;
        if (target && target.closest && target.closest('.v369-health')) return false;

        const changed = [...(m.addedNodes || []), ...(m.removedNodes || [])];
        if (!changed.length) return false;
        return changed.some(n => {
          if (!n || n.nodeType !== 1) return true;
          return !(n.matches?.('.v369-health') || n.closest?.('.v369-health'));
        });
      });
      if (externalChange) injectHealth();
    });

    observer.observe(document.body, {subtree: true, childList: true});
  });
})();
