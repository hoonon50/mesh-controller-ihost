from pathlib import Path
import json
import os
import re

ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
INDEX = ROOT / "templates" / "index.html"
STATIC = ROOT / "static"

if not INDEX.exists():
    raise SystemExit("v5.0.2: templates/index.html nenalezen")
if not (STATIC / "v502_live_refresh_bootstrap.js").exists():
    raise SystemExit("v5.0.2: v502_live_refresh_bootstrap.js nenalezen")

html = INDEX.read_text(encoding="utf-8")
script_tag = '<script src="/static/v502_live_refresh_bootstrap.js?v=5.0.2"></script>'

# Odstraň starší případnou verzi bootstrapu.
html = re.sub(
    r'<script\s+[^>]*src=["\']/static/v502_live_refresh_bootstrap\.js\?v=[^"\']+["\'][^>]*></script>\s*',
    '',
    html,
)

# MUSÍ být první script v HEAD, aby zachytil skutečné registrace intervalů
# všech následně načtených skriptů dashboardu.
head = re.search(r'<head\b[^>]*>', html, flags=re.I)
if not head:
    raise SystemExit("v5.0.2: index.html nemá <head>")
insert_at = head.end()
html = html[:insert_at] + "\n  " + script_tag + html[insert_at:]

# Cache bust v5 Operation Manageru; jeho 2s interval bootstrap výslovně ignoruje.
html = re.sub(
    r'(<link\s+[^>]*href=["\']/static/v500_operation\.css\?v=)[^"\']+(["\'][^>]*>)',
    r'\g<1>5.0.2\2',
    html,
)
html = re.sub(
    r'(<script\s+[^>]*src=["\']/static/v500_operation\.js\?v=)[^"\']+(["\'][^>]*></script>)',
    r'\g<1>5.0.2\2',
    html,
)
INDEX.write_text(html, encoding="utf-8")

# Build report: kolik timerů je ve výsledných zdrojích vidět. Nejde o heuristické
# přepisování – runtime bootstrap zachytí skutečné registrace intervalů.
scan = []
for path in [INDEX, *sorted(STATIC.glob("*.js"))]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    count = len(re.findall(r'\bsetInterval\s*\(', text))
    if count:
        scan.append({"file": str(path.relative_to(ROOT)), "setInterval": count})

report = {
    "version": "5.0.2",
    "strategy": "runtime setInterval interception before dashboard scripts",
    "dashboard_ms": 5000,
    "cpu_uptime_ms": 15000,
    "excluded": ["wan_usage.js", "wan_history.js", "v500_operation.js"],
    "setInterval_sources": scan,
}
(ROOT / "v502_refresh_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)

print("v5.0.2: explicitní live-refresh bootstrap vložen jako první script v <head>")
print("v5.0.2: dashboard intervaly >=8 s -> 5 s; CPU/uptime callbacky -> 15 s")
print("v5.0.2: WAN 30 s a Operation Manager 2 s jsou výslovně vyloučeny")
