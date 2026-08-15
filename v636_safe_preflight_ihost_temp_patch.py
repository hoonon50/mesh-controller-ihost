from pathlib import Path
import os
import re

VERSION = "6.3.6"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
OWUT = ROOT / "owut_manager.py"
OPS = ROOT / "mesh_operation_manager.py"
LIVE = ROOT / "live_topology_v503.py"
LIVE_JS = ROOT / "static" / "v503_live_topology.js"
INDEX = ROOT / "templates" / "index.html"
VERSIONED_MODULES = [
    ROOT / "topology_inspector_v631.py",
    ROOT / "lan_port_inspector_v630.py",
    ROOT / "client_ip_resolver_v632.py",
    ROOT / "ihost_temperature_v636.py",
]

for required in (OWUT, OPS):
    if not required.exists():
        raise SystemExit(f"v{VERSION}: {required.name} nenalezen")

# ---------------------------------------------------------------- OWUT --
owut = OWUT.read_text(encoding="utf-8")

shared_import = "from ihost_temperature_v636 import read_ihost_temperature\n"
if shared_import not in owut:
    anchor = "from pathlib import Path\n"
    if anchor not in owut:
        raise SystemExit(f"v{VERSION}: nenalezen import anchor v owut_manager.py")
    owut = owut.replace(anchor, anchor + shared_import, 1)

# Všechny OWUT reporty používají jeden společný iHost thermal/hwmon reader.
temp_pattern = re.compile(
    r"def _ihost_temperature\(\) -> Optional\[float\]:.*?(?=\n\ndef _collect_temperatures\()",
    re.S,
)
owut, temp_count = temp_pattern.subn(
    "def _ihost_temperature() -> Optional[float]:\n    return read_ihost_temperature()\n",
    owut,
    count=1,
)
if temp_count != 1:
    raise SystemExit(f"v{VERSION}: nepodařilo se sjednotit OWUT iHost temperature reader")

# Pokud preflight zjistí, že na všech uzlech není co aktualizovat, výslovně
# zaznamenáme, že Extroot byl pouze přečten a nebyl proveden žádný zápis/reboot.
old_no_update = '''            extra = "OWUT na všech 5 routerech hlásí, že není co aktualizovat. Firmware nebyl flashován."
            _op_finish(True, "OWUT: není dostupná aktualizace – nic se neflashovalo.", {"ok": True, "rows": rows, "backup_id": "", "no_update": True})
            return
'''
new_no_update = '''            extra = (
                "OWUT na všech 5 routerech hlásí, že není co aktualizovat. Firmware nebyl flashován. "
                "USB Extroot byl pouze zkontrolován; /overlay ani fstab nebyly změněny a žádný reboot nebyl proveden."
            )
            _op_log("OWUT: bez změn – USB Extroot zůstává beze změny, žádný sysupgrade ani reboot.", 28)
            _op_finish(True, "OWUT: není dostupná aktualizace – nic se neflashovalo.", {"ok": True, "rows": rows, "backup_id": "", "no_update": True})
            return
'''
if new_no_update not in owut:
    if old_no_update not in owut:
        raise SystemExit(f"v{VERSION}: nenalezen no-update blok")
    owut = owut.replace(old_no_update, new_no_update, 1)

