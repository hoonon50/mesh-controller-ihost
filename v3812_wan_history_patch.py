from pathlib import Path
import os
import re

ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
INDEX = ROOT / "templates" / "index.html"

if not INDEX.exists():
    raise SystemExit("v3.8.12: templates/index.html nenalezen")

html = INDEX.read_text(encoding="utf-8")

# Cache bust stávajících WAN dlaždic.
html = re.sub(
    r'(<link\s+[^>]*href=["\']/static/wan_usage\.css\?v=)[^"\']+(["\'][^>]*>)',
    r'\g<1>3.8.12\2',
    html,
)
html = re.sub(
    r'(<script\s+[^>]*src=["\']/static/wan_usage\.js\?v=)[^"\']+(["\'][^>]*></script>)',
    r'\g<1>3.8.12\2',
    html,
)

css_tag = '<link rel="stylesheet" href="/static/wan_history.css?v=3.8.12">'
js_tag = '<script src="/static/wan_history.js?v=3.8.12"></script>'

# Při opakovaném buildování nejdřív aktualizuj případnou starší verzi.
html = re.sub(
    r'<link\s+[^>]*href=["\']/static/wan_history\.css\?v=[^"\']+["\'][^>]*>',
    css_tag,
    html,
)
html = re.sub(
    r'<script\s+[^>]*src=["\']/static/wan_history\.js\?v=[^"\']+["\'][^>]*></script>',
    js_tag,
    html,
)

if css_tag not in html:
    if "</head>" not in html:
        raise SystemExit("v3.8.12: v index.html chybí </head>")
    html = html.replace("</head>", f"  {css_tag}\n</head>", 1)

if js_tag not in html:
    if "</body>" not in html:
        raise SystemExit("v3.8.12: v index.html chybí </body>")
    html = html.replace("</body>", f"  {js_tag}\n</body>", 1)

INDEX.write_text(html, encoding="utf-8")
print("v3.8.12: WAN DATA – HISTORIE vložena do panelu Průběh operace")
