from pathlib import Path
import os
import re

VERSION = "6.3.5"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
OWUT = ROOT / "owut_manager.py"
LIVE = ROOT / "live_topology_v503.py"
LIVE_JS = ROOT / "static" / "v503_live_topology.js"
INDEX = ROOT / "templates" / "index.html"
VERSIONED_MODULES = [
    ROOT / "topology_inspector_v631.py",
    ROOT / "lan_port_inspector_v630.py",
    ROOT / "client_ip_resolver_v632.py",
]

if not OWUT.exists():
    raise SystemExit(f"v{VERSION}: owut_manager.py nenalezen")

text = OWUT.read_text(encoding="utf-8")

# Helper se používá výhradně po prvním bootu ROUTERu po sysupgrade, kdy OpenWrt
# standardně běží z interního rootfs_data/UBIFS. Na aktivní USB extroot se tím
# nesahá. UUID se vždy bere z živého /overlay před začátkem upgradu.
helper = r'''
def _restore_extroot_config_after_first_boot(controller, expected_uuid: str) -> Tuple[bool, str]:
    expected_uuid = str(expected_uuid or "").strip()
    if not re.fullmatch(r"[0-9A-Fa-f-]{16,64}", expected_uuid):
        return False, f"Neplatné nebo prázdné UUID Extrootu: {expected_uuid or 'N/A'}"

    # Pojistka: tuto funkci nikdy nepoužívat, pokud už je /overlay na USB.
    current = _overlay_info(controller, MAIN_IP)
    if current.get("usb"):
        current_uuid = str(current.get("uuid") or "")
        if current_uuid and current_uuid.lower() == expected_uuid.lower():
            return True, f"USB Extroot je už aktivní ({current.get('device')}, UUID {current_uuid})."
        return False, (
            f"/overlay je už na USB {current.get('device')}, ale UUID nesouhlasí "
            f"({current_uuid or 'N/A'} != {expected_uuid})."
        )

    uuid_q = shlex.quote(expected_uuid)
    cmd = f'''set -e
EXPECTED={uuid_q}
CUR_OVERLAY="$(df -P /overlay 2>/dev/null | awk 'NR==2 {{print $1}}')"
case "$CUR_OVERLAY" in
  /dev/sd*) echo "ERROR=overlay_already_usb:$CUR_OVERLAY"; exit 31 ;;
esac

USB_DEV="$(block info 2>/dev/null | awk -v u="$EXPECTED" 'index($0, "UUID=\"" u "\"") {{sub(/:.*/, "", $1); print $1; exit}}')"
[ -n "$USB_DEV" ] || {{ echo "ERROR=usb_uuid_not_found:$EXPECTED"; block info 2>/dev/null || true; exit 32; }}

# První boot po sysupgrade je interní overlay. Právě sem musí být zapsaná
# extroot definice, aby ji PREINIT při druhém bootu našel.
uci -q delete fstab.extroot || true
uci set fstab.extroot='mount'
uci set fstab.extroot.uuid="$EXPECTED"
uci set fstab.extroot.target='/overlay'
uci set fstab.extroot.fstype='ext4'
uci set fstab.extroot.enabled='1'
uci commit fstab
sync

GOT_UUID="$(uci -q get fstab.extroot.uuid || true)"
GOT_TARGET="$(uci -q get fstab.extroot.target || true)"
GOT_TYPE="$(uci -q get fstab.extroot.fstype || true)"
GOT_ENABLED="$(uci -q get fstab.extroot.enabled || true)"
[ "$GOT_UUID" = "$EXPECTED" ] || {{ echo "ERROR=verify_uuid:$GOT_UUID"; exit 33; }}
[ "$GOT_TARGET" = "/overlay" ] || {{ echo "ERROR=verify_target:$GOT_TARGET"; exit 34; }}
[ "$GOT_TYPE" = "ext4" ] || {{ echo "ERROR=verify_fstype:$GOT_TYPE"; exit 35; }}
[ "$GOT_ENABLED" = "1" ] || {{ echo "ERROR=verify_enabled:$GOT_ENABLED"; exit 36; }}

printf 'OK=1\nUSB_DEV=%s\nUUID=%s\nINTERNAL_OVERLAY=%s\n' "$USB_DEV" "$GOT_UUID" "$CUR_OVERLAY"
'''
    try:
        out, err, code = _ssh_exec(controller, MAIN_IP, cmd, 20)
        detail = (out + ("\n" + err if err else "")).strip()
        if code == 0 and "OK=1" in out:
            return True, detail
        return False, detail or f"Obnova interního fstab skončila kódem {code}."
    except Exception as exc:
        return False, str(exc)


def _extroot_failure_diagnostic(controller) -> str:
    cmd = r'''echo '--- overlay ---'
