(() => {
  'use strict';

  const API = '/api/wan-history';
  const REFRESH_MS = 30000;
  const MONTHS = [
    ['01', 'LEDEN'], ['02', 'ÚNOR'], ['03', 'BŘEZEN'], ['04', 'DUBEN'],
    ['05', 'KVĚTEN'], ['06', 'ČERVEN'], ['07', 'ČERVENEC'], ['08', 'SRPEN'],
    ['09', 'ZÁŘÍ'], ['10', 'ŘÍJEN'], ['11', 'LISTOPAD'], ['12', 'PROSINEC']
  ];

  let selectedYear = '';
  let latestPayload = null;

  function formatTraffic(bytes) {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n < 0) return '—';
    const gb = n / 1_000_000_000;
    if (gb >= 1000) return `${(gb / 1000).toFixed(2)} TB`;
    return `${gb.toFixed(2)} GB`;
  }

  function smallestPanelContainingText(text) {
    const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,strong,b,div,span'))
      .filter(el => (el.textContent || '').trim() === text);
    for (const heading of headings) {
      let node = heading.parentElement;
      for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
        const rect = node.getBoundingClientRect();
        const content = (node.textContent || '');
        if (rect.width > 360 && rect.height > 220 && content.includes('Připraveno')) return node;
      }
    }
    return null;
  }

  function findOperationPanel() {
    return smallestPanelContainingText('Průběh operace') ||
           smallestPanelContainingText('PRŮBĚH OPERACE');
  }

  function buildShell() {
    const shell = document.createElement('section');
    shell.id = 'wanHistoryPanel';
    shell.className = 'wan-history-panel';
    shell.innerHTML = `
      <div class="wan-history-head">
        <div>
          <div class="wan-history-title">WAN DATA – HISTORIE</div>
          <div class="wan-history-subtitle">ROUTER .1 · měsíční součty</div>
        </div>
        <label class="wan-history-year-label">ROK
          <select id="wanHistoryYear" class="wan-history-year"></select>
        </label>
      </div>
      <div class="wan-history-table" role="table" aria-label="Historie WAN provozu">
        <div class="wan-history-row wan-history-table-head" role="row">
          <div>MĚSÍC</div><div>DOWNLOAD</div><div>UPLOAD</div><div>CELKEM</div>
        </div>
        <div id="wanHistoryRows"></div>
      </div>
      <div class="wan-history-total">
        <span>ROK CELKEM</span>
        <strong id="wanHistoryYearDownload">0.00 GB</strong>
        <strong id="wanHistoryYearUpload">0.00 GB</strong>
        <strong id="wanHistoryYearTotal">0.00 GB</strong>
      </div>`;
    return shell;
  }

  function mount() {
    if (document.getElementById('wanHistoryPanel')) return true;
    const panel = findOperationPanel();
    if (!panel) return false;

    panel.classList.add('wan-history-host-panel');
    const shell = buildShell();
    panel.appendChild(shell);

    const select = shell.querySelector('#wanHistoryYear');
    select.addEventListener('change', () => {
      selectedYear = select.value;
      render(latestPayload);
    });
    return true;
  }

  function updateYearOptions(payload) {
    const select = document.getElementById('wanHistoryYear');
    if (!select || !payload) return;
    const years = Array.from(new Set((payload.years || []).map(String)))
      .filter(y => /^\d{4}$/.test(y))
      .sort((a, b) => Number(b) - Number(a));
    const desired = selectedYear && years.includes(selectedYear)
      ? selectedYear
      : (years.includes(String(payload.current_year)) ? String(payload.current_year) : (years[0] || String(new Date().getFullYear())));

    const old = Array.from(select.options).map(o => o.value).join(',');
    const next = years.join(',');
    if (old !== next) {
      select.innerHTML = '';
      for (const year of years) {
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        select.appendChild(option);
      }
    }
    selectedYear = desired;
    select.value = desired;
  }

  function render(payload) {
    if (!payload || !mount()) return;
    latestPayload = payload;
    updateYearOptions(payload);

    const rows = document.getElementById('wanHistoryRows');
    if (!rows) return;
    const yearData = (payload.history && payload.history[selectedYear]) || {};
    const currentYear = String(payload.current_year || '');
    const currentMonth = String(payload.current_month || '');
    let yearRx = 0;
    let yearTx = 0;

    rows.innerHTML = '';
    for (const [monthNo, monthName] of MONTHS) {
      const bucket = yearData[monthNo];
      const hasData = !!bucket;
      const rx = hasData ? Number(bucket.rx_bytes || 0) : 0;
      const tx = hasData ? Number(bucket.tx_bytes || 0) : 0;
      yearRx += rx;
      yearTx += tx;

      const row = document.createElement('div');
      row.className = 'wan-history-row';
      if (selectedYear === currentYear && monthNo === currentMonth) row.classList.add('wan-history-current');
      row.innerHTML = `
        <div class="wan-history-month">${monthName}</div>
        <div class="wan-history-download">${hasData ? formatTraffic(rx) : '—'}</div>
        <div class="wan-history-upload">${hasData ? formatTraffic(tx) : '—'}</div>
        <div class="wan-history-sum">${hasData ? formatTraffic(rx + tx) : '—'}</div>`;
      rows.appendChild(row);
    }

    const yd = document.getElementById('wanHistoryYearDownload');
    const yu = document.getElementById('wanHistoryYearUpload');
    const yt = document.getElementById('wanHistoryYearTotal');
    if (yd) yd.textContent = formatTraffic(yearRx);
    if (yu) yu.textContent = formatTraffic(yearTx);
    if (yt) yt.textContent = formatTraffic(yearRx + yearTx);

    const panel = document.getElementById('wanHistoryPanel');
    if (panel) {
      panel.classList.toggle('wan-history-stale', !payload.ok);
      panel.title = payload.ok
        ? `WAN historie · aktualizováno ${payload.updated_at || ''}`
        : `Poslední hodnoty zachovány · ${payload.error || 'ROUTER .1 momentálně nedostupný'}`;
    }
  }

  async function refresh() {
    if (!mount()) return;
    try {
      const response = await fetch(API, {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (err) {
      const panel = document.getElementById('wanHistoryPanel');
      if (panel) {
        panel.classList.add('wan-history-stale');
        panel.title = `WAN historie je dočasně nedostupná: ${err}`;
      }
    }
  }

  function boot(retries = 24) {
    if (mount()) {
      refresh();
      window.setInterval(refresh, REFRESH_MS);
      return;
    }
    if (retries > 0) window.setTimeout(() => boot(retries - 1), 250);
  }

  document.addEventListener('DOMContentLoaded', () => boot(), {once: true});
})();
