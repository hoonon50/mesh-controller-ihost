from pathlib import Path
import re

root = Path('/app')
app_py = root / 'app.py'
text = app_py.read_text(encoding='utf-8')
hook = '''\n# v3.8.6 – daily schedule + reliable automatic reports\nfrom owut_manager import register_owut_manager\nregister_owut_manager(app, controller)\n'''
if 'register_owut_manager(app, controller)' not in text:
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

index = root / 'templates' / 'index.html'
html = index.read_text(encoding='utf-8')

css = '<link rel="stylesheet" href="/static/owut_manager.css?v=3.8.6">'
script = '<script src="/static/owut_manager.js?v=3.8.6"></script>'

html = re.sub(r'<link rel="stylesheet" href="/static/owut_manager\.css\?v=[^"]+">', '', html)
html = re.sub(r'<script src="/static/owut_manager\.js\?v=[^"]+"></script>', '', html)

if '</head>' in html:
    html = html.replace('</head>', f'  {css}\n</head>')
else:
    html = css + '\n' + html
if '</body>' in html:
    html = html.replace('</body>', f'  {script}\n</body>')
else:
    html += '\n' + script + '\n'

index.write_text(html, encoding='utf-8')