df -P /overlay 2>/dev/null || true
echo '--- fstab ---'
uci show fstab 2>/dev/null || true
echo '--- block ---'
block info 2>/dev/null || true
echo '--- extroot log ---'
logread 2>/dev/null | grep -iE 'extroot|mount_root|block:|sda|overlay' | tail -n 35 || true
'''
    try:
        out, err, _code = _ssh_exec(controller, MAIN_IP, cmd, 15)
        value = (out + ("\n" + err if err else "")).strip()
        return value[-3500:]
    except Exception as exc:
        return f"Diagnostiku se nepodařilo načíst: {exc}"
'''

anchor = "\ndef _ensure_owut(controller, ip: str) -> Tuple[bool, str]:\n"
if "def _restore_extroot_config_after_first_boot" not in text:
    if anchor not in text:
        raise SystemExit(f"v{VERSION}: nenalezen bod pro extroot helper")
    text = text.replace(anchor, helper + anchor, 1)

old_block = '''            # Hlavní router s extrootem: po prvním bootu je dle OpenWrt potřeba ještě druhý reboot.
            if ip == MAIN_IP and rebooted:
                _op_log("ROUTER: první boot po sysupgrade OK. Provádím druhý restart kvůli USB Extroot…", 92)
                ok2, detail2 = _reboot_and_wait(controller, ip, label)
                if not ok2:
                    rows.append({"ip": ip, "name": label, "ok": False, "detail": detail2})
                    raise RuntimeError(detail2)
                time.sleep(8)
                overlay_after = _overlay_info(controller, MAIN_IP)
                if not overlay_after.get("usb"):
                    rows.append({
                        "ip": ip,
                        "name": label,
                        "ok": False,
                        "detail": f"Po druhém restartu není /overlay na USB (device={overlay_after.get('device') or 'N/A'}).",
                    })
                    raise RuntimeError("ROUTER: USB overlay se po sysupgrade neobnovil.")
                if overlay_before.get("uuid") and overlay_after.get("uuid") and overlay_before["uuid"] != overlay_after["uuid"]:
                    rows.append({
                        "ip": ip,
                        "name": label,
                        "ok": False,
                        "detail": f"UUID overlay se změnilo: {overlay_before['uuid']} -> {overlay_after['uuid']}",
                    })
                    raise RuntimeError("ROUTER: UUID USB overlay po aktualizaci nesouhlasí.")
                detail += f" Druhý reboot OK, USB overlay {overlay_after.get('device')} aktivní."
'''

