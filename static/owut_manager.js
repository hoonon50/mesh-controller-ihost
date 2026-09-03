(() => {
  'use strict';

  if (window.__OWUT_MANAGER_386__) return;
  window.__OWUT_MANAGER_386__ = true;

  const SCHEDULE_MODES = [{value:'daily',label:'Každý den'},{value:'weekly',label:'Vybraný den'}];
  const SCHEDULE_DAYS = [{value:0,label:'Pondělí'},{value:1,label:'Úterý'},{value:2,label:'Středa'},{value:3,label:'Čtvrtek'},{value:4,label:'Pátek'},{value:5,label:'Sobota'},{value:6,label:'Neděle'}];

  async function api(url, options={}) {
    const r = await fetch(url, {
      cache:'no-store',
      ...options,
      headers:{'Content-Type':'application/json', ...(options.headers||{})}
    });
    let data = {};
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error(data.error || data.message || `HTTP ${r.status}`);
    return data;
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function sectionByTitles(titles) {
    const wanted = new Set(titles.map(x => x.toUpperCase()));
    const headings = document.querySelectorAll('h1,h2,h3,h4,.section-title,.card-title,strong');
    for (const el of headings) {
      const txt = (el.textContent || '').trim().toUpperCase();
      if (!wanted.has(txt)) continue;
      return el.closest('section,.panel,.card') || el.parentElement;
    }
    return null;
  }

  function makePanels() {
    let manual = document.getElementById('owutPanel');
    let auto = document.getElementById('owutAutoPanel');
    if (manual && auto) return {manual, auto};

    manual = document.createElement('section');
    manual.id = 'owutPanel';
    manual.className = 'owut-panel owut-manual-panel';
    manual.innerHTML = `
      <div class="owut-title">OWUT SYSUPGRADE</div>
      <div class="owut-sub">Oficiální OpenWrt upgrade přes owut · MESH2 → MESH3 → MESH4 → MESH1 → ROUTER · ROUTER používá dvojitý restart pro USB Extroot.</div>
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
      </div>`;

    auto = document.createElement('section');
    auto.id = 'owutAutoPanel';
    auto.className = 'owut-panel owut-auto-panel';
    auto.innerHTML = `
      <div class="owut-title owut-auto-title">AUTOMATICKÁ AKTUALIZACE + GMAIL REPORT</div>
      <div class="owut-form">
        <label><span>Automatika</span><input id="owutAuto" type="checkbox"></label>
        <label><span>Frekvence</span><select id="owutScheduleMode">${SCHEDULE_MODES.map(x=>`<option value="${x.value}">${x.label}</option>`).join('')}</select></label>
        <label id="owutWeekdayLabel"><span>Den</span><select id="owutWeekday">${SCHEDULE_DAYS.map(x=>`<option value="${x.value}">${x.label}</option>`).join('')}</select></label>
        <label><span>Čas</span><input id="owutTime" type="time" value="03:00"></label>
        <label><span>Gmail odesílatel</span><input id="owutFrom" type="email" placeholder="vas@gmail.com"></label>
        <label><span>Odeslat report na</span><input id="owutTo" type="email" placeholder="prijemce@gmail.com"></label>
        <label><span>Heslo aplikace Gmail</span><input id="owutPass" type="password" autocomplete="new-password" placeholder="16místné heslo aplikace"></label>
        <label><span>MAIL REPORT</span><select id="owutMailFormat"><option value="html">HTML</option><option value="text">TEXT</option></select></label>
      </div>
      <div class="owut-small" id="owutPassState"></div>
      <div class="owut-actions small-row owut-mail-actions">
        <button class="owut-btn good" id="owutSaveBtn">ULOŽIT NASTAVENÍ</button>
        <div class="owut-mail-test-wrap">
          <button class="owut-btn" id="owutMailBtn">ODESLAT TESTOVACÍ EMAIL</button>
          <div class="owut-mail-progress idle" id="owutMailProgress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" title="Připraveno">
            <div class="owut-mail-progress-fill"></div>
            <span class="owut-mail-progress-mark" aria-hidden="true"></span>
          </div>
        </div>
      </div>`;

    const main = document.querySelector('main,.container,.content') || document.body;
    main.appendChild(manual);
    main.appendChild(auto);

    document.getElementById('owutCheckBtn').onclick = () => startOp('/api/owut/check', {});
    document.getElementById('owutUpgradeBtn').onclick = () => startOp('/api/owut/upgrade', {});
    document.getElementById('owutRebootBtn').onclick = () => startOp('/api/owut/reboot', {target:'all'});
    document.getElementById('owutOverlayBtn').onclick = overlaySetup;
    document.getElementById('owutSaveBtn').onclick = saveSettings;
    document.getElementById('owutMailBtn').onclick = testEmail;
    document.getElementById('owutScheduleMode').onchange = syncScheduleUi;
    return {manual, auto};
  }

  function arrangeLayoutOnce() {
    if (document.documentElement.dataset.meshLayout381 === 'done') return true;

    const topology = sectionByTitles(['TOPOLOGIE']);
    const progress = sectionByTitles(['PRŮBĚH OPERACE','PRUBEH OPERACE']);
    const lan = sectionByTitles(['LAN PORTY']);
    const maintenance = sectionByTitles(['ÚDRŽBA']);
    const backups = sectionByTitles(['KONFIGURACE - ZÁLOHY','KONFIGURACE – ZÁLOHY','ZÁLOHY KONFIGURACE']);
    const manual = document.getElementById('owutPanel');
    const auto = document.getElementById('owutAutoPanel');

    if (!topology || !progress || !maintenance || !backups || !manual || !auto) return false;

    const topParent = topology.parentElement;
    if (!topParent) return false;

    let topRow = document.getElementById('meshTopRow381');
    if (!topRow) {
      topRow = document.createElement('div');
      topRow.id = 'meshTopRow381';
      topParent.insertBefore(topRow, topology);
    }

    // Jednorázové statické rozmístění 2×2:
    // TOPOLOGIE | PRŮBĚH OPERACE
    // OWUT      | AUTO + GMAIL
    topology.classList.add('mesh-cell-topology381');
    progress.classList.add('mesh-cell-progress381');
    manual.classList.add('mesh-cell-owut381');
    auto.classList.add('mesh-cell-auto381');

    topRow.appendChild(topology);
    topRow.appendChild(progress);
    topRow.appendChild(manual);
    topRow.appendChild(auto);

    const bottomParent = maintenance.parentElement;
    if (!bottomParent) return false;
    let bottomRow = document.getElementById('maintenanceBackupRow381');
    if (!bottomRow) {
      bottomRow = document.createElement('div');
      bottomRow.id = 'maintenanceBackupRow381';
      bottomParent.insertBefore(bottomRow, maintenance);
    }
    bottomRow.appendChild(maintenance);
    bottomRow.appendChild(backups);

    topRow.style.setProperty('grid-column','1 / -1','important');
    bottomRow.style.setProperty('grid-column','1 / -1','important');
    if (lan) lan.style.setProperty('grid-column','1 / -1','important');

    document.documentElement.dataset.meshLayout381 = 'done';
    return true;
  }

  function arrangeWithFiniteRetries() {
    if (arrangeLayoutOnce()) return;
    [100, 300, 700, 1400].forEach(ms => setTimeout(() => arrangeLayoutOnce(), ms));
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
    } catch (e) { alert(e.message); }
  }

  async function overlaySetup() {
    const answer = prompt('POZOR: Tato funkce smaže celý první nalezený USB disk na ROUTERu 192.168.30.1.\n\nPro potvrzení napiš přesně: SMAZAT USB');
    if (answer !== 'SMAZAT USB') return;
    await startOp('/api/owut/overlay-setup', {confirm:'SMAZAT USB'});
  }

  function syncScheduleUi() {
    const mode = document.getElementById('owutScheduleMode')?.value || 'weekly';
    const label = document.getElementById('owutWeekdayLabel');
    if (label) label.style.display = mode === 'daily' ? 'none' : '';
  }

  async function loadSettings() {
    try {
      const s = await api('/api/owut/settings');
      document.getElementById('owutAuto').checked = !!s.auto_enabled;
      const scheduleMode = (s.schedule_mode === 'daily' || Number(s.weekday) === -1) ? 'daily' : 'weekly';
      document.getElementById('owutScheduleMode').value = scheduleMode;
      document.getElementById('owutWeekday').value = String(Number(s.weekday) >= 0 ? s.weekday : 6);
      syncScheduleUi();
      document.getElementById('owutTime').value = s.time || '03:00';
      document.getElementById('owutFrom').value = s.gmail_from || '';
      document.getElementById('owutTo').value = s.gmail_to || '';
      document.getElementById('owutMailFormat').value = (s.mail_report_format || 'html').toLowerCase();
      document.getElementById('owutPassState').textContent = s.gmail_password_saved
        ? 'Heslo aplikace je uložené v /data. Pokud ho necháš prázdné, nezmění se.'
        : 'Heslo aplikace zatím není uložené.';
    } catch (_) {}
  }

  async function saveSettings() {
    const payload = {
      auto_enabled: document.getElementById('owutAuto').checked,
      schedule_mode: document.getElementById('owutScheduleMode').value,
      weekday: document.getElementById('owutScheduleMode').value === 'daily' ? -1 : Number(document.getElementById('owutWeekday').value),
      time: document.getElementById('owutTime').value,
      gmail_from: document.getElementById('owutFrom').value.trim(),
      gmail_to: document.getElementById('owutTo').value.trim(),
      gmail_app_password: document.getElementById('owutPass').value.trim(),
      mail_report_format: document.getElementById('owutMailFormat').value,
    };
    try {
      await api('/api/owut/settings', {method:'POST', body:JSON.stringify(payload)});
      document.getElementById('owutPass').value = '';
      await loadSettings();
      alert('Nastavení uloženo.');
    } catch(e) { alert(e.message); }
  }

  function setMailProgress(mode, title='') {
    const progress = document.getElementById('owutMailProgress');
    if (!progress) return;
    progress.classList.remove('idle','sending','success','failure');
    progress.classList.add(mode);
    progress.title = title || ({idle:'Připraveno',sending:'Odesílám testovací e-mail…',success:'Testovací e-mail byl odeslán.',failure:'Testovací e-mail se nepodařilo odeslat.'}[mode] || '');
    progress.setAttribute('aria-valuenow', mode === 'success' || mode === 'failure' ? '100' : '0');
    const mark = progress.querySelector('.owut-mail-progress-mark');
    if (mark) mark.textContent = mode === 'success' ? '✓' : (mode === 'failure' ? '✕' : '');
  }

  async function testEmail() {
    const btn = document.getElementById('owutMailBtn');
    if (btn) btn.disabled = true;
    setMailProgress('sending');
    try {
      const r = await api('/api/owut/test-email', {method:'POST', body:'{}'});
      setMailProgress('success', r.message || 'Testovací e-mail byl odeslán.');
      setTimeout(() => setMailProgress('idle'), 5000);
    } catch(e) {
      setMailProgress('failure', `Chyba: ${e.message}`);
      setTimeout(() => setMailProgress('idle'), 8000);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function refreshStatus() {
    try {
      const s = await api('/api/owut/status');
      const grid = document.getElementById('owutStatusGrid');
      if (!grid) return;
      const overlay = s.overlay || {};
      const html = (s.routers || []).map(r => {
        const owut = r.owut ? esc(r.owut) : 'owut ?';
        const version = r.version ? `OpenWrt ${esc(r.version)}` : 'OpenWrt ?';
        let extra = '';
        if (r.ip === '192.168.30.1') {
          extra = `<div class="owut-mini ${overlay.usb ? 'ok':'bad'}">USB OVERLAY: ${overlay.usb ? 'AKTIVNÍ':'NEAKTIVNÍ'}${overlay.device ? ` · ${esc(overlay.device)}`:''}</div>`;
        }
        return `<div class="owut-node ${r.online ? 'online':'offline'}"><b>${esc(r.name || r.ip)}</b><span>${esc(r.ip)}</span><small>${version}</small><small>${owut}</small>${extra}</div>`;
      }).join('');
      if (grid.innerHTML !== html) grid.innerHTML = html;
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
      b.disabled = !!op.running;
    });
  }

  async function refreshOperation() {
    try { renderOperation(await api('/api/owut/operation')); } catch (_) {}
  }

  document.addEventListener('DOMContentLoaded', () => {
    makePanels();
    arrangeWithFiniteRetries();
    hijackOldUpdateButton();
    loadSettings();
    refreshStatus();
    refreshOperation();

    // OWUT operace = 5 s, stav OWUT routerů = 30 s.
    setInterval(refreshOperation, 5000);
    setInterval(refreshStatus, 30000);
  }, {once:true});
})();
