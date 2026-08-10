(() => {
  'use strict';

  const WEEKDAYS = ['Pondělí','Úterý','Středa','Čtvrtek','Pátek','Sobota','Neděle'];
  let pollTimer = null;

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

  function sectionByTitles(titles) {
    const wanted = titles.map(x => x.toUpperCase());
    const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,.section-title,.card-title,strong'));
    for (const el of headings) {
      const txt = (el.textContent || '').trim().toUpperCase();
      if (!wanted.includes(txt)) continue;
      return el.closest('section,.panel,.card') || el.parentElement;
    }
    return null;
  }

  function compactMaintenanceAndBackups() {
    const maintenance = sectionByTitles(['ÚDRŽBA']);
    const backups = sectionByTitles(['KONFIGURACE - ZÁLOHY','KONFIGURACE – ZÁLOHY','ZÁLOHY KONFIGURACE']);
    if (!maintenance || !backups || maintenance === backups) return;

    // v3.7.4: ÚDRŽBA + KONFIGURACE/ZÁLOHY vedle sebe 50/50 a se stejnou výškou.
    let row = document.getElementById('maintenanceBackupRow');
    if (!row) {
      row = document.createElement('div');
      row.id = 'maintenanceBackupRow';
      row.className = 'maintenance-backup-row';
      maintenance.parentElement.insertBefore(row, maintenance);
    }

    // Přesuneme obě existující karty do společného řádku. Jejich obsah ani funkce se nemění.
    if (maintenance.parentElement !== row) row.appendChild(maintenance);
    if (backups.parentElement !== row) row.appendChild(backups);

    // v3.7.4: Flex je zde záměrně použit místo gridu. Původní stylesheet
    // některým kartám nastavuje vlastní grid-column / width, což je mohlo
    // shodit pod sebe. Třídy + !important CSS níže to spolehlivě přebijí.
    row.classList.add('maintenance-backup-row-force');
    maintenance.classList.add('maintenance-backup-half');
    backups.classList.add('maintenance-backup-half');

    row.style.setProperty('display', 'flex', 'important');
    row.style.setProperty('flex-direction', 'row', 'important');
    row.style.setProperty('flex-wrap', 'nowrap', 'important');
    row.style.setProperty('gap', '10px', 'important');
    row.style.setProperty('align-items', 'stretch', 'important');
    row.style.setProperty('width', '100%', 'important');
    row.style.setProperty('max-width', '100%', 'important');
    row.style.setProperty('box-sizing', 'border-box', 'important');
    row.style.setProperty('margin', '0 0 10px', 'important');

    for (const box of [maintenance, backups]) {
      box.style.setProperty('display', 'block', 'important');
      box.style.setProperty('flex', '1 1 0', 'important');
      box.style.setProperty('flex-basis', '0', 'important');
      box.style.setProperty('width', '0', 'important');
      box.style.setProperty('min-width', '0', 'important');
      box.style.setProperty('max-width', 'none', 'important');
      box.style.setProperty('grid-column', 'auto', 'important');
      box.style.setProperty('grid-row', 'auto', 'important');
      box.style.setProperty('align-self', 'stretch', 'important');
      box.style.setProperty('height', 'auto', 'important');
      box.style.setProperty('min-height', '0', 'important');
      box.style.setProperty('margin-top', '0', 'important');
      box.style.setProperty('margin-bottom', '0', 'important');
      box.style.setProperty('box-sizing', 'border-box', 'important');
    }

    // ÚDRŽBU ponecháme kompaktní, ale její karta se výškově dorovná se ZÁLOHAMI.
    maintenance.querySelectorAll('p,.sub,.subtitle,.section-subtitle,.muted').forEach(el => {
      const txt=(el.textContent||'').trim();
      if (txt && !el.querySelector('button,input,select')) el.style.display='none';
    });

    // Pod sebe pouze na skutečně úzkém displeji.
    const applyResponsive = () => {
      const mobile = window.innerWidth <= 640;
      row.style.setProperty('flex-direction', mobile ? 'column' : 'row', 'important');
      for (const box of [maintenance, backups]) {
        box.style.setProperty('width', mobile ? '100%' : '0', 'important');
        box.style.setProperty('flex-basis', mobile ? 'auto' : '0', 'important');
      }
    };
    applyResponsive();
    if (!row.dataset.resizeBound) {
      row.dataset.resizeBound = '1';
      window.addEventListener('resize', applyResponsive, {passive:true});
    }
  }



  // v3.7.6 – pouze klientské rozmístění podle nákresu.
  // Server / Flask / Jinja se tímto layoutem vůbec nemění.
  function installDashboardLayoutCss() {
    if (document.getElementById('dashboardLayout376')) return;
    const st = document.createElement('style');
    st.id = 'dashboardLayout376';
    st.textContent = `
      #topDashboardRow376{display:grid!important;grid-template-columns:minmax(0,3fr) minmax(360px,2fr)!important;gap:12px!important;align-items:stretch!important;width:100%!important;box-sizing:border-box!important;margin:0 0 12px!important}
      #topDashboardLeft376,#topDashboardRight376{display:flex!important;flex-direction:column!important;gap:10px!important;min-width:0!important;width:100%!important;box-sizing:border-box!important}
      #topDashboardLeft376>*,#topDashboardRight376>*{min-width:0!important;max-width:100%!important;box-sizing:border-box!important;margin-left:0!important;margin-right:0!important}
      #topDashboardLeft376>*{flex:1 1 auto!important}
      #topDashboardRight376>#owutPanel{margin:0!important;padding:13px!important;width:100%!important}
      #topDashboardRight376 .owut-status-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px!important}
      #topDashboardRight376 .owut-node{min-height:70px!important;padding:7px!important}
      #topDashboardRight376 .owut-log{height:78px!important}
      #topDashboardRight376 .owut-form{grid-template-columns:repeat(2,minmax(0,1fr))!important}
      @media(max-width:900px){#topDashboardRow376{grid-template-columns:1fr!important}}
      @media(max-width:560px){#topDashboardRight376 .owut-status-grid,#topDashboardRight376 .owut-form{grid-template-columns:1fr!important}}
    `;
    document.head.appendChild(st);
  }

  function arrangeTopDashboard376() {
    installDashboardLayoutCss();
    const topology = sectionByTitles(['TOPOLOGIE']);
    const progress = sectionByTitles(['PRŮBĚH OPERACE','PRUBEH OPERACE']);
    const owut = document.getElementById('owutPanel');
    if (!topology || !progress || !owut) return;

    let row = document.getElementById('topDashboardRow376');
    if (!row) {
      row = document.createElement('div');
      row.id = 'topDashboardRow376';
      row.innerHTML = '<div id="topDashboardLeft376"></div><div id="topDashboardRight376"></div>';
      const parent = topology.parentElement;
      if (!parent) return;
      parent.insertBefore(row, topology);
    }

    const left = document.getElementById('topDashboardLeft376');
    const right = document.getElementById('topDashboardRight376');
    if (!left || !right) return;

    if (topology.parentElement !== left) left.appendChild(topology);
    if (progress.parentElement !== right) right.appendChild(progress);
    if (owut.parentElement !== right) right.appendChild(owut);

    // Původní grid/flex pravidla konkrétních karet nesmí přetlačit nový řádek.
    for (const panel of [topology, progress, owut]) {
      panel.style.setProperty('width','100%','important');
      panel.style.setProperty('max-width','100%','important');
      panel.style.setProperty('grid-column','auto','important');
      panel.style.setProperty('grid-row','auto','important');
      panel.style.setProperty('margin-left','0','important');
      panel.style.setProperty('margin-right','0','important');
      panel.style.setProperty('box-sizing','border-box','important');
    }
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

    // v3.7.4: ÚDRŽBA + ZÁLOHY jsou v jednom 50/50 řádku; OWUT je pod nimi.
    compactMaintenanceAndBackups();
    const row = document.getElementById('maintenanceBackupRow');
    const backups = sectionByTitles(['KONFIGURACE - ZÁLOHY','KONFIGURACE – ZÁLOHY','ZÁLOHY KONFIGURACE']);
    const maintenance = sectionByTitles(['ÚDRŽBA']);
    const anchor = row || backups || maintenance;
    if (anchor && anchor.parentElement) {
      anchor.insertAdjacentElement('afterend', panel);
    } else {
      const main = document.querySelector('main,.container,.content') || document.body;
      main.appendChild(panel);
    }

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
    compactMaintenanceAndBackups();
    makePanel();
    compactMaintenanceAndBackups();
    arrangeTopDashboard376();
    hijackOldUpdateButton();
    loadSettings();
    refreshStatus();
    refreshOperation();
    setTimeout(arrangeTopDashboard376, 300);
    setTimeout(arrangeTopDashboard376, 1200);
    window.addEventListener('resize', arrangeTopDashboard376, {passive:true});
    setInterval(refreshOperation, 2500);
    setInterval(refreshStatus, 60000);

    const observer = new MutationObserver(() => {
      hijackOldUpdateButton();
      compactMaintenanceAndBackups();
      arrangeTopDashboard376();
    });
    observer.observe(document.body, {childList:true, subtree:true});
  });
})();
