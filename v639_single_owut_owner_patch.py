from pathlib import Path
import os
import re

VERSION = "6.3.9"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
OWUT = ROOT / "owut_manager.py"
OPS = ROOT / "mesh_operation_manager.py"
INDEX = ROOT / "templates" / "index.html"
V500_JS = ROOT / "static" / "v500_operation.js"

for required in (OWUT, OPS):
    if not required.exists():
        raise SystemExit(f"v{VERSION}: {required.name} nenalezen")

# ---------------------------------------------------------------- OWUT --
owut = OWUT.read_text(encoding="utf-8")

# 1) Starý scheduler v owut_manager.py je definitivně neaktivní.
# PersistentMeshOperationManager je jediný vlastník automatického OWUT plánování.
legacy_scheduler = re.compile(
    r"def _scheduler_loop\(controller\) -> None:.*?(?=\n\ndef register_owut_manager\()",
    re.S,
)
replacement_scheduler = '''def _scheduler_loop(controller) -> None:
    # v6.3.9: automatický OWUT vlastní výhradně PersistentMeshOperationManager.
    # Funkce zůstává jen kvůli kompatibilitě staršího modulu; nesmí spouštět OWUT.
    return
'''
owut, scheduler_count = legacy_scheduler.subn(replacement_scheduler, owut, count=1)
if scheduler_count != 1:
    raise SystemExit(f"v{VERSION}: starý _scheduler_loop v owut_manager.py nenalezen")

old_thread_pattern = re.compile(
    r'(?m)^\s*threading\.Thread\(target=_scheduler_loop,\s*args=\(controller,\),\s*daemon=True,\s*name="owut-scheduler"\)\.start\(\)\s*$'
)
owut, thread_count = old_thread_pattern.subn(
    '    # v6.3.9: legacy owut scheduler se nespouští; scheduler vlastní mesh_operation_v500.',
    owut,
    count=1,
)
if thread_count != 1:
    raise SystemExit(f"v{VERSION}: start legacy owut-scheduler threadu nenalezen")

# 2) Staré POST /api/owut/upgrade už nesmí spouštět legacy _upgrade_worker.
# Kvůli zpětné kompatibilitě endpoint zůstane, ale deleguje na persistent manager.
legacy_upgrade_route = re.compile(
    r'    @app\.post\("/api/owut/upgrade"\)\n'
    r'    def owut_upgrade_start\(\):.*?'
    r'(?=\n\n    @app\.post\("/api/owut/overlay-setup"\))',
    re.S,
)
replacement_route = '''    @app.post("/api/owut/upgrade")
    def owut_upgrade_start():
        manager = app.extensions.get("mesh_operation_v500") if hasattr(app, "extensions") else None
        if manager is None:
            return jsonify({"ok": False, "error": "Persistent Operation Manager není dostupný."}), 503
        ok, detail = manager.start_operation("owut_upgrade", automatic=False, source="legacy-api")
        return jsonify({"ok": ok, "message": detail, "state": manager.snapshot()}), (200 if ok else 409)
'''
owut, route_count = legacy_upgrade_route.subn(replacement_route, owut, count=1)
if route_count != 1:
    raise SystemExit(f"v{VERSION}: legacy /api/owut/upgrade route nenalezena")

# Build-time pojistky: starý scheduler ani starý upgrade worker nesmí být z API dosažitelný.
if 'threading.Thread(target=_scheduler_loop' in owut or 'name="owut-scheduler"' in owut:
    raise SystemExit(f"v{VERSION}: legacy scheduler thread je po patchi stále aktivní")
if 'threading.Thread(target=_upgrade_worker, args=(controller, False)' in owut:
    raise SystemExit(f"v{VERSION}: legacy /api/owut/upgrade stále spouští _upgrade_worker")
if 'source="legacy-api"' not in owut or 'app.extensions.get("mesh_operation_v500")' not in owut:
    raise SystemExit(f"v{VERSION}: legacy upgrade route nedeleguje na persistent manager")

OWUT.write_text(owut, encoding="utf-8")

# ------------------------------------------------ Persistent manager --
ops = OPS.read_text(encoding="utf-8")
ops = re.sub(
    r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
    f'VERSION = "{VERSION}"',
    ops,
    count=1,
)
ops = ops.replace('START v6.3.8:', f'START v{VERSION}:')
ops = ops.replace('Persistent Operation Manager v6.3.8', f'Persistent Operation Manager v{VERSION}')
ops = ops.replace('OpenWRT MESH CONTROLLER PRO v6.3.8', f'OpenWRT MESH CONTROLLER PRO v{VERSION}')

# Persistent scheduler i v6.3.8 Extroot flow musí po všech patchech stále existovat.
if 'self.start_operation("owut_upgrade", automatic=True, source="scheduler-v500")' not in ops:
    raise SystemExit(f"v{VERSION}: persistent scheduler-v500 OWUT start nenalezen")
if 'def _second_router_reboot_if_extroot' not in ops:
    raise SystemExit(f"v{VERSION}: persistent Extroot recovery flow nenalezen")
if 'standardní druhý reboot bez změny fstab' not in ops:
    raise SystemExit(f"v{VERSION}: v6.3.8 standardní druhý Extroot reboot není v runtime kódu")
if 'fallback fstab.extroot' not in ops:
    raise SystemExit(f"v{VERSION}: v6.3.8 Extroot fallback není v runtime kódu")

OPS.write_text(ops, encoding="utf-8")

# --------------------------------------------------------------- UI --
if V500_JS.exists():
    js = V500_JS.read_text(encoding="utf-8")
    js = re.sub(r'<span class="v500-version">v[^<]+</span>', f'<span class="v500-version">v{VERSION}</span>', js)
    V500_JS.write_text(js, encoding="utf-8")

if INDEX.exists():
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(r'(/static/v500_operation\.css\?v=)[^"\']+', rf'\g<1>{VERSION}', html)
    html = re.sub(r'(/static/v500_operation\.js\?v=)[^"\']+', rf'\g<1>{VERSION}', html)
    INDEX.write_text(html, encoding="utf-8")

print(f"v{VERSION}: jediný automatický OWUT scheduler = PersistentMeshOperationManager")
print(f"v{VERSION}: legacy owut_manager scheduler je hard-disabled a jeho thread se nespouští")
print(f"v{VERSION}: /api/owut/upgrade deleguje na persistent manager; legacy _upgrade_worker se z API nespouští")
print(f"v{VERSION}: v6.3.8 Extroot double-reboot + UUID fallback zůstává aktivní")
