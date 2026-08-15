from pathlib import Path
import os
import re

VERSION = "6.3.7"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
OPS = ROOT / "mesh_operation_manager.py"
OWUT = ROOT / "owut_manager.py"

for required in (OPS, OWUT):
    if not required.exists():
        raise SystemExit(f"v{VERSION}: {required.name} nenalezen")

REBOOT_ORDER_BLOCK = '''REBOOT_ORDER = [
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
    ("192.168.30.1", "ROUTER"),
    ("192.168.30.2", "MESH1"),
]
'''

# ---------------------------------------------------------------- OPS --
ops = OPS.read_text(encoding="utf-8")

# Runtime verze Persistent Operation Manageru.
ops = re.sub(
    r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
    f'VERSION = "{VERSION}"',
    ops,
    count=1,
)

# ROLLING_ORDER zůstává OWUT pořadím. Pro čistý reboot přidáme oddělené pořadí,
# kde ROUTER naběhne dřív než MESH1. iHost je na LAN MESH1, takže poslední
# link-flap proběhne až do už plně běžící sítě s DHCP/DNS/gateway.
if "REBOOT_ORDER = [" not in ops:
    m = re.search(r'(?ms)^ROLLING_ORDER: List\[Tuple\[str, str\]\] = \[.*?^\]\n', ops)
    if not m:
        raise SystemExit(f"v{VERSION}: ROLLING_ORDER v mesh_operation_manager.py nenalezen")
    ops = ops[:m.end()] + REBOOT_ORDER_BLOCK + ops[m.end():]

run_reboot = re.compile(
    r'(def _run_reboot\(self, resume: bool = False\) -> None:.*?)(?=\n    def _run_owut\()',
    re.S,
)
m = run_reboot.search(ops)
if not m:
    raise SystemExit(f"v{VERSION}: _run_reboot blok nenalezen")
block = m.group(1)
if "enumerate(REBOOT_ORDER)" not in block:
    if "enumerate(ROLLING_ORDER)" not in block:
        raise SystemExit(f"v{VERSION}: _run_reboot nepoužívá očekávaný ROLLING_ORDER")
    block = block.replace("enumerate(ROLLING_ORDER)", "enumerate(REBOOT_ORDER)", 1)
    ops = ops[:m.start(1)] + block + ops[m.end(1):]

# Report: odstranit CPU / SoC a ponechat pouze jednoduché označení teploty.
ops = ops.replace("iHost CPU / SoC:", "iHost teplota:")
ops = ops.replace("iHost CPU: <b>", "iHost teplota: <b>")
ops = ops.replace("iHost CPU:</b>", "iHost teplota:</b>")
ops = ops.replace("Persistent Operation Manager v6.3.6", f"Persistent Operation Manager v{VERSION}")
ops = ops.replace("OpenWRT MESH CONTROLLER PRO v6.3.6", f"OpenWRT MESH CONTROLLER PRO v{VERSION}")

OPS.write_text(ops, encoding="utf-8")

# ---------------------------------------------------------------- OWUT --
owut = OWUT.read_text(encoding="utf-8")

# UPDATE_ORDER zůstává pouze pro OWUT/sysupgrade. Samostatný REBOOT_ORDER je
# používán jen endpointem /api/owut/reboot target=all.
if "REBOOT_ORDER = [" not in owut:
    m = re.search(r'(?ms)^UPDATE_ORDER = \[.*?^\]\n', owut)
    if not m:
        raise SystemExit(f"v{VERSION}: UPDATE_ORDER v owut_manager.py nenalezen")
    owut = owut[:m.end()] + REBOOT_ORDER_BLOCK + owut[m.end():]

old_targets = '            targets = UPDATE_ORDER[:]  # hlavní router poslední\n'
new_targets = '            targets = REBOOT_ORDER[:]  # běžný reboot: ROUTER před MESH1\n'
if new_targets not in owut:
    if old_targets not in owut:
        raise SystemExit(f"v{VERSION}: reboot-all targets blok nenalezen")
    owut = owut.replace(old_targets, new_targets, 1)

# Jednodušší označení teploty iHostu ve všech HTML/text reportech.
owut = owut.replace("iHost CPU / SoC:", "iHost teplota:")
owut = owut.replace("iHost CPU / SoC", "iHost teplota")

OWUT.write_text(owut, encoding="utf-8")

print(f"v{VERSION}: běžný reboot = MESH2 -> MESH3 -> MESH4 -> ROUTER -> MESH1")
print(f"v{VERSION}: OWUT/sysupgrade pořadí zůstává beze změny")
print(f"v{VERSION}: reporty používají označení 'iHost teplota'")
