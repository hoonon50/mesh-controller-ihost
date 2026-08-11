from pathlib import Path
import json
import os
import re

ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
STATIC = ROOT / "static"

FAST_MS = 5000       # topologie, mesh spoje, klienti
HEALTH_MS = 15000    # CPU, teplota, uptime, health dlaždice
FAST_S = 5
HEALTH_S = 15

EXCLUDED_JS = {
    "v500_operation.js",   # záměrně 2 s
    "wan_usage.js",        # záměrně 30 s
    "wan_history.js",      # záměrně 30 s
    "v501_refresh_guard.js",
}
EXCLUDED_PY = {
    "mesh_operation_manager.py",
    "wan_usage.py",
    "v501_refresh_tune.py",
}

FAST_WORDS = (
    "topology", "topologie", "mesh", "link", "links", "client", "clients",
    "station", "stations", "peer", "peers", "live", "fast",
)
HEALTH_WORDS = (
    "cpu", "uptime", "temperature", "temp", "thermal", "health", "node_stats",
    "router_stats", "nodehealth", "routerhealth", "node_health", "router_health",
)
INTERVAL_WORDS = ("refresh", "interval", "poll", "timer", "ttl", "cache")

changes = []


def classify(text: str):
    low = text.lower()
    if any(w in low for w in HEALTH_WORDS):
        return "health"
    if any(w in low for w in FAST_WORDS):
        return "fast"
    return None


def patch_js(path: Path):
    original = path.read_text(encoding="utf-8")
    s = original
    local = []

    # 1) Nejbezpečnější případ: pojmenovaná konstanta intervalu/TTL.
    const_pat = re.compile(
        r"(?m)^(?P<prefix>\s*(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*)(?P<value>\d+(?:\.\d+)?)(?P<suffix>\s*;?\s*(?://[^\n]*)?)$"
    )
    def repl_const(m):
        name = m.group("name")
        low = name.lower()
        if not any(w in low for w in INTERVAL_WORDS):
            return m.group(0)
        kind = classify(name)
        if not kind:
            return m.group(0)
        old = float(m.group("value"))
        # JS intervaly bývají v ms; pokud je hodnota malá, ponecháme sekundovou jednotku.
        target = (FAST_MS if kind == "fast" else HEALTH_MS) if old >= 1000 else (FAST_S if kind == "fast" else HEALTH_S)
        local.append(f"{path.name}: {name} {m.group('value')} -> {target}")
        return f"{m.group('prefix')}{target}{m.group('suffix')}"
    s = const_pat.sub(repl_const, s)

    # 2) setInterval / setTimeout s pojmenovanou callback funkcí.
    timer_pat = re.compile(
        r"(?P<head>\bset(?:Interval|Timeout)\(\s*(?P<cb>[A-Za-z_$][\w$]*)\s*,\s*)(?P<delay>[^\)\n]+)(?P<tail>\))"
    )
    def repl_timer(m):
        kind = classify(m.group("cb"))
        if not kind:
            return m.group(0)
        target = FAST_MS if kind == "fast" else HEALTH_MS
        # Nedotýkat se jednorázových velmi krátkých UI timeoutů.
        delay = m.group("delay").strip()
        if re.fullmatch(r"\d+", delay) and int(delay) < 1000:
            return m.group(0)
        local.append(f"{path.name}: {m.group('cb')} timer {delay} -> {target}")
        return f"{m.group('head')}{target}{m.group('tail')}"
    s = timer_pat.sub(repl_timer, s)

    # 3) Arrow callback na jednom řádku: setInterval(() => refreshTopology(...), X)
    arrow_pat = re.compile(
        r"(?P<head>\bset(?:Interval|Timeout)\(\s*\(\s*\)\s*=>\s*(?P<cb>[A-Za-z_$][\w$]*)\s*\([^\n\)]*\)\s*,\s*)(?P<delay>[^\)\n]+)(?P<tail>\))"
    )
    def repl_arrow(m):
        kind = classify(m.group("cb"))
        if not kind:
            return m.group(0)
        target = FAST_MS if kind == "fast" else HEALTH_MS
        delay = m.group("delay").strip()
        local.append(f"{path.name}: arrow {m.group('cb')} {delay} -> {target}")
        return f"{m.group('head')}{target}{m.group('tail')}"
    s = arrow_pat.sub(repl_arrow, s)

    # 4) Konzervativní line fallback: pouze řádky, kde je zároveň význam
    #    refreshu a příslušné semantické slovo. Žádné globální nahrazování.
    lines = []
    for line in s.splitlines(keepends=True):
        low_line = line.lower()
        kind = classify(low_line)
        if kind and ("setinterval" in low_line or "settimeout" in low_line or any(w in low_line for w in INTERVAL_WORDS)):
            target = FAST_MS if kind == "fast" else HEALTH_MS
            # Jen zjevné časové literály >= 5 s; ostatní čísla (rozměry apod.) necháme.
            def _num_repl(mm):
                value = int(mm.group(0))
                if value >= 5000 and value != target:
                    local.append(f"{path.name}: line timer {value} -> {target}")
                    return str(target)
                return mm.group(0)
            line = re.sub(r"(?<![A-Za-z0-9_])(?:600000|300000|120000|60000|30000|15000|10000|5000)(?![A-Za-z0-9_])", _num_repl, line)
        lines.append(line)
    s = "".join(lines)

    if s != original:
        path.write_text(s, encoding="utf-8")
        changes.extend(local or [f"{path.name}: upraven refresh"])


