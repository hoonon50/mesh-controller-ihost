from pathlib import Path
import os
import re

VERSION = "6.3.1"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"

if not APP.exists():
    raise SystemExit("v6.3.1: app.py nenalezen")
if not INDEX.exists():
    raise SystemExit("v6.3.1: templates/index.html nenalezen")

app = APP.read_text(encoding="utf-8")
marker = "# v6.3.1 topology node device inspector"
if marker not in app:
    m = re.search(r"(?m)^(\s*app\s*=\s*Flask\([^\n]*\)\s*)$", app)
    if not m:
        raise SystemExit("v6.3.1: app = Flask(...) nenalezen")
    injection = (
        m.group(1) + "\n\n" + marker + "\n"
        + "from topology_inspector_v631 import init_topology_inspector_v631\n"
        + "init_topology_inspector_v631(app)\n"
    )
    app = app[:m.start()] + injection + app[m.end():]
APP.write_text(app, encoding="utf-8")

html = INDEX.read_text(encoding="utf-8")
css_tag = f'<link rel="stylesheet" href="/static/v631_topology_inspector.css?v={VERSION}">'
js_tag = f'<script src="/static/v631_topology_inspector.js?v={VERSION}"></script>'

html = re.sub(
    r'<link\s+[^>]*href=["\']/static/v631_topology_inspector\.css(?:\?v=[^"\']+)?["\'][^>]*>',
    css_tag, html, flags=re.I,
)
html = re.sub(
    r'<script\s+[^>]*src=["\']/static/v631_topology_inspector\.js(?:\?v=[^"\']+)?["\'][^>]*></script>',
    js_tag, html, flags=re.I,
)
if css_tag not in html:
    html = re.sub(r"</head>", f"  {css_tag}\n</head>", html, count=1, flags=re.I)
if js_tag not in html:
    html = re.sub(r"</body>", f"  {js_tag}\n</body>", html, count=1, flags=re.I)
INDEX.write_text(html, encoding="utf-8")

print("v6.3.1: topology node client inspector enabled")
