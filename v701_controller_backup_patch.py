from pathlib import Path
import os
import re

VERSION = "7.0.1"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"
OPS = ROOT / "mesh_operation_manager.py"
OWUT = ROOT / "owut_manager.py"
LIVE = ROOT / "live_topology_v503.py"
LAN = ROOT / "lan_port_control_v620.py"
VERSIONED = [
    OPS,
    OWUT,
    LIVE,
    LAN,
    ROOT / "topology_inspector_v631.py",
    ROOT / "lan_port_inspector_v630.py",
    ROOT / "client_ip_resolver_v632.py",
]


def sub_once(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    new, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"v{VERSION}: nenalezen patch bod: {label}")
    return new


# ---------------------------------------------------------------------- app --
app = APP.read_text(encoding="utf-8")
restore_marker = "# v7.0.1 controller restore before /data consumers"
if restore_marker not in app:
    app = sub_once(
        app,
        r'(?m)^from mesh_core import controller\s*$',
        restore_marker + '\nfrom controller_backup_v701 import apply_pending_restore\napply_pending_restore()\n\nfrom mesh_core import controller',
        "restore before mesh_core",
    )

init_marker = "# v7.0.1 controller backup manager"
if init_marker not in app:
    app = sub_once(
        app,
        r'(?m)^(init_operation_manager\(app\)\s*)$',
        r'\1\n' + init_marker + '\nfrom controller_backup_v701 import init_controller_backup_v701\ninit_controller_backup_v701(app)',
        "backup manager init",
    )
APP.write_text(app, encoding="utf-8")


# -------------------------------------------------------- persistent OWUT --
ops = OPS.read_text(encoding="utf-8")
ops = sub_once(
    ops,
    r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
    f'VERSION = "{VERSION}"',
    "operation version",
)
ops = re.sub(r'START v\d+\.\d+\.\d+:', f'START v{VERSION}:', ops)
ops = re.sub(r'Persistent Operation Manager v\d+\.\d+\.\d+', f'Persistent Operation Manager v{VERSION}', ops)
ops = re.sub(r'OpenWRT MESH CONTROLLER PRO v\d+\.\d+\.\d+', f'OpenWRT MESH CONTROLLER PRO v{VERSION}', ops)

if '"controller_backup": {}' not in ops:
    ops = sub_once(
        ops,
        r'(\s+"owut_checks": \{\},\n)',
        r'\1        "controller_backup": {},\n',
        "operation controller_backup state",
    )

guard_marker = "# v7.0.1 automatic controller/Nextcloud backup gate"
if guard_marker not in ops:
    pattern = r'(    def _run_owut\(self, resume: bool = False\) -> None:\n        try:\n            state = self\.snapshot\(\)\n)'
    replacement = r'''\1            ''' + guard_marker + r'''
            if bool(state.get("automatic")) and not resume and not state.get("controller_backup"):
                from controller_backup_v701 import automatic_backup_result_for_now
                controller_backup = automatic_backup_result_for_now()
                self._set(controller_backup=controller_backup)
                state = self.snapshot()
                if not bool(controller_backup.get("ok")):
                    detail = str(controller_backup.get("detail") or "Předautomatická záloha není potvrzená.")
                    raise RuntimeError(f"NEXTCLOUD BACKUP: CHYBA – {detail} Automatický OWUT nebyl spuštěn.")
'''
    ops = sub_once(ops, pattern, replacement, "automatic backup gate")

