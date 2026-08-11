from pathlib import Path
import os
import re

ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"

if not APP.exists():
    raise SystemExit("v6.0.0: app.py nenalezen")

app = APP.read_text(encoding="utf-8")
marker = "# v6.0.0 silent AP inactivity policy"
if marker not in app:
    m = re.search(r"(?m)^(\s*app\s*=\s*Flask\([^\n]*\)\s*)$", app)
    if not m:
        raise SystemExit("v6.0.0: nepodařilo se najít app = Flask(...)")
    injection = (
        m.group(1) + "\n\n" + marker + "\n"
        + "from wifi_ap_policy_v600 import init_wifi_ap_policy_v600\n"
        + "init_wifi_ap_policy_v600(app)\n"
    )
    app = app[:m.start()] + injection + app[m.end():]
APP.write_text(app, encoding="utf-8")

# Cache bust pouze existujících vlastních JS/CSS modulů. Layout se nemění.
if INDEX.exists():
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(
        r'(<link\s+[^>]*href=["\']/static/v503_live_topology\.css\?v=)[^"\']+(["\'][^>]*>)',
        r'\g<1>6.0.0\2', html, flags=re.I,
    )
    html = re.sub(
        r'(<script\s+[^>]*src=["\']/static/v503_live_topology\.js\?v=)[^"\']+(["\'][^>]*></script>)',
        r'\g<1>6.0.0\2', html, flags=re.I,
    )
    html = re.sub(
        r'(<link\s+[^>]*href=["\']/static/v500_operation\.css\?v=)[^"\']+(["\'][^>]*>)',
        r'\g<1>6.0.0\2', html, flags=re.I,
    )
    html = re.sub(
        r'(<script\s+[^>]*src=["\']/static/v500_operation\.js\?v=)[^"\']+(["\'][^>]*></script>)',
        r'\g<1>6.0.0\2', html, flags=re.I,
    )
    INDEX.write_text(html, encoding="utf-8")

print("v6.0.0: tichá startup kontrola AP max_inactivity/skip_inactivity_poll přidána")
print("v6.0.0: bez wifi reload, bez restartu, MESH rozhraní nedotčeno")
