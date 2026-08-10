from pathlib import Path
import os
import re

ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"

if not APP.exists():
    raise SystemExit("v3.8.9: app.py nenalezen")
if not INDEX.exists():
    raise SystemExit("v3.8.9: templates/index.html nenalezen")

app = APP.read_text(encoding="utf-8")
marker = "# v3.8.9 WAN usage"
if marker not in app:
    match = re.search(r"(?m)^(\s*app\s*=\s*Flask\([^\n]*\)\s*)$", app)
    if not match:
        raise SystemExit("v3.8.9: nepodařilo se bezpečně najít vytvoření Flask app")
    injection = (
        match.group(1)
        + "\n\n"
        + marker + "\n"
        + "from wan_usage import init_wan_usage\n"
        + "init_wan_usage(app)\n"
    )
    app = app[:match.start()] + injection + app[match.end():]
    APP.write_text(app, encoding="utf-8")

html = INDEX.read_text(encoding="utf-8")
css_tag = '<link rel="stylesheet" href="/static/wan_usage.css?v=3.8.10">'
js_tag = '<script src="/static/wan_usage.js?v=3.8.10"></script>'

if css_tag not in html:
    if "</head>" not in html:
        raise SystemExit("v3.8.9: v index.html chybí </head>")
    html = html.replace("</head>", f"  {css_tag}\n</head>", 1)

if js_tag not in html:
    if "</body>" not in html:
        raise SystemExit("v3.8.9: v index.html chybí </body>")
    html = html.replace("</body>", f"  {js_tag}\n</body>", 1)

INDEX.write_text(html, encoding="utf-8")
print("v3.8.10: WAN DOWNLOAD/UPLOAD – kompaktní horní dlaždice")
