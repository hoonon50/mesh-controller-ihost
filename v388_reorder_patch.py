from pathlib import Path
import re

ROOT = Path('/app')
MANAGER = ROOT / 'owut_manager.py'
JS = ROOT / 'static' / 'owut_manager.js'
INDEX = ROOT / 'templates' / 'index.html'

if not MANAGER.exists():
    raise SystemExit('v3.8.8: /app/owut_manager.py nenalezen')

s = MANAGER.read_text(encoding='utf-8')

old_order = '''UPDATE_ORDER = [
    ("192.168.30.2", "MESH1"),
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
    ("192.168.30.1", "ROUTER"),
]'''
new_order = '''UPDATE_ORDER = [
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
    ("192.168.30.2", "MESH1"),  # iHost je LAN kabelem na MESH1 -> aktualizovat jako poslední satelit
    ("192.168.30.1", "ROUTER"),
]'''

if old_order in s:
    s = s.replace(old_order, new_order, 1)
elif new_order not in s:
    # Robustní fallback pro případ drobně změněného formátování.
    pattern = re.compile(
        r'UPDATE_ORDER\s*=\s*\[\s*'
        r'\("192\.168\.30\.2"\s*,\s*"MESH1"\)\s*,\s*'
        r'\("192\.168\.30\.3"\s*,\s*"MESH2"\)\s*,\s*'
        r'\("192\.168\.30\.4"\s*,\s*"MESH3"\)\s*,\s*'
        r'\("192\.168\.30\.5"\s*,\s*"MESH4"\)\s*,\s*'
        r'\("192\.168\.30\.1"\s*,\s*"ROUTER"\)\s*,?\s*\]',
        re.S,
    )
    s2, n = pattern.subn(new_order, s, count=1)
    if n != 1:
        raise SystemExit('v3.8.8: nepodařilo se bezpečně najít UPDATE_ORDER')
    s = s2

# Pojistka před aktualizací hlavního ROUTERu .1.
# Vkládá se přímo do skutečného upgrade loopu, ne do preflightu.
guard_marker = 'v3.8.8 MESH1-LAN guard'
if guard_marker not in s:
    loop_start = s.find('# 5) Satelity první, hlavní router poslední.')
    if loop_start < 0:
        # Komentář mohl být v novější verzi pozměněn; vezmeme upgrade loop podle volání start_owut.
        loop_start = s.find('for idx, (ip, label) in enumerate(UPDATE_ORDER, 1):', s.find('def _upgrade_worker'))
    if loop_start < 0:
        raise SystemExit('v3.8.8: upgrade loop nebyl nalezen')

    loop_end = s.find('# 6) Finální kontrola celé sítě.', loop_start)
    if loop_end < 0:
        # Fallback: konec funkce před except/finally.
        loop_end = s.find('\n        # 6)', loop_start)
    if loop_end < 0:
        loop_end = s.find('\n        overall_ok = True', loop_start)
    if loop_end < 0:
        raise SystemExit('v3.8.8: konec upgrade loopu nebyl nalezen')

    block = s[loop_start:loop_end]
    m = re.search(
        r'(?m)^(?P<indent>\s*)_op_log\(f"\{label\}: spouštím owut upgrade…", base_progress\)\s*$',
        block,
    )
    if not m:
        raise SystemExit('v3.8.8: místo pro MESH1-LAN guard nebylo nalezeno')

    indent = m.group('indent')
    original_line = m.group(0)
    guard = (
        f'{indent}# {guard_marker}\n'
        f'{indent}if ip == MAIN_IP:\n'
        f'{indent}    _op_log("Před ROUTERem .1 ověřuji návrat MESH1 .2 a dostupnost ROUTERu .1…", 90)\n'
        f'{indent}    if not _wait_online(controller, "192.168.30.2", 360):\n'
        f'{indent}        raise RuntimeError("MESH1 (192.168.30.2) se po aktualizaci nevrátil online; ROUTER .1 nebude aktualizován.")\n'
        f'{indent}    if not _wait_online(controller, MAIN_IP, 180):\n'
        f'{indent}        raise RuntimeError("ROUTER (192.168.30.1) není po návratu MESH1 dostupný; sysupgrade .1 nebude spuštěn.")\n'
        f'{indent}    _op_log("MESH1 .2 i ROUTER .1 jsou dostupné – pokračuji na hlavní router.", 91)\n'
        f'{indent}    time.sleep(5)\n'
    )
    block = block[:m.start()] + guard + original_line + block[m.end():]
    s = s[:loop_start] + block + s[loop_end:]

MANAGER.write_text(s, encoding='utf-8')

# Text v UI – uživatel hned vidí skutečné bezpečné pořadí.
if JS.exists():
    j = JS.read_text(encoding='utf-8')
    j = j.replace(
        'MESH1 → MESH4 → ROUTER',
        'MESH2 → MESH3 → MESH4 → MESH1 → ROUTER',
    )
    j = j.replace(
        'MESH1 - MESH4 - ROUTER',
        'MESH2 - MESH3 - MESH4 - MESH1 - ROUTER',
    )
    JS.write_text(j, encoding='utf-8')

# Cache bust pro nový JS/CSS, aby po update nebyla v prohlížeči stará verze.
if INDEX.exists():
    h = INDEX.read_text(encoding='utf-8')
    h = re.sub(r'(/static/owut_manager\.js\?v=)[^"\']+', r'\g<1>3.8.8', h)
    h = re.sub(r'(/static/owut_manager\.css\?v=)[^"\']+', r'\g<1>3.8.8', h)
    INDEX.write_text(h, encoding='utf-8')

print('v3.8.8: UPDATE_ORDER = MESH2 -> MESH3 -> MESH4 -> MESH1 -> ROUTER')
print('v3.8.8: před ROUTER .1 se ověřuje MESH1 .2 + ROUTER .1')
