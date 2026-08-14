from pathlib import Path
import os
import re

VERSION = "6.2.0"
ASSET_REV = "6.2.0-r2"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"

app = APP.read_text(encoding="utf-8")
marker = "# v6.2.0 LAN port runtime control"
if marker not in app:
    m = re.search(r"(?m)^(\s*app\s*=\s*Flask\([^\n]*\)\s*)$", app)
    if not m:
        raise SystemExit("v6.2.0: app = Flask(...) nenalezen")
    injection = (
        m.group(1) + "\n\n" + marker + "\n"
        + "from lan_port_control_v620 import init_lan_port_control_v620\n"
        + "init_lan_port_control_v620(app)\n"
    )
    app = app[:m.start()] + injection + app[m.end():]
APP.write_text(app, encoding="utf-8")

html = INDEX.read_text(encoding="utf-8")
css_tag = f'<link rel="stylesheet" href="/static/v620_lan_port_control.css?v={ASSET_REV}">'
js_tag = f'<script src="/static/v620_lan_port_control.js?v={ASSET_REV}"></script>'

html = re.sub(
    r'<link\s+[^>]*href=["\']/static/v620_lan_port_control\.css(?:\?v=[^"\']+)?["\'][^>]*>',
    css_tag, html, flags=re.I,
)
html = re.sub(
    r'<script\s+[^>]*src=["\']/static/v620_lan_port_control\.js(?:\?v=[^"\']+)?["\'][^>]*></script>',
    js_tag, html, flags=re.I,
)
if css_tag not in html:
    html = re.sub(r"</head>", f"  {css_tag}\n</head>", html, count=1, flags=re.I)
if js_tag not in html:
    html = re.sub(r"</body>", f"  {js_tag}\n</body>", html, count=1, flags=re.I)
INDEX.write_text(html, encoding="utf-8")

print("v6.2.0: Docker-side LAN port control enabled")
print(f"v6.2.0: LAN control asset rev {ASSET_REV}")
