from pathlib import Path
import os
import re

VERSION = "6.3.8"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
OPS = ROOT / "mesh_operation_manager.py"

if not OPS.exists():
    raise SystemExit(f"v{VERSION}: mesh_operation_manager.py nenalezen")

text = OPS.read_text(encoding="utf-8")

# Runtime verze Operation Manageru.
text = re.sub(
    r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
    f'VERSION = "{VERSION}"',
    text,
    count=1,
)
text = text.replace('START v6.0.0:', f'START v{VERSION}:')
text = text.replace('START v6.3.7:', f'START v{VERSION}:')
text = text.replace('Persistent Operation Manager v6.3.7', f'Persistent Operation Manager v{VERSION}')
text = text.replace('OpenWRT MESH CONTROLLER PRO v6.3.7', f'OpenWRT MESH CONTROLLER PRO v{VERSION}')

# v6.3.6 před druhým rebootem prováděla příliš přísný first-boot gate
# (apk seznam balíčků, ext4, owut atd.) a při jeho selhání druhý reboot zrušila.
# Aktuální OpenWrt ASU dokumentace pro Extroot říká: po sysupgrade jsou potřeba
# dva rebooty; po prvním bootu se externí root nepřipojí a není nutné Extroot
# znovu vytvářet. Proto v6.3.8 nejprve provede standardní druhý reboot bez
# zápisu do fstab. Teprve pokud je po druhém bootu stále interní overlay,
# použije bezpečný fallback: ověřit původní USB UUID, zapsat pouze interní
# fstab.extroot a provést třetí reboot. USB se nikdy neformátuje ani nekopíruje.

extroot_block = r'''    def _repair_extroot_fstab_fallback(self, expected_uuid: str) -> str:
        expected_uuid = str(expected_uuid or "").strip()
        if not re.fullmatch(r"[0-9A-Fa-f-]{16,64}", expected_uuid):
            raise RuntimeError(f"ROUTER .1: neplatné referenční UUID Extrootu ({expected_uuid or 'N/A'}).")

        script = "EXPECTED=" + shlex.quote(expected_uuid) + r'''
set -e
CUR_OVERLAY="$(df -P /overlay 2>/dev/null | awk 'NR==2 {print $1}')"
case "$CUR_OVERLAY" in
  /dev/sd*) echo "ERROR=already_usb:$CUR_OVERLAY"; exit 61 ;;
esac

for C in uci block blkid; do
  command -v "$C" >/dev/null 2>&1 || { echo "ERROR=command_missing:$C"; exit 62; }
done

USB_DEV="$(block info 2>/dev/null | awk -v u="$EXPECTED" 'index($0, "UUID=\"" u "\"") {sub(/:.*/, "", $1); print $1; exit}')"
if [ -z "$USB_DEV" ]; then
  for D in /dev/sd[a-z][0-9]*; do
    [ -b "$D" ] || continue
    U="$(blkid -s UUID -o value "$D" 2>/dev/null || true)"
    [ "$U" = "$EXPECTED" ] && { USB_DEV="$D"; break; }
  done
fi
[ -n "$USB_DEV" ] || { echo "ERROR=usb_uuid_not_found:$EXPECTED"; block info 2>/dev/null || true; exit 63; }
case "$USB_DEV" in
  /dev/sd[a-z][0-9]*) ;;
  *) echo "ERROR=unexpected_usb_device:$USB_DEV"; exit 64 ;;
esac
[ -b "$USB_DEV" ] || { echo "ERROR=usb_not_block_device:$USB_DEV"; exit 65; }

ACTUAL_UUID="$(blkid -s UUID -o value "$USB_DEV" 2>/dev/null || true)"
ACTUAL_TYPE="$(blkid -s TYPE -o value "$USB_DEV" 2>/dev/null || true)"
[ "$ACTUAL_UUID" = "$EXPECTED" ] || { echo "ERROR=uuid_mismatch:$ACTUAL_UUID"; exit 66; }
[ "$ACTUAL_TYPE" = "ext4" ] || { echo "ERROR=filesystem_not_ext4:$ACTUAL_TYPE"; exit 67; }