report_marker = "# v7.0.1 controller backup report block"
if report_marker not in ops:
    ops = sub_once(
        ops,
        r'(        ihost_text = f"\{ihost_temp\} °C" if ihost_temp is not None else "N/A"\n)',
        r'''\1        ''' + report_marker + r'''
        controller_backup = state.get("controller_backup") or {}
        auto_owut = state.get("kind") == "owut_upgrade" and bool(state.get("automatic"))
        controller_backup_text = ""
        controller_backup_html = ""
        if auto_owut:
            local_ok = bool(controller_backup.get("local_backup_ok"))
            nextcloud_ok = bool(controller_backup.get("nextcloud_ok"))
            filename = str(controller_backup.get("filename") or "—")
            backup_detail = str(controller_backup.get("detail") or "")
            controller_backup_text = (
                f"\nCONTROLLER BACKUP: {'OK' if local_ok else 'CHYBA'}"
                f"\nNEXTCLOUD BACKUP: {'OK' if nextcloud_ok else 'CHYBA'}"
                f"\nSOUBOR: {filename}"
            )
            if backup_detail:
                controller_backup_text += f"\nBACKUP DETAIL: {backup_detail}"
            nc_color = "#16a34a" if nextcloud_ok else "#dc2626"
            local_color = "#16a34a" if local_ok else "#dc2626"
            controller_backup_html = (
                '<tr><td style="padding:0 20px 18px">'
                '<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;font-size:12px">'
                '<tr style="background:#f8fafc"><th colspan="2" style="padding:8px;text-align:left">ZÁLOHA CONTROLLERU PŘED AUTOMATICKÝM OWUT</th></tr>'
                f'<tr><td style="padding:7px 8px">CONTROLLER BACKUP</td><td style="padding:7px 8px;color:{local_color};font-weight:700">{"OK" if local_ok else "CHYBA"}</td></tr>'
                f'<tr><td style="padding:7px 8px">NEXTCLOUD BACKUP</td><td style="padding:7px 8px;color:{nc_color};font-weight:700">{"OK" if nextcloud_ok else "CHYBA"}</td></tr>'
                f'<tr><td style="padding:7px 8px">SOUBOR</td><td style="padding:7px 8px;color:#334155">{html.escape(filename)}</td></tr>'
                + (f'<tr><td style="padding:7px 8px">DETAIL</td><td style="padding:7px 8px;color:#64748b">{html.escape(backup_detail)}</td></tr>' if backup_detail else '')
                + '</table></td></tr>'
            )
''',
        "report backup variables",
    )
    ops = sub_once(
        ops,
        r'\+ f"\\n\\niHost teplota: \{ihost_text\}\\n\\n\{state\.get\(\'message\',\'\'\)\}"',
        '+ f"\\n\\niHost teplota: {ihost_text}" + controller_backup_text + f"\\n\\n{state.get(\'message\',\'\')}"',
        "text report backup insertion",
    )
    ops = sub_once(
        ops,
        r'(\{\'\'\.join\(html_rows\)\}</table></td></tr>\n)(<tr><td style="padding:0 20px 20px;color:#334155;font-size:12px">Záloha:)',
        r'\1{controller_backup_html}\n\2',
        "html report backup insertion",
    )

OPS.write_text(ops, encoding="utf-8")


# -------------------------------------------------------------- UI/version --
for module in VERSIONED:
    if module == OPS or not module.exists():
        continue
    text = module.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', text, count=1)
    module.write_text(text, encoding="utf-8")

html_text = INDEX.read_text(encoding="utf-8")
html_text = re.sub(r'<title>.*?</title>', f'<title>OpenWRT MESH CONTROLLER PRO · v.{VERSION}</title>', html_text, count=1, flags=re.S)
html_text = re.sub(r'<span class="app-version">v\.[^<]+</span>', f'<span class="app-version">v.{VERSION}</span>', html_text, count=1)

css_tag = f'<link rel="stylesheet" href="/static/v701_controller_backup.css?v={VERSION}">'
js_tag = f'<script src="/static/v701_controller_backup.js?v={VERSION}"></script>'
if css_tag not in html_text:
    html_text = html_text.replace('</head>', f'  {css_tag}\n</head>', 1)

