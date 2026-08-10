from pathlib import Path
import re

root = Path('/app')
app_py = root / 'app.py'
text = app_py.read_text(encoding='utf-8')
hook = '''\n# v3.7.5 – dashboard layout podle nákresu + OWUT\nfrom owut_manager import register_owut_manager\nregister_owut_manager(app, controller)\n'''
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
/* OWUT panel */
.owut-panel{margin:0!important;padding:14px!important;border:1px solid #34343c;border-radius:14px;background:#1a1a1e;color:#e8e8ec;box-sizing:border-box;width:100%!important}
.owut-title{font-size:17px;font-weight:800;letter-spacing:.04em;margin-bottom:3px}
.owut-sub{font-size:11px;color:#92929e;margin-bottom:10px}
.owut-status-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-bottom:9px}
.owut-node{padding:8px;border:1px solid #34343c;border-radius:9px;background:#222228;min-height:72px;display:flex;flex-direction:column;gap:1px;box-sizing:border-box}
.owut-node.online{border-color:rgba(0,216,111,.45)}.owut-node.offline{border-color:rgba(255,77,94,.6);opacity:.72}
.owut-node span,.owut-node small{color:#92929e;font-size:10px}.owut-mini{margin-top:3px;font-size:9px;font-weight:700}.owut-mini.ok{color:#00d86f}.owut-mini.bad{color:#ff4d5e}
.owut-actions{display:flex;flex-wrap:wrap;gap:7px;margin:8px 0}.owut-btn{border:0;border-radius:8px;padding:9px 11px;background:#34343c;color:#fff;font-size:11px;font-weight:800;cursor:pointer}.owut-btn:disabled{opacity:.45;cursor:not-allowed}.owut-btn.good{background:#236846}.owut-btn.warn{background:#8a6420}.owut-btn.danger{background:#9f3340}
.owut-progress-wrap{border:1px solid #34343c;border-radius:9px;background:#141416;padding:9px;margin-top:8px}.owut-progress-head{display:flex;justify-content:space-between;gap:10px;font-size:11px;margin-bottom:5px}.owut-progress{height:7px;border-radius:99px;background:#2b2b31;overflow:hidden}.owut-progress>div{height:100%;width:0;background:#00d86f;transition:width .2s}.owut-log{height:82px;overflow:auto;margin:7px 0 0;padding:7px;background:#0f0f11;border-radius:7px;color:#cfcfd6;font:10px/1.4 monospace;white-space:pre-wrap}
.owut-settings-title{font-size:12px;font-weight:800;margin:11px 0 7px}.owut-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.owut-form label{display:flex;flex-direction:column;gap:3px;color:#92929e;font-size:10px}.owut-form input,.owut-form select{box-sizing:border-box;width:100%;background:#222228;color:#e8e8ec;border:1px solid #34343c;border-radius:7px;padding:8px}.owut-form input[type=checkbox]{width:auto;align-self:flex-start;transform:scale(1.10);margin:7px 0 0 3px}.owut-small{font-size:9px;color:#92929e;margin-top:4px}.small-row{margin-top:7px}

/* v3.7.5 – horní dashboard přesně podle nákresu */
#topDashboardRow.top-dashboard-row{display:grid!important;grid-template-columns:minmax(0,3fr) minmax(360px,2fr)!important;gap:12px!important;align-items:stretch!important;width:100%!important;max-width:100%!important;margin:0 0 12px!important;box-sizing:border-box!important}
#topDashboardLeft.top-dashboard-left,#topDashboardRight.top-dashboard-right{display:flex!important;flex-direction:column!important;gap:10px!important;min-width:0!important;width:100%!important;box-sizing:border-box!important}
#topDashboardLeft.top-dashboard-left{align-self:stretch!important}
#topDashboardLeft>.dashboard-topology-panel{flex:1 1 auto!important;height:100%!important;min-height:100%!important;margin:0!important}
#topDashboardRight>.dashboard-progress-panel,#topDashboardRight>.dashboard-owut-panel{width:100%!important;margin:0!important;min-width:0!important;box-sizing:border-box!important}
#topDashboardRight>.dashboard-progress-panel{flex:0 0 auto!important}
#topDashboardRight>.dashboard-owut-panel{flex:1 1 auto!important}

/* LAN PORTY zůstávají přes celou šířku a nejsou měněny. */

/* spodní řádek přesně 50 / 50, stejná výška */
#maintenanceBackupRow.maintenance-backup-row-force{display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;align-items:stretch!important;width:100%!important;max-width:100%!important;gap:12px!important;box-sizing:border-box!important;margin:12px 0 0!important}
#maintenanceBackupRow.maintenance-backup-row-force>.maintenance-backup-half{display:flex!important;flex-direction:column!important;flex:1 1 0!important;flex-basis:0!important;width:0!important;min-width:0!important;max-width:none!important;grid-column:auto!important;grid-row:auto!important;align-self:stretch!important;height:auto!important;margin-top:0!important;margin-bottom:0!important;box-sizing:border-box!important}

@media(max-width:1100px){.owut-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:900px){#topDashboardRow.top-dashboard-row{grid-template-columns:1fr!important}.owut-form{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){#maintenanceBackupRow.maintenance-backup-row-force{flex-direction:column!important}#maintenanceBackupRow.maintenance-backup-row-force>.maintenance-backup-half{width:100%!important;flex-basis:auto!important}}
@media(max-width:560px){.owut-status-grid,.owut-form{grid-template-columns:1fr!important}.owut-btn{width:100%}}
</style>'''
script = '<script src="/static/owut_manager.js?v=3.7.5"></script>'

if 'id="owut-manager-style"' in html:
    html = re.sub(r'<style id="owut-manager-style">.*?</style>', style, html, flags=re.S)
else:
    html = html.replace('</head>', f'  {style}\n</head>') if '</head>' in html else style + '\n' + html

if '/static/owut_manager.js' not in html:
    html = html.replace('</body>', f'  {script}\n</body>') if '</body>' in html else html + '\n' + script
else:
    html = re.sub(r'<script src="/static/owut_manager\.js\?v=[^"]+"></script>', script, html)

index.write_text(html, encoding='utf-8')