# Po prvním sysupgrade bootu nejdřív funkčně ověřit nový interní systém,
# balíčky/prerekvizity Extrootu a přesný USB disk. Teprve pak se smí zapsat
# fstab.extroot a povolit druhý reboot.
ready_helper = r"""
def _validate_extroot_first_boot(controller, expected_uuid: str) -> Tuple[bool, str]:
    expected_uuid = str(expected_uuid or "").strip()
    if not re.fullmatch(r"[0-9A-Fa-f-]{16,64}", expected_uuid):
        return False, f"Neplatné UUID pro first-boot kontrolu: {expected_uuid or 'N/A'}"

    uuid_q = shlex.quote(expected_uuid)
    cmd = f'''set -e
EXPECTED={uuid_q}
CUR_OVERLAY="$(df -P /overlay 2>/dev/null | awk 'NR==2 {{print $1}}')"
case "$CUR_OVERLAY" in
  /dev/sd*) echo "ERROR=first_boot_already_usb:$CUR_OVERLAY"; exit 41 ;;
esac

# Nový systém musí být přes SSH plně použitelný ještě před aktivací Extrootu.
. /etc/openwrt_release 2>/dev/null || true
[ -n "${{DISTRIB_RELEASE:-}}" ] || {{ echo 'ERROR=release_missing'; exit 42; }}
[ -n "${{DISTRIB_REVISION:-}}" ] || {{ echo 'ERROR=revision_missing'; exit 43; }}
for C in uci block blkid owut; do
  command -v "$C" >/dev/null 2>&1 || {{ echo "ERROR=command_missing:$C"; exit 44; }}
done

grep -qw ext4 /proc/filesystems 2>/dev/null || {{ echo 'ERROR=ext4_not_available'; exit 45; }}

PKG_LIST="$(apk list --installed 2>/dev/null || opkg list-installed 2>/dev/null || true)"
MISSING=""
for P in block-mount kmod-fs-ext4 kmod-usb-storage kmod-usb-storage-uas; do
  printf '%s\n' "$PKG_LIST" | grep -Eq "^${{P}}([ -]|$)" || MISSING="$MISSING $P"
done
[ -z "$MISSING" ] || {{ echo "ERROR=packages_missing:$MISSING"; exit 46; }}

USB_DEV="$(block info 2>/dev/null | awk -v u="$EXPECTED" 'index($0, "UUID=\"" u "\"") {{sub(/:.*/, "", $1); print $1; exit}}')"
[ -n "$USB_DEV" ] || {{ echo "ERROR=usb_uuid_not_found:$EXPECTED"; block info 2>/dev/null || true; exit 47; }}
case "$USB_DEV" in
  /dev/sd[a-z][0-9]*) ;;
  *) echo "ERROR=unexpected_usb_device:$USB_DEV"; exit 48 ;;
esac
[ -b "$USB_DEV" ] || {{ echo "ERROR=usb_not_block_device:$USB_DEV"; exit 49; }}

ACTUAL_UUID="$(blkid -s UUID -o value "$USB_DEV" 2>/dev/null || true)"
ACTUAL_TYPE="$(blkid -s TYPE -o value "$USB_DEV" 2>/dev/null || true)"
[ "$ACTUAL_UUID" = "$EXPECTED" ] || {{ echo "ERROR=uuid_mismatch:$ACTUAL_UUID"; exit 50; }}
[ "$ACTUAL_TYPE" = "ext4" ] || {{ echo "ERROR=filesystem_not_ext4:$ACTUAL_TYPE"; exit 51; }}

printf 'OK=1\nOPENWRT=%s\nREVISION=%s\nINTERNAL_OVERLAY=%s\nUSB_DEV=%s\nUUID=%s\nTYPE=%s\n' \
  "${{DISTRIB_RELEASE}}" "${{DISTRIB_REVISION}}" "$CUR_OVERLAY" "$USB_DEV" "$ACTUAL_UUID" "$ACTUAL_TYPE"
'''
    try:
        out, err, code = _ssh_exec(controller, MAIN_IP, cmd, 25)
        detail = (out + ("\n" + err if err else "")).strip()
        if code == 0 and "OK=1" in out:
            return True, detail
        return False, detail or f"First-boot Extroot kontrola skončila kódem {code}."
    except Exception as exc:
        return False, str(exc)

"""

ready_anchor = "\ndef _ensure_owut(controller, ip: str) -> Tuple[bool, str]:\n"
if "def _validate_extroot_first_boot" not in owut:
    if ready_anchor not in owut:
        raise SystemExit(f"v{VERSION}: nenalezen bod pro first-boot helper")
    owut = owut.replace(ready_anchor, ready_helper + ready_anchor, 1)

