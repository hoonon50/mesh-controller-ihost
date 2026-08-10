from pathlib import Path

root = Path('/app')

# 1) Flask route pro CPU teplotu + uptime
app_py = root / 'app.py'
text = app_py.read_text(encoding='utf-8')
hook = '''\n# v3.6.10 – CPU teplota + uptime v topologii\nfrom v369_extra import register_v369\nregister_v369(app, controller)\n'''
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

# 2) JS overlay – načte health endpoint a doplní dvě řádky do router tile
index = root / 'templates' / 'index.html'
html = index.read_text(encoding='utf-8')
script = '<script src="/static/v369.js?v=3.6.10"></script>'
if script not in html:
    if '</body>' in html:
        html = html.replace('</body>', f'  {script}\n</body>')
    else:
        html += '\n' + script + '\n'
    index.write_text(html, encoding='utf-8')
