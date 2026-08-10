from pathlib import Path

root = Path('/app')
app_py = root / 'app.py'
text = app_py.read_text(encoding='utf-8')
hook = '''\n# v3.7.1 – OWUT sysupgrade / USB Extroot / Gmail report / automatika\nfrom owut_manager import register_owut_manager\nregister_owut_manager(app, controller)\n'''
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
style = '''<style id="owut-manager-style">
.owut-panel{margin:18px 0;padding:16px;border:1px solid #34343c;border-radius:14px;background:#1a1a1e;color:#e8e8ec;box-sizing:border-box}
.owut-title{font-size:18px;font-weight:800;letter-spacing:.04em;margin-bottom:3px}
.owut-sub{font-size:12px;color:#92929e;margin-bottom:13px}
.owut-status-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-bottom:12px}
.owut-node{padding:10px;border:1px solid #34343c;border-radius:10px;background:#222228;min-height:84px;display:flex;flex-direction:column;gap:2px}
.owut-node.online{border-color:rgba(0,216,111,.45)}.owut-node.offline{border-color:rgba(255,77,94,.6);opacity:.72}
.owut-node span,.owut-node small{color:#92929e;font-size:11px}.owut-mini{margin-top:4px;font-size:10px;font-weight:700}.owut-mini.ok{color:#00d86f}.owut-mini.bad{color:#ff4d5e}
.owut-actions{display:flex;flex-wrap:wrap;gap:8px;margin:9px 0}.owut-btn{border:0;border-radius:9px;padding:10px 13px;background:#34343c;color:#fff;font-weight:800;cursor:pointer}.owut-btn:disabled{opacity:.45;cursor:not-allowed}.owut-btn.good{background:#236846}.owut-btn.warn{background:#8a6420}.owut-btn.danger{background:#9f3340}
.owut-progress-wrap{border:1px solid #34343c;border-radius:10px;background:#141416;padding:10px;margin-top:10px}.owut-progress-head{display:flex;justify-content:space-between;gap:12px;font-size:12px;margin-bottom:6px}.owut-progress{height:8px;border-radius:99px;background:#2b2b31;overflow:hidden}.owut-progress>div{height:100%;width:0;background:#00d86f;transition:width .2s}.owut-log{height:120px;overflow:auto;margin:9px 0 0;padding:8px;background:#0f0f11;border-radius:8px;color:#cfcfd6;font:11px/1.45 monospace;white-space:pre-wrap}
.owut-settings-title{font-size:13px;font-weight:800;margin:15px 0 8px}.owut-form{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.owut-form label{display:flex;flex-direction:column;gap:4px;color:#92929e;font-size:11px}.owut-form input,.owut-form select{box-sizing:border-box;width:100%;background:#222228;color:#e8e8ec;border:1px solid #34343c;border-radius:8px;padding:9px}.owut-form input[type=checkbox]{width:auto;align-self:flex-start;transform:scale(1.15);margin:8px 0 0 3px}.owut-small{font-size:10px;color:#92929e;margin-top:5px}.small-row{margin-top:8px}
@media(max-width:900px){.owut-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.owut-form{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.owut-status-grid,.owut-form{grid-template-columns:1fr}.owut-btn{width:100%}}
</style>'''
script = '<script src="/static/owut_manager.js?v=3.7.1"></script>'
if 'id="owut-manager-style"' not in html:
    html = html.replace('</head>', f'  {style}\n</head>') if '</head>' in html else style + '\n' + html
if '/static/owut_manager.js' not in html:
    html = html.replace('</body>', f'  {script}\n</body>') if '</body>' in html else html + '\n' + script
else:
    import re
    html = re.sub(r'<script src="/static/owut_manager\.js\?v=[^"]+"></script>', script, html)
index.write_text(html, encoding='utf-8')
