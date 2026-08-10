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

    // Zálohy patří bezprostředně pod ÚDRŽBU.
    if (maintenance.nextElementSibling !== backups) {
      maintenance.insertAdjacentElement('afterend', backups);
    }

    // Karty se nesmějí natahovat podle výšky sousední karty.
    for (const box of [maintenance, backups]) {
      box.style.gridColumn = '1 / -1';
      box.style.width = '100%';
      box.style.maxWidth = '100%';
      box.style.flex = '0 0 100%';
      box.style.alignSelf = 'start';
      box.style.height = 'auto';
      box.style.minHeight = '0';
      box.style.boxSizing = 'border-box';
    }

    maintenance.style.marginBottom = '10px';
    backups.style.marginTop = '0';

    const parent = maintenance.parentElement;
    if (parent && parent === backups.parentElement) {
      const cs = getComputedStyle(parent);
      parent.style.alignItems = 'start';
      if (cs.display.includes('grid')) {
        parent.style.gridTemplateColumns = 'minmax(0,1fr)';
        parent.style.rowGap = '10px';
      } else if (cs.display.includes('flex')) {
        parent.style.flexDirection = 'column';
        parent.style.alignItems = 'stretch';
        parent.style.gap = '10px';
      }
    }

    // Odstraní pouze prázdný prostor; tlačítka a ovládací prvky zůstávají.
    maintenance.querySelectorAll('p,.sub,.subtitle,.section-subtitle,.muted').forEach(el => {
      const txt=(el.textContent||'').trim();
      if (txt && !el.querySelector('button,input,select')) el.style.display='none';
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

    // v3.7.2: ÚDRŽBA -> KONFIGURACE/ZÁLOHY -> OWUT.
    // Zálohy tak zůstávají bezprostředně pod kompaktní údržbou.
    compactMaintenanceAndBackups();
    const backups = sectionByTitles(['KONFIGURACE - ZÁLOHY','KONFIGURACE – ZÁLOHY','ZÁLOHY KONFIGURACE']);
    const maintenance = sectionByTitles(['ÚDRŽBA']);
    const anchor = backups || maintenance;
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
    hijackOldUpdateButton();
    loadSettings();
    refreshStatus();
    refreshOperation();
    setInterval(refreshOperation, 2500);
    setInterval(refreshStatus, 60000);

    const observer = new MutationObserver(() => {
      hijackOldUpdateButton();
      compactMaintenanceAndBackups();
    });
    observer.observe(document.body, {childList:true, subtree:true});
  });
})();
