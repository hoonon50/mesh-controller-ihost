from pathlib import Path
import os
import re

ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"

if not APP.exists():
    raise SystemExit("v6.0.6: app.py nenalezen")
if not INDEX.exists():
    raise SystemExit("v6.0.6: templates/index.html nenalezen")

app = APP.read_text(encoding="utf-8")
marker = "# v5.0.7 explicit live topology API"
if marker not in app:
    m = re.search(r"(?m)^(\s*app\s*=\s*Flask\([^\n]*\)\s*)$", app)
    if not m:
        raise SystemExit("v6.0.6: nepodařilo se najít app = Flask(...)")
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

css_tag = '<link rel="stylesheet" href="/static/v503_live_topology.css?v=6.0.6">'
js_tag = '<script src="/static/v503_live_topology.js?v=6.0.6"></script>'

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
        raise SystemExit("v6.0.6: index.html nemá </head>")
    html = re.sub(r"</head>", f"  {css_tag}\n</head>", html, count=1, flags=re.I)
if js_tag not in html:
    if "</body>" not in html.lower():
        raise SystemExit("v6.0.6: index.html nemá </body>")
    html = re.sub(r"</body>", f"  {js_tag}\n</body>", html, count=1, flags=re.I)

# Cache bust Operation Manageru.
html = re.sub(
    r'(<link\s+[^>]*href=["\']/static/v500_operation\.css\?v=)[^"\']+(["\'][^>]*>)',
    r'\g<1>6.0.3\2', html, flags=re.I,
)
html = re.sub(
    r'(<script\s+[^>]*src=["\']/static/v500_operation\.js\?v=)[^"\']+(["\'][^>]*></script>)',
    r'\g<1>6.0.3\2', html, flags=re.I,
)

INDEX.write_text(html, encoding="utf-8")
print("v6.0.6: explicitní /api/v503/live-topology + vlastní živý topology renderer")
print("v6.0.6: starý v5.0.2 timer interception odstraněn")