uci -q delete fstab.extroot || true
uci set fstab.extroot='mount'
uci set fstab.extroot.uuid="$EXPECTED"
uci set fstab.extroot.target='/overlay'
uci set fstab.extroot.fstype='ext4'
uci set fstab.extroot.enabled='1'
uci commit fstab
sync

[ "$(uci -q get fstab.extroot.uuid || true)" = "$EXPECTED" ] || { echo 'ERROR=fstab_uuid_verify'; exit 68; }
[ "$(uci -q get fstab.extroot.target || true)" = "/overlay" ] || { echo 'ERROR=fstab_target_verify'; exit 69; }
[ "$(uci -q get fstab.extroot.fstype || true)" = "ext4" ] || { echo 'ERROR=fstab_type_verify'; exit 70; }
[ "$(uci -q get fstab.extroot.enabled || true)" = "1" ] || { echo 'ERROR=fstab_enabled_verify'; exit 71; }

printf 'OK=1\nINTERNAL_OVERLAY=%s\nUSB_DEV=%s\nUUID=%s\nTYPE=%s\n' \
  "$CUR_OVERLAY" "$USB_DEV" "$ACTUAL_UUID" "$ACTUAL_TYPE"
'''
        out, err, code = self._exec(MAIN_IP, script, timeout=30)
        detail = (out + ("\n" + err if err else "")).strip()
        if code != 0 or "OK=1" not in out:
            diag_out, diag_err, _diag_code = self._exec(
                MAIN_IP,
                "echo '--- overlay ---'; df -P /overlay 2>/dev/null || true; "
                "echo '--- fstab ---'; uci show fstab 2>/dev/null || true; "
                "echo '--- block ---'; block info 2>/dev/null || true; "
                "echo '--- blkid ---'; blkid /dev/sd* 2>/dev/null || true; "
                "echo '--- extroot log ---'; logread 2>/dev/null | grep -iE 'extroot|mount_root|block:|sda|overlay' | tail -n 45 || true",
                timeout=20,
            )
            diag = (diag_out + ("\n" + diag_err if diag_err else "")).strip()
            raise RuntimeError(
                "ROUTER .1: fallback obnova interního fstab.extroot selhala: "
                + (detail or f"rc={code}")
                + (" | " + diag[-3000:] if diag else "")
            )
        return detail

    def _second_router_reboot_if_extroot(self, index: int, before_overlay: Dict[str, Any]) -> Dict[str, Any]:
        source = str(before_overlay.get("overlay") or "")
        expected_uuid = str(before_overlay.get("overlay_uuid") or "").strip()
        if not source.startswith("/dev/sd"):
            raise RuntimeError(
                f"ROUTER .1: před sysupgrade nebyl aktivní USB Extroot ({source or 'N/A'}); automatický Extroot návrat zrušen."
            )
        if not expected_uuid:
            raise RuntimeError("ROUTER .1: před sysupgrade nebylo zjištěno UUID USB Extrootu.")

        first = self._wait_online_stable(MAIN_IP, ONLINE_TIMEOUT)
        first_source = str(first.get("overlay") or "")
        first_uuid = str(first.get("overlay_uuid") or "")
        if first_source.startswith("/dev/sd"):
            if first_uuid.lower() != expected_uuid.lower():
                raise RuntimeError(
                    f"ROUTER .1: Extroot je aktivní už po prvním bootu, ale UUID nesouhlasí ({first_uuid or 'N/A'} != {expected_uuid})."
                )
            self._log(f"ROUTER .1: USB Extroot je aktivní už po prvním bootu ({first_source}); další reboot není nutný.")
            return first

        self._set(stage="router_extroot_second_reboot", current_index=index, current_ip=MAIN_IP,
                  current_name="ROUTER", action_sent=False, progress=94)
        self._log(
            f"ROUTER .1: první boot po sysupgrade je na interním overlay ({first_source or 'N/A'}) – "
            "to je pro Extroot očekávané. Čekám 15 s na dokončení first-boot služeb a provedu standardní druhý reboot bez změny fstab."
        )
        time.sleep(15)

        before_second = self._router_info(MAIN_IP)
        self._send_reboot(MAIN_IP)
        self._set(action_sent=True, action_sent_at=_now_text(), status="waiting", progress=95)
        self._wait_offline(MAIN_IP, OFFLINE_TIMEOUT)
        second = self._wait_online_stable(MAIN_IP, ONLINE_TIMEOUT)
        if before_second.get("boot_id") and second.get("boot_id") == before_second.get("boot_id"):
            raise RuntimeError("ROUTER .1: druhý reboot nepotvrdil změnu boot_id.")

        second_source = str(second.get("overlay") or "")
        second_uuid = str(second.get("overlay_uuid") or "")
        if second_source.startswith("/dev/sd"):
            if second_uuid.lower() != expected_uuid.lower():
                raise RuntimeError(
                    f"ROUTER .1: po druhém bootu je USB overlay aktivní, ale UUID nesouhlasí ({second_uuid or 'N/A'} != {expected_uuid})."
                )
            self._log(f"ROUTER .1: druhý boot OK – USB Extroot {second_source}, UUID {second_uuid}.")
            return second

        # Oficiální druhý reboot Extroot neaktivoval. Teď teprve opravíme interní
        # fstab podle přesného před-upgrade UUID. USB data se nijak nemění.
        self._set(stage="router_extroot_fallback_repair", current_index=index, current_ip=MAIN_IP,
                  current_name="ROUTER", action_sent=False, status="running", progress=96)
        self._log(
            f"ROUTER .1: po standardním druhém bootu je stále interní overlay ({second_source or 'N/A'}). "
            "Spouštím automatický fallback: ověřím USB podle původního UUID a opravím pouze interní fstab.extroot."
        )
        repair = self._repair_extroot_fstab_fallback(expected_uuid)
        self._log("ROUTER .1: fallback fstab.extroot ověřen – " + repair.replace("\n", " | ")[:700])

        before_third = self._router_info(MAIN_IP)
        self._set(stage="router_extroot_fallback_reboot", action_sent=False, progress=97)
        self._send_reboot(MAIN_IP)
        self._set(action_sent=True, action_sent_at=_now_text(), status="waiting")
        self._wait_offline(MAIN_IP, OFFLINE_TIMEOUT)
        third = self._wait_online_stable(MAIN_IP, ONLINE_TIMEOUT)
        if before_third.get("boot_id") and third.get("boot_id") == before_third.get("boot_id"):
            raise RuntimeError("ROUTER .1: fallback reboot nepotvrdil změnu boot_id.")

        third_source = str(third.get("overlay") or "")
        third_uuid = str(third.get("overlay_uuid") or "")
        if not third_source.startswith("/dev/sd"):
            raise RuntimeError(
                f"ROUTER .1: ani po fallback opravě není USB Extroot aktivní ({third_source or 'N/A'})."
            )
        if third_uuid.lower() != expected_uuid.lower():
            raise RuntimeError(
                f"ROUTER .1: fallback aktivoval USB, ale UUID nesouhlasí ({third_uuid or 'N/A'} != {expected_uuid})."
            )
        self._log(f"ROUTER .1: fallback úspěšný – USB Extroot {third_source}, UUID {third_uuid}.")
        return third

'''

pattern = re.compile(
    r"    def _second_router_reboot_if_extroot\(self, index: int, before_overlay: Dict\[str, Any\]\) -> Dict\[str, Any\]:.*?(?=\n    def _owut_one\()",
    re.S,
)
text, count = pattern.subn(lambda _m: extroot_block, text, count=1)
if count != 1:
    raise SystemExit(f"v{VERSION}: nepodařilo se nahradit persistent Extroot reboot flow")

OPS.write_text(text, encoding="utf-8")

print(f"v{VERSION}: Extroot po sysupgrade používá standardní druhý reboot bez first-boot package gate")
print(f"v{VERSION}: pokud druhý boot zůstane interní, fallback opraví pouze interní fstab.extroot podle živého před-upgrade UUID a provede třetí reboot")
print(f"v{VERSION}: žádný format/wipe/repartition/copy USB overlay")
