(() => {
  'use strict';

  const WEEKDAYS = ['Pondělí','Úterý','Středa','Čtvrtek','Pátek','Sobota','Neděle'];
  let layoutBusy = false;
  let layoutScheduled = false;

  async function api(url, options={}) {
    const r = await fetch(url, {cache:'no-store', ...options, headers:{'Content-Type':'application/json', ...(options.headers||{})}});
    let data = {};
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error(data.error || data.message || `HTTP ${r.status}`);
    return data;
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function titleText(el) {
    return (el?.textContent || '').replace(/\s+/g, ' ').trim().toUpperCase();
  }

  function sectionByTitles(titles) {
    const wanted = titles.map(x => x.replace(/\s+/g, ' ').trim().toUpperCase());
    const headings = Array.from(document.querySelectorAll(
      'h1,h2,h3,h4,.section-title,.card-title,.panel-title,.title,strong'
    ));
    for (const el of headings) {
      if (!wanted.includes(titleText(el))) continue;
      return el.closest('section,.panel,.card,.glass,.box,.block') || el.parentElement;
    }
    return null;
  }

  function forcePanelFill(panel) {
    if (!panel) return;
    panel.style.setProperty('width', '100%', 'important');
    panel.style.setProperty('max-width', 'none', 'important');
    panel.style.setProperty('min-width', '0', 'important');
    panel.style.setProperty('box-sizing', 'border-box', 'important');
    panel.style.setProperty('grid-column', 'auto', 'important');
    panel.style.setProperty('grid-row', 'auto', 'important');
    panel.style.setProperty('margin-left', '0', 'important');
    panel.style.setProperty('margin-right', '0', 'important');
  }

  function compactMaintenance(maintenance) {
    if (!maintenance) return;
    maintenance.querySelectorAll('p,.sub,.subtitle,.section-subtitle,.muted').forEach(el => {
      const txt = (el.textContent || '').trim();
      if (txt && !el.querySelector('button,input,select')) el.style.display = 'none';
    });
  }

  function ensureTopDashboard(topology, progress, owut, lan) {
    if (!topology || !progress || !owut) return null;

    let row = document.getElementById('topDashboardRow');
    if (!row) {
      row = document.createElement('div');
      row.id = 'topDashboardRow';
      row.className = 'top-dashboard-row';

      const left = document.createElement('div');
      left.id = 'topDashboardLeft';
      left.className = 'top-dashboard-left';
      const right = document.createElement('div');
      right.id = 'topDashboardRight';
      right.className = 'top-dashboard-right';
      row.append(left, right);

      // Ideální kotva je LAN PORTY: horní 60/40 blok bude vždy těsně nad nimi.
      if (lan && lan.parentElement) {
        lan.parentElement.insertBefore(row, lan);
      } else if (topology.parentElement) {
        topology.parentElement.insertBefore(row, topology);
      }
    }

    const left = document.getElementById('topDashboardLeft');
    const right = document.getElementById('topDashboardRight');
    if (!left || !right) return row;

    if (topology.parentElement !== left) left.appendChild(topology);
    if (progress.parentElement !== right) right.appendChild(progress);
    if (owut.parentElement !== right) right.appendChild(owut);

    forcePanelFill(topology);
    forcePanelFill(progress);
    forcePanelFill(owut);

    topology.classList.add('dashboard-topology-panel');
    progress.classList.add('dashboard-progress-panel');
    owut.classList.add('dashboard-owut-panel');
    return row;
  }

  function ensureMaintenanceBackupRow(maintenance, backups, lan) {
    if (!maintenance || !backups || maintenance === backups) return null;

    let row = document.getElementById('maintenanceBackupRow');
    if (!row) {
      row = document.createElement('div');
      row.id = 'maintenanceBackupRow';
      row.className = 'maintenance-backup-row-force';

      // Dole bude přesně: LAN PORTY -> ÚDRŽBA | KONFIGURACE-ZÁLOHY.
      if (lan && lan.parentElement) {
        lan.insertAdjacentElement('afterend', row);
      } else if (maintenance.parentElement) {
        maintenance.parentElement.insertBefore(row, maintenance);
      }
    }

    if (maintenance.parentElement !== row) row.appendChild(maintenance);
    if (backups.parentElement !== row) row.appendChild(backups);

    for (const panel of [maintenance, backups]) {
      panel.classList.add('maintenance-backup-half');
      panel.style.setProperty('display', 'flex', 'important');
      panel.style.setProperty('flex-direction', 'column', 'important');
      panel.style.setProperty('flex', '1 1 0', 'important');
      panel.style.setProperty('flex-basis', '0', 'important');
      panel.style.setProperty('width', '0', 'important');
      panel.style.setProperty('min-width', '0', 'important');
      panel.style.setProperty('max-width', 'none', 'important');
      panel.style.setProperty('align-self', 'stretch', 'important');
      panel.style.setProperty('height', 'auto', 'important');
      panel.style.setProperty('box-sizing', 'border-box', 'important');
      panel.style.setProperty('grid-column', 'auto', 'important');
      panel.style.setProperty('grid-row', 'auto', 'important');
      panel.style.setProperty('margin-top', '0', 'important');
      panel.style.setProperty('margin-bottom', '0', 'important');
    }

    compactMaintenance(maintenance);
    return row;
  }

  function applyResponsiveLayout() {
    const top = document.getElementById('topDashboardRow');
    const bottom = document.getElementById('maintenanceBackupRow');
    const mobileTop = window.innerWidth <= 900;
    const mobileBottom = window.innerWidth <= 700;

    if (top) top.style.setProperty('grid-template-columns', mobileTop ? '1fr' : 'minmax(0,3fr) minmax(360px,2fr)', 'important');
    if (bottom) {
      bottom.style.setProperty('flex-direction', mobileBottom ? 'column' : 'row', 'important');
      for (const box of bottom.children) {
        if (!(box instanceof HTMLElement)) continue;
        box.style.setProperty('width', mobileBottom ? '100%' : '0', 'important');
        box.style.setProperty('flex-basis', mobileBottom ? 'auto' : '0', 'important');
      }
    }
  }

  function arrangeDashboard() {
    if (layoutBusy) return;
    layoutBusy = true;
    try {
      const topology = sectionByTitles(['TOPOLOGIE']);
      const progress = sectionByTitles(['PRŮBĚH OPERACE','PRUBEH OPERACE']);
      const lan = sectionByTitles(['LAN PORTY']);
      const maintenance = sectionByTitles(['ÚDRŽBA','UDRŽBA']);
      const backups = sectionByTitles(['KONFIGURACE - ZÁLOHY','KONFIGURACE – ZÁLOHY','KONFIGURACE - ZALOHY','ZÁLOHY KONFIGURACE']);
      const owut = document.getElementById('owutPanel');

      if (topology && progress && owut) ensureTopDashboard(topology, progress, owut, lan);
      if (maintenance && backups) ensureMaintenanceBackupRow(maintenance, backups, lan);
      applyResponsiveLayout();
    } finally {
      layoutBusy = false;
    }
  }

  function scheduleLayout() {
    if (layoutScheduled) return;
    layoutScheduled = true;
    requestAnimationFrame(() => {
      layoutScheduled = false;
      arrangeDashboard();
    });
  }

  function makePanel() {
    if (document.getElementById('owutPanel')) return;
    const panel = document.createElement('section');
    panel.id = 'owutPanel';
    panel.className = 'owut-panel';
    panel.innerHTML = `
      <div class="owut-title">OWUT SYSUPGRADE</div>
      <div class="owut-sub">Oficiální OpenWrt upgrade přes owut · MESH1 → MESH4 → ROUTER · ROUTER používá dvojitý restart pro USB Extroot.</div>

      <div class="owut-status-grid" id="owutStatusGrid"></div>

      <div class="owut-actions">
        <button class="owut-btn warn" id="owutCheckBtn">OWUT KONTROLA</button>
        <button class="owut-btn good" id="owutUpgradeBtn">OWUT AKTUALIZACE</button>
        <button class="owut-btn" id="owutRebootBtn">RESTART VŠECH</button>
        <button class="owut-btn danger" id="owutOverlayBtn">NASTAVIT USB OVERLAY .1</button>
      </div>

      <div class="owut-progress-wrap">
        <div class="owut-progress-head"><span id="owutOpMsg">Připraveno</span><span id="owutOpPct">0 %</span></div>
        <div class="owut-progress"><div id="owutProgressBar"></div></div>
        <pre id="owutLog" class="owut-log"></pre>
      </div>

      <div class="owut-settings-title">AUTOMATICKÁ AKTUALIZACE + GMAIL REPORT</div>
      <div class="owut-form">
        <label><span>Automatika</span><input id="owutAuto" type="checkbox"></label>
        <label><span>Den</span><select id="owutWeekday">${WEEKDAYS.map((x,i)=>`<option value="${i}">${x}</option>`).join('')}</select></label>
        <label><span>Čas</span><input id="owutTime" type="time" value="03:00"></label>
        <label><span>Gmail odesílatel</span><input id="owutFrom" type="email" placeholder="vas@gmail.com"></label>
        <label><span>Odeslat report na</span><input id="owutTo" type="email" placeholder="prijemce@gmail.com"></label>
        <label><span>Heslo aplikace Gmail</span><input id="owutPass" type="password" autocomplete="new-password" placeholder="16místné heslo aplikace"></label>
      </div>
      <div class="owut-small" id="owutPassState"></div>
      <div class="owut-actions small-row">
        <button class="owut-btn good" id="owutSaveBtn">ULOŽIT NASTAVENÍ</button>
        <button class="owut-btn" id="owutMailBtn">ODESLAT TESTOVACÍ EMAIL</button>
      </div>
    `;

    // Panel vložíme do hlavního obsahu a následně jej layout přesune
    // pod PRŮBĚH OPERACE do pravého horního sloupce.
    const main = document.querySelector('main,.container,.content') || document.body;
    main.appendChild(panel);

    document.getElementById('owutCheckBtn').onclick = () => startOp('/api/owut/check', {});
    document.getElementById('owutUpgradeBtn').onclick = () => startOp('/api/owut/upgrade', {});
    document.getElementById('owutRebootBtn').onclick = () => startOp('/api/owut/reboot', {target:'all'});
    document.getElementById('owutOverlayBtn').onclick = overlaySetup;
    document.getElementById('owutSaveBtn').onclick = saveSettings;
    document.getElementById('owutMailBtn').onclick = testEmail;
  }

  function hijackOldUpdateButton() {
    const buttons = Array.from(document.querySelectorAll('button'));
    for (const btn of buttons) {
      if (btn.dataset.owutBound === '1') continue;
      const txt = (btn.textContent || '').trim().toUpperCase();
      if (txt === 'AKTUALIZACE HW' || txt.includes('AKTUALIZOVAT VŠECH 5 ROUTERŮ') || txt.includes('AKTUALIZOVAT BALÍČKY NA VŠECH')) {
        const clone = btn.cloneNode(true);
        clone.dataset.owutBound = '1';
        clone.textContent = 'OWUT AKTUALIZACE';
        clone.onclick = (e) => { e.preventDefault(); startOp('/api/owut/upgrade', {}); };
        btn.replaceWith(clone);
      }
    }
  }

  async function startOp(url, body) {
    try {
      await api(url, {method:'POST', body:JSON.stringify(body)});
      await refreshOperation();
    } catch (e) {
      alert(e.message);
    }
  }

  async function overlaySetup() {
    const answer = prompt('POZOR: Tato funkce smaže celý první nalezený USB disk na ROUTERu 192.168.30.1.\n\nPro potvrzení napiš přesně: SMAZAT USB');
    if (answer !== 'SMAZAT USB') return;
    await startOp('/api/owut/overlay-setup', {confirm:'SMAZAT USB'});
  }

  async function loadSettings() {
    try {
      const s = await api('/api/owut/settings');
      document.getElementById('owutAuto').checked = !!s.auto_enabled;
      document.getElementById('owutWeekday').value = String(s.weekday ?? 6);
      document.getElementById('owutTime').value = s.time || '03:00';
      document.getElementById('owutFrom').value = s.gmail_from || '';
      document.getElementById('owutTo').value = s.gmail_to || '';
      document.getElementById('owutPassState').textContent = s.gmail_password_saved ? 'Heslo aplikace je uložené v /data. Pokud ho necháš prázdné, nezmění se.' : 'Heslo aplikace zatím není uložené.';
    } catch (_) {}
  }

  async function saveSettings() {
    const payload = {
      auto_enabled: document.getElementById('owutAuto').checked,
      weekday: Number(document.getElementById('owutWeekday').value),
      time: document.getElementById('owutTime').value,
      gmail_from: document.getElementById('owutFrom').value.trim(),
      gmail_to: document.getElementById('owutTo').value.trim(),
      gmail_app_password: document.getElementById('owutPass').value.trim(),
    };
    try {
      await api('/api/owut/settings', {method:'POST', body:JSON.stringify(payload)});
      document.getElementById('owutPass').value = '';
      await loadSettings();
      alert('Nastavení uloženo.');
    } catch(e) { alert(e.message); }
  }

  async function testEmail() {
    try {
      const r = await api('/api/owut/test-email', {method:'POST', body:'{}'});
      alert(r.message || 'Testovací e-mail odeslán.');
    } catch(e) { alert(e.message); }
  }

  async function refreshStatus() {
    try {
      const s = await api('/api/owut/status');
      const grid = document.getElementById('owutStatusGrid');
      if (!grid) return;
      const overlay = s.overlay || {};
      grid.innerHTML = (s.routers || []).map(r => {
        const owut = r.owut ? esc(r.owut) : 'owut ?';
        const version = r.version ? `OpenWrt ${esc(r.version)}` : 'OpenWrt ?';
        let extra = '';
        if (r.ip === '192.168.30.1') {
          extra = `<div class="owut-mini ${overlay.usb ? 'ok':'bad'}">USB OVERLAY: ${overlay.usb ? 'AKTIVNÍ':'NEAKTIVNÍ'}${overlay.device ? ` · ${esc(overlay.device)}`:''}</div>`;
        }
        return `<div class="owut-node ${r.online ? 'online':'offline'}"><b>${esc(r.name || r.ip)}</b><span>${esc(r.ip)}</span><small>${version}</small><small>${owut}</small>${extra}</div>`;
      }).join('');
      renderOperation(s.operation || {});
    } catch (_) {}
  }

  function renderOperation(op) {
    const msg = document.getElementById('owutOpMsg');
    if (!msg) return;
    const pct = Number(op.progress || 0);
    msg.textContent = op.message || 'Připraveno';
    document.getElementById('owutOpPct').textContent = `${pct} %`;
    document.getElementById('owutProgressBar').style.width = `${pct}%`;
    const log = document.getElementById('owutLog');
    const text = (op.log || []).join('\n');
    if (log.textContent !== text) {
      log.textContent = text;
      log.scrollTop = log.scrollHeight;
    }
    document.querySelectorAll('#owutPanel button').forEach(b => {
      if (!['owutSaveBtn','owutMailBtn'].includes(b.id)) b.disabled = !!op.running;
    });
  }

  async function refreshOperation() {
    try { renderOperation(await api('/api/owut/operation')); } catch (_) {}
  }

  document.addEventListener('DOMContentLoaded', () => {
    makePanel();
    hijackOldUpdateButton();
    arrangeDashboard();
    loadSettings();
    refreshStatus();
    refreshOperation();

    setTimeout(arrangeDashboard, 300);
    setTimeout(arrangeDashboard, 1200);
    setInterval(refreshOperation, 2500);
    setInterval(refreshStatus, 60000);

    window.addEventListener('resize', applyResponsiveLayout, {passive:true});

    // Některé části hlavní aplikace se živě překreslují. Layout je idempotentní;
    // observer pouze znovu naváže případně nově vytvořený obsah do stejných sloupců.
    const observer = new MutationObserver(() => {
      hijackOldUpdateButton();
      scheduleLayout();
    });
    observer.observe(document.body, {childList:true, subtree:true});
  });
})();