new_block = '''            # v6.3.5: Extroot po sysupgrade. OpenWrt standardně potřebuje dva booty.
            # Po prvním bootu jsme na interním rootfs_data; právě tam znovu ověříme/zapíšeme
            # extroot fstab podle UUID, které bylo živě načteno PŘED sysupgrade.
            if ip == MAIN_IP and rebooted:
                expected_uuid = str(overlay_before.get("uuid") or "").strip()
                if not expected_uuid:
                    rows.append({"ip": ip, "name": label, "ok": False, "detail": "Před sysupgrade nebylo dostupné UUID USB Extrootu."})
                    raise RuntimeError("ROUTER: chybí referenční UUID USB Extrootu; druhý reboot nebude proveden.")

                time.sleep(5)
                first_overlay = _overlay_info(controller, MAIN_IP)
                if first_overlay.get("usb"):
                    first_uuid = str(first_overlay.get("uuid") or "")
                    if first_uuid.lower() != expected_uuid.lower():
                        rows.append({
                            "ip": ip,
                            "name": label,
                            "ok": False,
                            "detail": f"Po prvním bootu je /overlay na USB, ale UUID nesouhlasí: {first_uuid or 'N/A'} != {expected_uuid}.",
                        })
                        raise RuntimeError("ROUTER: po prvním bootu je aktivní neočekávaný USB overlay.")
                    _op_log(f"ROUTER: USB Extroot je aktivní už po prvním bootu ({first_overlay.get('device')}). Druhý reboot není nutný.", 94)
                    detail += f" USB Extroot aktivní po prvním bootu: {first_overlay.get('device')}."
                else:
                    _op_log(
                        f"ROUTER: první boot je na interním overlay ({first_overlay.get('device') or 'N/A'}). "
                        f"Obnovuji Extroot konfiguraci pro UUID {expected_uuid}…",
                        92,
                    )
                    cfg_ok, cfg_detail = _restore_extroot_config_after_first_boot(controller, expected_uuid)
                    if not cfg_ok:
                        diag = _extroot_failure_diagnostic(controller)
                        rows.append({
                            "ip": ip,
                            "name": label,
                            "ok": False,
                            "detail": f"Extroot fstab nebyl před druhým rebootem ověřen: {cfg_detail} | {diag}",
                        })
                        raise RuntimeError("ROUTER: interní Extroot konfigurace není ověřená; druhý reboot byl bezpečně zrušen.")

                    _op_log("ROUTER: interní fstab Extroot ověřen. Provádím druhý restart…", 93)
                    ok2, detail2 = _reboot_and_wait(controller, ip, label)
                    if not ok2:
                        rows.append({"ip": ip, "name": label, "ok": False, "detail": detail2})
                        raise RuntimeError(detail2)
                    time.sleep(8)
                    overlay_after = _overlay_info(controller, MAIN_IP)
                    if not overlay_after.get("usb"):
                        diag = _extroot_failure_diagnostic(controller)
                        rows.append({
                            "ip": ip,
                            "name": label,
                            "ok": False,
                            "detail": (
                                f"Po druhém restartu není /overlay na USB "
                                f"(device={overlay_after.get('device') or 'N/A'}). | {diag}"
                            ),
                        })
                        raise RuntimeError("ROUTER: USB overlay se po ověřené Extroot konfiguraci neobnovil.")
                    after_uuid = str(overlay_after.get("uuid") or "")
                    if not after_uuid or after_uuid.lower() != expected_uuid.lower():
                        rows.append({
                            "ip": ip,
                            "name": label,
                            "ok": False,
                            "detail": f"UUID overlay po druhém bootu nesouhlasí: {after_uuid or 'N/A'} != {expected_uuid}",
                        })
                        raise RuntimeError("ROUTER: UUID USB overlay po aktualizaci nesouhlasí.")
                    detail += (
                        f" Druhý reboot OK, USB Extroot {overlay_after.get('device')} "
                        f"UUID {after_uuid} aktivní."
                    )
'''

if new_block not in text:
    if old_block not in text:
        raise SystemExit(f"v{VERSION}: nenalezen původní blok druhého Extroot rebootu")
    text = text.replace(old_block, new_block, 1)

# Preflight nesmí pokračovat bez UUID; zařízení /dev/sd* samotné nestačí.
old_preflight = '''        if not overlay_before.get("usb"):
            raise RuntimeError(
                f"ROUTER {MAIN_IP}: USB overlay není aktivní (aktuálně {overlay_before.get('device') or 'neznámé'}). "
                "OWUT sysupgrade byl z bezpečnostních důvodů zastaven."
            )
        _op_log(
'''
new_preflight = '''        if not overlay_before.get("usb"):
            raise RuntimeError(
                f"ROUTER {MAIN_IP}: USB overlay není aktivní (aktuálně {overlay_before.get('device') or 'neznámé'}). "
                "OWUT sysupgrade byl z bezpečnostních důvodů zastaven."
            )
        if not str(overlay_before.get("uuid") or "").strip():
            raise RuntimeError(
                "ROUTER: USB Extroot je aktivní, ale nepodařilo se načíst jeho UUID. "
                "OWUT sysupgrade byl z bezpečnostních důvodů zastaven."
            )
        _op_log(
'''
if new_preflight not in text:
    if old_preflight not in text:
        raise SystemExit(f"v{VERSION}: nenalezen Extroot preflight")
    text = text.replace(old_preflight, new_preflight, 1)

OWUT.write_text(text, encoding="utf-8")

# Release metadata/cache tags; funkční live LAN/topology logika se nemění.
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
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(
        r'(<link\s+[^>]*href=["\']/static/v503_live_topology\.css\?v=)[^"\']+(["\'][^>]*>)',
        rf'\g<1>{VERSION}\2', html, flags=re.I,
    )
    html = re.sub(
        r'(<script\s+[^>]*src=["\']/static/v503_live_topology\.js\?v=)[^"\']+(["\'][^>]*></script>)',
        rf'\g<1>{VERSION}\2', html, flags=re.I,
    )
    INDEX.write_text(html, encoding="utf-8")

print(f"v{VERSION}: před druhým ROUTER rebootem se interní Extroot fstab obnoví a ověří podle živého UUID")
print(f"v{VERSION}: při chybě Extroot konfigurace se druhý reboot bezpečně neprovede")
print(f"v{VERSION}: po druhém bootu se ověřuje USB zařízení i přesná shoda UUID")
