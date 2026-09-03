(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const server = $('cbNextcloudServer');
  const username = $('cbNextcloudUser');
  const password = $('cbNextcloudPassword');
  const remoteDir = $('cbNextcloudDir');
  const saveBtn = $('cbNextcloudSave');
  const testBtn = $('cbNextcloudTest');
  const exportBtn = $('cbExport');
  const importBtn = $('cbImport');
  const importFile = $('cbImportFile');
  const statusBox = $('cbStatus');
  const nextBox = $('cbNextRun');

  if (!server || !username || !password || !remoteDir || !statusBox) return;

  function setStatus(text, ok = null) {
    statusBox.textContent = text || '—';
    statusBox.classList.remove('cb-ok', 'cb-error');
    if (ok === true) statusBox.classList.add('cb-ok');
    if (ok === false) statusBox.classList.add('cb-error');
  }

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || data.message || `HTTP ${response.status}`);
    }
    return data;
  }

  function localDateTime(value) {
    if (!value) return '—';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString('cs-CZ');
  }

  async function load() {
    try {
      const data = await api('/api/v701/controller-backup');
      const cfg = data.settings || {};
      server.value = cfg.server || '';
      username.value = cfg.username || '';
      remoteDir.value = cfg.remote_dir || '/OpenWRT-MESH-CONTROLLER';
      password.value = '';
      password.placeholder = cfg.password_set ? 'uloženo – prázdné = ponechat' : 'heslo / App Password';

      const last = data.last_backup || {};
      if (last.attempted_at) {
        const mark = last.ok ? 'OK' : 'CHYBA';
        const detail = last.detail ? ` · ${last.detail}` : '';
        setStatus(`Poslední automatická záloha: ${mark} · ${localDateTime(last.attempted_at)}${detail}`, !!last.ok);
      } else {
        setStatus(cfg.configured ? 'Nextcloud je nastaven. Automatická záloha ještě neproběhla.' : 'Nextcloud zatím není kompletně nastaven.', cfg.configured ? null : false);
      }

      const next = data.next || {};
      nextBox.textContent = next.backup
        ? `Další automatická záloha + OWUT: ${localDateTime(next.owut)} · stejný plánovaný čas · Nextcloud ponechá posledních 10 záloh`
        : 'Automatická záloha se řídí výhradně plánem OWUT a spouští se ve stejný čas. Nextcloud ponechá posledních 10 záloh.';
    } catch (err) {
      setStatus(`Chyba načtení: ${err.message}`, false);
    }
  }

  function formPayload() {
    return {
      server: server.value.trim(),
      username: username.value.trim(),
      password: password.value,
      remote_dir: remoteDir.value.trim() || '/OpenWRT-MESH-CONTROLLER',
    };
  }

  saveBtn?.addEventListener('click', async () => {
    saveBtn.disabled = true;
    setStatus('Ukládám nastavení…');
    try {
      await api('/api/v701/controller-backup/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(formPayload()),
      });
      password.value = '';
      setStatus('Nastavení Nextcloudu uloženo.', true);
      await load();
    } catch (err) {
      setStatus(`Uložení selhalo: ${err.message}`, false);
    } finally {
      saveBtn.disabled = false;
    }
  });

  testBtn?.addEventListener('click', async () => {
    testBtn.disabled = true;
    setStatus('Testuji Nextcloud WebDAV…');
    try {
      await api('/api/v701/controller-backup/test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(formPayload()),
      });
      setStatus('NEXTCLOUD: OK · přihlášení i cílový adresář jsou dostupné.', true);
    } catch (err) {
      setStatus(`NEXTCLOUD: CHYBA · ${err.message}`, false);
    } finally {
      testBtn.disabled = false;
    }
  });

  exportBtn?.addEventListener('click', () => {
    window.location.href = '/api/v701/controller-backup/export';
  });

  importBtn?.addEventListener('click', () => importFile?.click());

  importFile?.addEventListener('change', async () => {
    const file = importFile.files && importFile.files[0];
    if (!file) return;
    const accepted = window.confirm('Import obnoví nastavení a statistiky Controlleru ze zvolené zálohy. Zálohy routerů v /data/backups se nemění. Pokračovat?');
    if (!accepted) {
      importFile.value = '';
      return;
    }
    const body = new FormData();
    body.append('file', file);
    importBtn.disabled = true;
    setStatus('Ověřuji a připravuji import…');
    try {
      const data = await api('/api/v701/controller-backup/import', {method: 'POST', body});
      setStatus(`${data.message || 'Import připraven.'} Obnovuji stránku…`, true);
      setTimeout(() => window.location.reload(), 6500);
    } catch (err) {
      setStatus(`IMPORT: CHYBA · ${err.message}`, false);
      importBtn.disabled = false;
    } finally {
      importFile.value = '';
    }
  });

  load();
})();
