from pathlib import Path
import re

root = Path('/app')

# 1) Flask route pro CPU teplotu + uptime
app_py = root / 'app.py'
text = app_py.read_text(encoding='utf-8')
hook = '''\n# v3.6.12 – CPU teplota + uptime v topologii\nfrom v369_extra import register_v369\nregister_v369(app, controller)\n'''
if 'register_v369(app, controller)' not in text:
    marker = '\nif __name__ == "__main__":'
    marker2 = "\nif __name__ == '__main__':"
    pos = text.rfind(marker)
    if pos < 0:
        pos = text.rfind(marker2)
    if pos >= 0:
        text = text[:pos] + hook + text[pos:]
    else:
        text += hook
    app_py.write_text(text, encoding='utf-8')

# 2) JS overlay + pevná výška health sekce
index = root / 'templates' / 'index.html'
html = index.read_text(encoding='utf-8')
style = '''<style id="v369-health-style">
.v369-health-card{box-sizing:border-box!important;min-height:108px!important;}
.v369-health{height:38px!important;min-height:38px!important;box-sizing:border-box!important;margin-top:4px!important;padding-top:3px!important;border-top:1px solid rgba(255,255,255,.10)!important;font-size:10px!important;line-height:15px!important;color:#e8e8ec!important;white-space:nowrap!important;text-align:left!important;overflow:hidden!important;}
.v369-health strong{color:#92929e!important;font-weight:700!important;}
</style>'''
script = '<script src="/static/v369.js?v=3.6.12"></script>'
if 'id="v369-health-style"' not in html:
    if '</head>' in html:
        html = html.replace('</head>', f'  {style}\n</head>')
    else:
        html = style + '\n' + html
if '/static/v369.js' not in html:
    if '</body>' in html:
        html = html.replace('</body>', f'  {script}\n</body>')
    else:
        html += '\n' + script + '\n'
else:
    html = re.sub(r'<script src="/static/v369\.js\?v=[^"]+"></script>', script, html)
index.write_text(html, encoding='utf-8')

# 3) v3.6.12 – běžný stav/topologie obnovovat každých 5 sekund.
# CPU + UPTIME zůstávají odděleně v /api/v369/router-health s TTL 10 minut.
app_js = root / 'static' / 'app.js'
if app_js.exists():
    js = app_js.read_text(encoding='utf-8')
    patterns = [
        r'setInterval\(\s*(loadStatus|refreshStatus|loadData|refreshData)\s*,\s*(?:30000|30_000)\s*\)',
        r'setInterval\(\s*\(\s*\)\s*=>\s*(loadStatus|refreshStatus|loadData|refreshData)\(\s*\)\s*,\s*(?:30000|30_000)\s*\)',
        r'setInterval\(\s*function\s*\(\s*\)\s*\{\s*(loadStatus|refreshStatus|loadData|refreshData)\(\s*\)\s*;?\s*\}\s*,\s*(?:30000|30_000)\s*\)',
    ]
    changed = False
    for pat in patterns:
        m = re.search(pat, js)
        if not m:
            continue
        fn = m.group(1)
        js = js[:m.start()] + f'setInterval({fn},5000)' + js[m.end():]
        changed = True
        break

    # Fallback pro jinak zapsaný 30s interval.
    if not changed:
        m = re.search(r'setInterval\(([^;\n]{1,180}),\s*(?:30000|30_000)\s*\)', js)
        if m:
            call = m.group(1)
            js = js[:m.start()] + f'setInterval({call},5000)' + js[m.end():]
            changed = True

    # Poslední fallback: druhý 5s timer ve stejném JS souboru.
    if not changed and 'v3612-graphics-refresh' not in js:
        js += """

// v3612-graphics-refresh – rychlý refresh topologie, health zůstává 10 min.
(() => {
  const refreshFn =
    (typeof loadStatus === 'function' && loadStatus) ||
    (typeof refreshStatus === 'function' && refreshStatus) ||
    (typeof loadData === 'function' && loadData) ||
    (typeof refreshData === 'function' && refreshData) || null;
  if (refreshFn) setInterval(refreshFn, 5000);
})();
"""
    app_js.write_text(js, encoding='utf-8')
