from pathlib import Path
import os
import re

ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"
OWUT = ROOT / "owut_manager.py"

if not APP.exists():
    raise SystemExit("v5.0.0: app.py nenalezen")
if not INDEX.exists():
    raise SystemExit("v5.0.0: templates/index.html nenalezen")

# 1) Flask init – Operation Manager je samostatný a nepotřebuje browser ani starý controller.
app = APP.read_text(encoding="utf-8")
marker = "# v5.0.0 persistent operation manager"
if marker not in app:
    match = re.search(r"(?m)^(\s*app\s*=\s*Flask\([^\n]*\)\s*)$", app)
    if not match:
        raise SystemExit("v5.0.0: nepodařilo se najít app = Flask(...)")
    injection = (
        match.group(1) + "\n\n" + marker + "\n"
        + "from mesh_operation_manager import init_operation_manager\n"
        + "init_operation_manager(app)\n"
    )
    app = app[:match.start()] + injection + app[match.end():]
    APP.write_text(app, encoding="utf-8")

# 2) Vypnout starý OWUT scheduler, aby plánovaný update neběžel dvakrát.
#    V5 scheduler čte stejné /data/owut_settings.json.
if OWUT.exists():
    s = OWUT.read_text(encoding="utf-8")
    guard = "# v5.0.0 scheduler owned by PersistentMeshOperationManager"
    if guard not in s:
        pattern = re.compile(r"(?m)^(def\s+_scheduler_loop\s*\([^\n]*\)\s*:\s*)$")
        m = pattern.search(s)
        if m:
            indent = "    "
            block = (
                m.group(1) + "\n"
                + indent + guard + "\n"
                + indent + "try:\n"
                + indent*2 + "from mesh_operation_manager import v500_scheduler_owned\n"
                + indent*2 + "if v500_scheduler_owned():\n"
                + indent*3 + "return\n"
                + indent + "except Exception:\n"
                + indent*2 + "pass"
            )
            s = s[:m.start()] + block + s[m.end():]
            OWUT.write_text(s, encoding="utf-8")
        else:
            print("v5.0.0 WARNING: _scheduler_loop nebyl nalezen; zkontrolujte případný starý scheduler")

# 3) Frontend – pouze doplnění JS/CSS, žádné přestavění dashboardu.
html = INDEX.read_text(encoding="utf-8")
css_tag = '<link rel="stylesheet" href="/static/v500_operation.css?v=5.0.2">'
js_tag = '<script src="/static/v500_operation.js?v=5.0.2"></script>'

html = re.sub(r'<link\s+[^>]*href=["\']/static/v500_operation\.css\?v=[^"\']+["\'][^>]*>', css_tag, html)
html = re.sub(r'<script\s+[^>]*src=["\']/static/v500_operation\.js\?v=[^"\']+["\'][^>]*></script>', js_tag, html)
if css_tag not in html:
    if "</head>" not in html:
        raise SystemExit("v5.0.0: index.html nemá </head>")
    html = html.replace("</head>", f"  {css_tag}\n</head>", 1)
if js_tag not in html:
    if "</body>" not in html:
        raise SystemExit("v5.0.0: index.html nemá </body>")
    html = html.replace("</body>", f"  {js_tag}\n</body>", 1)
INDEX.write_text(html, encoding="utf-8")

print("v5.0.2: persistentní REBOOT + OWUT manager + explicitní live refresh")