def patch_py(path: Path):
    original = path.read_text(encoding="utf-8")
    s = original
    local = []

    # Pouze jasně pojmenované CACHE/TTL/REFRESH/POLL/INTERVAL konstanty.
    pat = re.compile(
        r"(?m)^(?P<prefix>\s*(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*)(?P<value>\d+(?:\.\d+)?)(?P<suffix>\s*(?:#.*)?)$"
    )
    def repl(m):
        name = m.group("name")
        low = name.lower()
        if not any(w in low for w in INTERVAL_WORDS):
            return m.group(0)
        kind = classify(name)
        if not kind:
            return m.group(0)
        old = float(m.group("value"))
        # Python backend intervaly jsou typicky v sekundách; pokud jsou očividně ms, použij ms.
        target = (FAST_MS if kind == "fast" else HEALTH_MS) if old >= 1000 else (FAST_S if kind == "fast" else HEALTH_S)
        local.append(f"{path.name}: {name} {m.group('value')} -> {target}")
        return f"{m.group('prefix')}{target}{m.group('suffix')}"
    s = pat.sub(repl, s)

    if s != original:
        path.write_text(s, encoding="utf-8")
        changes.extend(local or [f"{path.name}: backend refresh upraven"])


if STATIC.exists():
    for path in sorted(STATIC.glob("*.js")):
        if path.name in EXCLUDED_JS:
            continue
        try:
            patch_js(path)
        except UnicodeDecodeError:
            pass

for path in sorted(ROOT.glob("*.py")):
    if path.name in EXCLUDED_PY or path.name.endswith("_patch.py"):
        continue
    try:
        patch_py(path)
    except UnicodeDecodeError:
        pass

report = {
    "version": "5.0.1",
    "topology_mesh_clients_ms": FAST_MS,
    "cpu_uptime_ms": HEALTH_MS,
    "changes": changes,
}
try:
    (ROOT / "v501_refresh_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception:
    pass

if changes:
    print("v5.0.1 refresh tuning:")
    for line in changes:
        print(" -", line)
else:
    print("v5.0.1 WARNING: nebyl nalezen žádný bezpečně rozpoznaný starý refresh timer; build pokračuje beze změny ostatních funkcí.")