card_marker = 'id="controllerBackupCard"'
if card_marker not in html_text:
    card = '''\n  <section class="card controller-backup-card" id="controllerBackupCard">
    <div class="card-head"><div><h2>ZÁLOHA CONTROLLERU</h2></div></div>
    <div class="controller-backup-grid">
      <div class="controller-backup-panel">
        <h3>RUČNÍ ZÁLOHA / OBNOVA</h3>
        <div class="controller-backup-note">Záloha obsahuje nastavení a persistentní data Controlleru včetně měsíční WAN statistiky. Zálohy OpenWrt routerů v <b>/data/backups</b> se do tohoto archivu nezahrnují.</div>
        <div class="controller-backup-actions">
          <button id="cbExport" class="good-btn">STÁHNOUT DO PC</button>
          <button id="cbImport" class="warn">IMPORTOVAT Z PC</button>
          <input id="cbImportFile" type="file" accept=".tar.gz,.tgz,application/gzip">
        </div>
      </div>
      <div class="controller-backup-panel">
        <h3>NEXTCLOUD · AUTOMATICKY 10 MINUT PŘED OWUT</h3>
        <div class="controller-backup-form">
          <label for="cbNextcloudServer">IP / HOSTNAME / URL</label><input id="cbNextcloudServer" type="text" placeholder="https://nextcloud.example.cz nebo 192.168.30.x">
          <label for="cbNextcloudUser">UŽIVATEL</label><input id="cbNextcloudUser" type="text" autocomplete="username">
          <label for="cbNextcloudPassword">HESLO / APP PASSWORD</label><input id="cbNextcloudPassword" type="password" autocomplete="new-password">
          <label for="cbNextcloudDir">CÍLOVÝ ADRESÁŘ</label><input id="cbNextcloudDir" type="text" value="/OpenWRT-MESH-CONTROLLER">
        </div>
        <div class="controller-backup-actions">
          <button id="cbNextcloudTest" class="secondary">TEST PŘIPOJENÍ</button>
          <button id="cbNextcloudSave" class="good-btn">ULOŽIT</button>
        </div>
        <div class="controller-backup-note">Den ani čas se zde nenastavuje. Automatika vždy použije den a čas z automatického OWUT a spustí Nextcloud zálohu přesně o 10 minut dříve.</div>
      </div>
    </div>
    <div id="cbStatus" class="controller-backup-status">Načítám stav zálohy…</div>
    <div id="cbNextRun" class="controller-backup-next"></div>
  </section>\n'''
    html_text = html_text.replace('  <section class="card clients-card">', card + '\n  <section class="card clients-card">', 1)

if js_tag not in html_text:
    html_text = html_text.replace('</body>', f'  {js_tag}\n</body>', 1)

# Cache-busting i pro stávající assety; funkční logiku jejich obsahu neměníme.
html_text = re.sub(r'(/static/[A-Za-z0-9_.-]+\.(?:css|js)\?v=)[^"\']+', rf'\g<1>{VERSION}', html_text)
INDEX.write_text(html_text, encoding="utf-8")


# ----------------------------------------------------------- build safeguards --
app_check = APP.read_text(encoding="utf-8")
ops_check = OPS.read_text(encoding="utf-8")
index_check = INDEX.read_text(encoding="utf-8")
checks = {
    "restore before mesh_core": app_check.find('apply_pending_restore()') < app_check.find('from mesh_core import controller'),
    "backup manager init": 'init_controller_backup_v701(app)' in app_check,
    "automatic OWUT gate": guard_marker in ops_check and 'automatic_backup_result_for_now' in ops_check,
    "existing report extended": 'NEXTCLOUD BACKUP' in ops_check and 'controller_backup_html' in ops_check,
    "controller backup card": card_marker in index_check,
    "manual export/import UI": 'cbExport' in index_check and 'cbImport' in index_check,
    "no Nextcloud schedule selector": 'cbNextcloudTime' not in index_check and 'cbNextcloudWeekday' not in index_check,
    "version": f'v.{VERSION}' in index_check,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f"v{VERSION}: build safeguard selhal: {', '.join(failed)}")

print(f"v{VERSION}: controller-only export/import + Nextcloud WebDAV backup integrated")
print(f"v{VERSION}: automatic Nextcloud backup is fixed at OWUT schedule minus 10 minutes")
print(f"v{VERSION}: existing HTML OWUT report extended with CONTROLLER/NEXTCLOUD BACKUP status")
print(f"v{VERSION}: /data/backups router archives are excluded; WAN monthly history remains included")
