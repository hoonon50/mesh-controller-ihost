(() => {
  'use strict';
  if (window.__MESH_V502_REFRESH_BOOTSTRAP__) return;
  window.__MESH_V502_REFRESH_BOOTSTRAP__ = true;

  const FAST_MS = 5000;
  const HEALTH_MS = 15000;
  const MIN_TUNABLE_MS = 8000;
  const MAX_TUNABLE_MS = 900000;

  // Tyto moduly mají vlastní záměrný interval a v5.0.2 se na ně nesahá.
  const EXCLUDED_SCRIPT_PARTS = [
    'wan_usage',
    'wan_history',
    'v500_operation',
    'v502_live_refresh_bootstrap'
  ];

  const HEALTH_WORDS = [
    'cpu', 'uptime', 'temperature', 'thermal', 'health', 'temp'
  ];

  const FAST_WORDS = [
    'topology', 'topologie', 'mesh', 'link', 'links', 'client', 'clients',
    'station', 'stations', 'peer', 'peers', 'node', 'nodes', 'status',
    'refresh', 'reload', 'update', 'load'
  ];

  const stats = {
    version: '5.0.2',
    fastMs: FAST_MS,
    healthMs: HEALTH_MS,
    changedIntervals: 0,
    untouchedIntervals: 0,
    registrations: []
  };
  window.__MESH_V502_REFRESH__ = stats;

  const nativeSetInterval = window.setInterval.bind(window);
  const nativeSetTimeout = window.setTimeout.bind(window);

  function currentScriptName() {
    try {
      const src = (document.currentScript && document.currentScript.src) || '';
      return src.split('/').pop().split('?')[0].toLowerCase();
    } catch (_) {
      return '';
    }
  }

  function callbackText(fn) {
    try {
      return typeof fn === 'function' ? Function.prototype.toString.call(fn).toLowerCase() : String(fn || '').toLowerCase();
    } catch (_) {
      return '';
    }
  }

  function hasAny(text, words) {
    return words.some(word => text.includes(word));
  }

  function excludedScript(scriptName) {
    return EXCLUDED_SCRIPT_PARTS.some(part => scriptName.includes(part));
  }

  function chooseInterval(fn, delay, scriptName) {
    const n = Number(delay);
    if (!Number.isFinite(n) || n < MIN_TUNABLE_MS || n > MAX_TUNABLE_MS) return n;
    if (excludedScript(scriptName)) return n;

    const cb = callbackText(fn);

    // CPU/uptime mají zůstat o něco pomalejší. Pokud callback přímo říká,
    // že jde o health data, použijeme 15 s.
    if (hasAny(cb, HEALTH_WORDS)) return HEALTH_MS;

    // U explicitně pojmenovaných live/topology/client callbacků vždy 5 s.
    if (hasAny(cb, FAST_WORDS)) return FAST_MS;

    // Hlavní dashboard historicky používá i generické callbacky typu refresh().
    // U periodických UI timerů v hlavním/inline skriptu proto bezpečně stáhneme
    // interval na 5 s. Výslovně oddělené WAN/Operation skripty jsou výše vyňaté.
    return FAST_MS;
  }

  window.setInterval = function meshV502SetInterval(fn, delay, ...args) {
    const scriptName = currentScriptName();
    const original = Number(delay);
    const tuned = chooseInterval(fn, original, scriptName);
    const changed = Number.isFinite(original) && tuned !== original;

    if (changed) stats.changedIntervals += 1;
    else stats.untouchedIntervals += 1;

    if (stats.registrations.length < 80) {
      stats.registrations.push({
        script: scriptName || 'inline',
        originalMs: original,
        effectiveMs: tuned,
        changed
      });
    }
    return nativeSetInterval(fn, tuned, ...args);
  };

  // setTimeout obecně NEzrychlujeme – používá se i pro reboot/OWUT timeouty,
  // dialogy a jednorázové akce. Jen ho zachováme beze změny.
  window.setTimeout = function meshV502SetTimeout(fn, delay, ...args) {
    return nativeSetTimeout(fn, delay, ...args);
  };

  // Diagnostika v konzoli: window.__MESH_V502_REFRESH__
  try {
    console.info('[Mesh v5.0.2] live refresh bootstrap aktivní: dashboard 5 s, CPU/uptime 15 s; WAN/Operation beze změny.');
  } catch (_) {}
})();