old_first_boot = '''                    _op_log(
                        f"ROUTER: první boot je na interním overlay ({first_overlay.get('device') or 'N/A'}). "
                        f"Obnovuji Extroot konfiguraci pro UUID {expected_uuid}…",
                        92,
                    )
                    cfg_ok, cfg_detail = _restore_extroot_config_after_first_boot(controller, expected_uuid)
'''
new_first_boot = '''                    _op_log(
                        f"ROUTER: první boot je na interním overlay ({first_overlay.get('device') or 'N/A'}). "
                        "Ověřuji nový OpenWrt, Extroot balíčky a USB disk…",
                        92,
                    )
                    ready_ok, ready_detail = _validate_extroot_first_boot(controller, expected_uuid)
                    if not ready_ok:
                        diag = _extroot_failure_diagnostic(controller)
                        rows.append({
                            "ip": ip,
                            "name": label,
                            "ok": False,
                            "detail": f"First-boot Extroot kontrola selhala: {ready_detail} | {diag}",
                        })
                        raise RuntimeError(
                            "ROUTER: nový interní systém není připraven pro bezpečný návrat Extrootu; "
                            "druhý reboot byl zrušen."
                        )

                    _op_log(
                        f"ROUTER: first-boot kontrola OK – {ready_detail.replace(chr(10), ' | ')[:600]}. "
                        f"Obnovuji Extroot konfiguraci pro UUID {expected_uuid}…",
                        92,
                    )
                    cfg_ok, cfg_detail = _restore_extroot_config_after_first_boot(controller, expected_uuid)
'''
if new_first_boot not in owut:
    if old_first_boot not in owut:
        raise SystemExit(f"v{VERSION}: nenalezen v6.3.5 first-boot Extroot blok")
    owut = owut.replace(old_first_boot, new_first_boot, 1)

OWUT.write_text(owut, encoding="utf-8")

# ------------------------------------------------ Persistent Operation Manager --
ops = OPS.read_text(encoding="utf-8")
if shared_import not in ops:
    anchor = "from pathlib import Path\n"
    if anchor not in ops:
        raise SystemExit(f"v{VERSION}: nenalezen import anchor v mesh_operation_manager.py")
    ops = ops.replace(anchor, anchor + shared_import, 1)

ops_temp_pattern = re.compile(
    r"    def _ihost_temperature\(self\) -> Optional\[int\]:.*?(?=\n    def _mail_settings\()",
    re.S,
)
ops, ops_temp_count = ops_temp_pattern.subn(
    "    def _ihost_temperature(self) -> Optional[float]:\n        return read_ihost_temperature()\n\n",
    ops,
    count=1,
)
if ops_temp_count != 1:
    raise SystemExit(f"v{VERSION}: nepodařilo se sjednotit Operation Manager iHost temperature reader")

OPS.write_text(ops, encoding="utf-8")

# ----------------------------------------------------------- release metadata --
if LIVE.exists():
    live = LIVE.read_text(encoding="utf-8")
    live = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', live, count=1)
    LIVE.write_text(live, encoding="utf-8")

for module in VERSIONED_MODULES:
    if module.exists():
        mod = module.read_text(encoding="utf-8")
        mod = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', mod, count=1)
        module.write_text(mod, encoding="utf-8")

if LIVE_JS.exists():
    js = LIVE_JS.read_text(encoding="utf-8")
    js = re.sub(r'LIVE v\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', f'LIVE v{VERSION}', js)
    LIVE_JS.write_text(js, encoding="utf-8")

if INDEX.exists():
    html_text = INDEX.read_text(encoding="utf-8")
    html_text = re.sub(
        r'(<link\s+[^>]*href=["\']/static/v503_live_topology\.css\?v=)[^"\']+(["\'][^>]*>)',
        rf'\g<1>{VERSION}\2', html_text, flags=re.I,
    )
    html_text = re.sub(
        r'(<script\s+[^>]*src=["\']/static/v503_live_topology\.js\?v=)[^"\']+(["\'][^>]*></script>)',
        rf'\g<1>{VERSION}\2', html_text, flags=re.I,
    )
    INDEX.write_text(html_text, encoding="utf-8")

print(f"v{VERSION}: no-update OWUT výslovně potvrzuje nulový zásah do Extrootu")
print(f"v{VERSION}: před druhým ROUTER rebootem se ověřuje nový OpenWrt, Extroot balíčky, ext4 a přesné USB UUID")
print(f"v{VERSION}: všechny OWUT/Persistent mail reporty používají společný iHost CPU/SoC temperature reader")
