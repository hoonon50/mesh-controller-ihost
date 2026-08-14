from pathlib import Path
import os
import re

RELEASE_VERSION = "6.2.0"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"
LIVE_PY = ROOT / "live_topology_v503.py"
LIVE_JS = ROOT / "static" / "v503_live_topology.js"

if not APP.exists():
    raise SystemExit(f"v{RELEASE_VERSION}: app.py nenalezen")
if not INDEX.exists():
    raise SystemExit(f"v{RELEASE_VERSION}: templates/index.html nenalezen")

# Sjednocení runtime verze bez změny funkční live-topology logiky.
if LIVE_PY.exists():
    live_py = LIVE_PY.read_text(encoding="utf-8")
    live_py = re.sub(
        r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
        f'VERSION = "{RELEASE_VERSION}"',
        live_py,
        count=1,
    )
    LIVE_PY.write_text(live_py, encoding="utf-8")

if LIVE_JS.exists():
    live_js = LIVE_JS.read_text(encoding="utf-8")
    live_js = re.sub(
        r'__MESH_V\d+_LIVE_TOPOLOGY__',
        '__MESH_V620_LIVE_TOPOLOGY__',
        live_js,
    )
    live_js = re.sub(r'LIVE v6\.0\.9', f'LIVE v{RELEASE_VERSION}', live_js)
    LIVE_JS.write_text(live_js, encoding="utf-8")

app = APP.read_text(encoding="utf-8")
marker = "# v5.0.7 explicit live topology API"
if marker not in app:
    m = re.search(r"(?m)^(\s*app\s*=\s*Flask\([^\n]*\)\s*)$", app)
    if not m:
        raise SystemExit(f"v{RELEASE_VERSION}: nepodařilo se najít app = Flask(...)")
    injection = (
        m.group(1) + "\n\n" + marker + "\n"
        + "from live_topology_v503 import init_live_topology_v503\n"
        + "init_live_topology_v503(app)\n"
    )
    app = app[:m.start()] + injection + app[m.end():]
APP.write_text(app, encoding="utf-8")

html = INDEX.read_text(encoding="utf-8")

# v5.0.7 už nepoužívá v5.0.2 interception timerů. Pokud by byl tag v šabloně
# z předchozího buildu, explicitně ho odstraníme.
html = re.sub(
    r'<script\s+[^>]*src=["\']/static/v502_live_refresh_bootstrap\.js(?:\?v=[^"\']+)?["\'][^>]*></script>\s*',
    '', html, flags=re.I,
)

css_tag = f'<link rel="stylesheet" href="/static/v503_live_topology.css?v={RELEASE_VERSION}">'
js_tag = f'<script src="/static/v503_live_topology.js?v={RELEASE_VERSION}"></script>'

html = re.sub(
    r'<link\s+[^>]*href=["\']/static/v503_live_topology\.css\?v=[^"\']+["\'][^>]*>',
    css_tag, html, flags=re.I,
)
html = re.sub(
    r'<script\s+[^>]*src=["\']/static/v503_live_topology\.js\?v=[^"\']+["\'][^>]*></script>',
    js_tag, html, flags=re.I,
)

if css_tag not in html:
    if "</head>" not in html.lower():
        raise SystemExit(f"v{RELEASE_VERSION}: index.html nemá </head>")
    html = re.sub(r"</head>", f"  {css_tag}\n</head>", html, count=1, flags=re.I)
if js_tag not in html:
    if "</body>" not in html.lower():
        raise SystemExit(f"v{RELEASE_VERSION}: index.html nemá </body>")
    html = re.sub(r"</body>", f"  {js_tag}\n</body>", html, count=1, flags=re.I)

# Cache bust Operation Manageru ponechává jeho vlastní stabilní verzi.
html = re.sub(
    r'(<link\s+[^>]*href=["\']/static/v500_operation\.css\?v=)[^"\']+(["\'][^>]*>)',
    r'\g<1>6.0.3\2', html, flags=re.I,
)
html = re.sub(
    r'(<script\s+[^>]*src=["\']/static/v500_operation\.js\?v=)[^"\']+(["\'][^>]*></script>)',
    r'\g<1>6.0.3\2', html, flags=re.I,
)

INDEX.write_text(html, encoding="utf-8")
print(f"v{RELEASE_VERSION}: explicitní /api/v503/live-topology + vlastní živý topology renderer")
print(f"v{RELEASE_VERSION}: backend/frontend verze a cache tagy sjednoceny")
