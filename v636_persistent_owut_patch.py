from pathlib import Path
import os
import re

VERSION = "6.3.6"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
OPS = ROOT / "mesh_operation_manager.py"

if not OPS.exists():
    raise SystemExit(f"v{VERSION}: mesh_operation_manager.py nenalezen")

text = OPS.read_text(encoding="utf-8")

# Persistent/plánovaný manager používá vlastní OWUT implementaci. Musí mít stejné
# bezpečnostní vlastnosti jako ruční OWUT cesta: bez externího nohup, ověřený PID,
# heartbeat a bezpečný Extroot first-boot gate před druhým restartem.
if "import shlex\n" not in text:
    if "import re\n" not in text:
        raise SystemExit(f"v{VERSION}: nenalezen import re")
    text = text.replace("import re\n", "import re\nimport shlex\n", 1)

launcher_and_watch = r"""    def _start_owut_detached(self, ip: str) -> None:
        add = ""
        if ip == MAIN_IP:
            add = " --add block-mount,kmod-fs-ext4,kmod-usb-storage,kmod-usb-storage-uas"
        owut_cmd = f"owut upgrade --verbose{add}"
        inner = (
            "trap '' HUP; "
            f"{owut_cmd}; "
            "rc=$?; printf '%s\\n' \"$rc\" > /tmp/v500_owut.rc; exit \"$rc\""
        )
        command = (
            "rm -f /tmp/v500_owut.rc /tmp/v500_owut.log /tmp/v500_owut.pid; "
            ": > /tmp/v500_owut.log; "
            f"sh -c {shlex.quote(inner)} >> /tmp/v500_owut.log 2>&1 </dev/null & "
            "pid=$!; printf '%s\\n' \"$pid\" > /tmp/v500_owut.pid; "
            "sleep 2; "
            "if kill -0 \"$pid\" 2>/dev/null; then printf 'STARTED PID=%s\\n' \"$pid\"; exit 0; fi; "
            "if [ -s /tmp/v500_owut.rc ]; then "
            "  rc=$(cat /tmp/v500_owut.rc 2>/dev/null || echo 255); "
            "  printf 'EXIT=%s\\n' \"$rc\"; tail -n 20 /tmp/v500_owut.log 2>/dev/null || true; "
            "  [ \"$rc\" = 0 ] && exit 0; exit 23; "
            "fi; "
            "printf 'FAILED PID=%s\\n' \"$pid\"; tail -n 20 /tmp/v500_owut.log 2>/dev/null || true; exit 24"
        )
        out, err, code = self._exec(ip, command, timeout=20)
        detail = (out + ("\n" + err if err else "")).strip()
        if code != 0 or ("STARTED PID=" not in out and "EXIT=0" not in out):
            raise RuntimeError(f"OWUT upgrade se na {ip} nepodařilo spustit: {detail or f'rc={code}'}")
        self._log(f"OWUT {ip}: proces potvrzen – {detail.splitlines()[0] if detail else 'STARTED'}")

    def _wait_owut_reboot(self, ip: str, name: str, before_boot: str) -> Dict[str, Any]:
        started = time.monotonic()
        deadline = started + OWUT_TIMEOUT
        last_heartbeat = 0.0
        last_log = ""
        dead_without_result = 0

        while time.monotonic() < deadline:
            self._check_cancel()
            if not self._is_online(ip):
                self._log(f"{name} ({ip}): router se restartuje po OWUT, čekám na návrat.")
                return self._wait_online_stable(ip, ONLINE_TIMEOUT)

            try:
                info = self._router_info(ip)
                if before_boot and info.get("boot_id") != before_boot:
                    self._log(f"{name} ({ip}): po OWUT již běží s novým boot_id.")
                    return self._wait_online_stable(ip, ONLINE_TIMEOUT)

                out, _err, _code = self._exec(
                    ip,
                    "printf 'RC='; cat /tmp/v500_owut.rc 2>/dev/null || true; printf '\\n'; "
                    "pid=$(cat /tmp/v500_owut.pid 2>/dev/null || true); printf 'PID=%s\\n' \"$pid\"; "
                    "if [ -n \"$pid\" ] && kill -0 \"$pid\" 2>/dev/null; then echo 'RUNNING=1'; else echo 'RUNNING=0'; fi; "
                    "echo '__LOG__'; tail -n 25 /tmp/v500_owut.log 2>/dev/null || true",
                    timeout=15,
                )
                m = re.search(r"^RC=(\d+)\s*$", out, re.M)
                log_part = out.split("__LOG__", 1)[1].strip() if "__LOG__" in out else ""
                if log_part:
                    last_log = log_part

                if m:
                    rc = int(m.group(1))
                    if rc != 0:
                        raise RuntimeError(f"OWUT {name} ({ip}) skončil rc={rc}: {(last_log or out)[-1800:]}")
                    time.sleep(10)
                    try:
                        again = self._router_info(ip)
                        if before_boot and again.get("boot_id") == before_boot:
                            raise RuntimeError(
                                f"OWUT {name} ({ip}) skončil rc=0 bez restartu: {(last_log or out)[-1800:]}"
                            )
                        return self._wait_online_stable(ip, ONLINE_TIMEOUT)
                    except RuntimeError:
                        raise
                    except Exception:
                        return self._wait_online_stable(ip, ONLINE_TIMEOUT)

                running = bool(re.search(r"^RUNNING=1\s*$", out, re.M))
                if running:
                    dead_without_result = 0
                elif not last_log:
                    dead_without_result += 1
                    if dead_without_result >= 2:
                        raise RuntimeError(
                            f"OWUT {name} ({ip}) neběží a nevznikl log ani návratový kód; launcher selhal."
                        )
                else:
                    dead_without_result = 0

                now = time.monotonic()
                if now - last_heartbeat >= 30:
                    last_heartbeat = now
                    elapsed = max(0, int(now - started))
                    mm, ss = divmod(elapsed, 60)
                    total_mm, total_ss = divmod(OWUT_TIMEOUT, 60)
                    tail = ""
                    if last_log:
                        for line in reversed(last_log.splitlines()):
                            clean = " ".join(line.split())
                            if clean:
                                tail = clean[:180]
                                break
                    msg = f"{name} ({ip}): OWUT běží {mm:02d}:{ss:02d} / {total_mm:02d}:{total_ss:02d}"
                    if tail:
                        msg += f" · {tail}"
                    self._log(msg)
            except RuntimeError:
                raise
            except Exception:
                # Krátký SSH výpadek může být začátek sysupgrade rebootu.
                time.sleep(5)
                if not self._is_online(ip):
                    self._log(f"{name} ({ip}): router se restartuje po OWUT, čekám na návrat.")
                    return self._wait_online_stable(ip, ONLINE_TIMEOUT)

            time.sleep(10)

        detail = f"OWUT {name} ({ip}) nevyvolal restart do {OWUT_TIMEOUT} s."
        if last_log:
            detail += " Poslední log: " + " | ".join(last_log.splitlines()[-6:])[-1000:]
        raise TimeoutError(detail)

"""

launcher_pattern = re.compile(
    r"    def _start_owut_detached\(self, ip: str\) -> None:.*?(?=\n    def _second_router_reboot_if_extroot\()",
    re.S,
)
text, count = launcher_pattern.subn(lambda _m: launcher_and_watch, text, count=1)
if count != 1:
    raise SystemExit(f"v{VERSION}: nepodařilo se nahradit persistent OWUT launcher/watchdog")

extroot_block = r"""    def _validate_and_restore_extroot_first_boot(self, expected_uuid: str) -> str:
        expected_uuid = str(expected_uuid or "").strip()
        if not re.fullmatch(r"[0-9A-Fa-f-]{16,64}", expected_uuid):
            raise RuntimeError(f"ROUTER .1: neplatné referenční UUID Extrootu ({expected_uuid or 'N/A'}).")

        script = "EXPECTED=" + shlex.quote(expected_uuid) + r'''
set -e
CUR_OVERLAY="$(df -P /overlay 2>/dev/null | awk 'NR==2 {print $1}')"
case "$CUR_OVERLAY" in
  /dev/sd*) echo "ERROR=first_boot_already_usb:$CUR_OVERLAY"; exit 41 ;;
esac

. /etc/openwrt_release 2>/dev/null || true
[ -n "${DISTRIB_RELEASE:-}" ] || { echo 'ERROR=release_missing'; exit 42; }
[ -n "${DISTRIB_REVISION:-}" ] || { echo 'ERROR=revision_missing'; exit 43; }
for C in uci block blkid owut; do
  command -v "$C" >/dev/null 2>&1 || { echo "ERROR=command_missing:$C"; exit 44; }
done

grep -qw ext4 /proc/filesystems 2>/dev/null || { echo 'ERROR=ext4_not_available'; exit 45; }
PKG_LIST="$(apk list --installed 2>/dev/null || opkg list-installed 2>/dev/null || true)"
MISSING=""
for P in block-mount kmod-fs-ext4 kmod-usb-storage kmod-usb-storage-uas; do
  printf '%s\n' "$PKG_LIST" | grep -Eq "^${P}([ -]|$)" || MISSING="$MISSING $P"
done
[ -z "$MISSING" ] || { echo "ERROR=packages_missing:$MISSING"; exit 46; }

USB_DEV="$(block info 2>/dev/null | awk -v u="$EXPECTED" 'index($0, "UUID=\"" u "\"") {sub(/:.*/, "", $1); print $1; exit}')"
[ -n "$USB_DEV" ] || { echo "ERROR=usb_uuid_not_found:$EXPECTED"; block info 2>/dev/null || true; exit 47; }
case "$USB_DEV" in
  /dev/sd[a-z][0-9]*) ;;
  *) echo "ERROR=unexpected_usb_device:$USB_DEV"; exit 48 ;;
esac
[ -b "$USB_DEV" ] || { echo "ERROR=usb_not_block_device:$USB_DEV"; exit 49; }
ACTUAL_UUID="$(blkid -s UUID -o value "$USB_DEV" 2>/dev/null || true)"
ACTUAL_TYPE="$(blkid -s TYPE -o value "$USB_DEV" 2>/dev/null || true)"
[ "$ACTUAL_UUID" = "$EXPECTED" ] || { echo "ERROR=uuid_mismatch:$ACTUAL_UUID"; exit 50; }
[ "$ACTUAL_TYPE" = "ext4" ] || { echo "ERROR=filesystem_not_ext4:$ACTUAL_TYPE"; exit 51; }

uci -q delete fstab.extroot || true
uci set fstab.extroot='mount'
uci set fstab.extroot.uuid="$EXPECTED"
uci set fstab.extroot.target='/overlay'
uci set fstab.extroot.fstype='ext4'
uci set fstab.extroot.enabled='1'
uci commit fstab
sync

[ "$(uci -q get fstab.extroot.uuid || true)" = "$EXPECTED" ] || { echo 'ERROR=fstab_uuid_verify'; exit 52; }
[ "$(uci -q get fstab.extroot.target || true)" = "/overlay" ] || { echo 'ERROR=fstab_target_verify'; exit 53; }
[ "$(uci -q get fstab.extroot.fstype || true)" = "ext4" ] || { echo 'ERROR=fstab_type_verify'; exit 54; }
[ "$(uci -q get fstab.extroot.enabled || true)" = "1" ] || { echo 'ERROR=fstab_enabled_verify'; exit 55; }

printf 'OK=1\nOPENWRT=%s\nREVISION=%s\nINTERNAL_OVERLAY=%s\nUSB_DEV=%s\nUUID=%s\nTYPE=%s\n' \
  "$DISTRIB_RELEASE" "$DISTRIB_REVISION" "$CUR_OVERLAY" "$USB_DEV" "$ACTUAL_UUID" "$ACTUAL_TYPE"
'''
        out, err, code = self._exec(MAIN_IP, script, timeout=30)
        detail = (out + ("\n" + err if err else "")).strip()
        if code != 0 or "OK=1" not in out:
            diag_out, diag_err, _diag_code = self._exec(
                MAIN_IP,
                "echo '--- overlay ---'; df -P /overlay 2>/dev/null || true; "
                "echo '--- fstab ---'; uci show fstab 2>/dev/null || true; "
                "echo '--- block ---'; block info 2>/dev/null || true; "
                "echo '--- extroot log ---'; logread 2>/dev/null | grep -iE 'extroot|mount_root|block:|sda|overlay' | tail -n 35 || true",
                timeout=20,
            )
            diag = (diag_out + ("\n" + diag_err if diag_err else "")).strip()
            raise RuntimeError(
                "ROUTER .1: first-boot Extroot kontrola/obnova selhala: "
                + (detail or f"rc={code}")
                + (" | " + diag[-2500:] if diag else "")
            )
        return detail

    def _second_router_reboot_if_extroot(self, index: int, before_overlay: Dict[str, Any]) -> Dict[str, Any]:
        source = str(before_overlay.get("overlay") or "")
        expected_uuid = str(before_overlay.get("overlay_uuid") or "").strip()
        if not source.startswith("/dev/sd"):
            raise RuntimeError(
                f"ROUTER .1: před sysupgrade nebyl aktivní USB Extroot ({source or 'N/A'}); druhý reboot zrušen."
            )
        if not expected_uuid:
            raise RuntimeError("ROUTER .1: před sysupgrade nebylo zjištěno UUID USB Extrootu; druhý reboot zrušen.")

        first = self._wait_online_stable(MAIN_IP, ONLINE_TIMEOUT)
        first_source = str(first.get("overlay") or "")
        first_uuid = str(first.get("overlay_uuid") or "")
        if first_source.startswith("/dev/sd"):
            if first_uuid.lower() != expected_uuid.lower():
                raise RuntimeError(
                    f"ROUTER .1: Extroot je aktivní už po prvním bootu, ale UUID nesouhlasí ({first_uuid or 'N/A'} != {expected_uuid})."
                )
            self._log(f"ROUTER .1: USB Extroot je aktivní už po prvním bootu ({first_source}); druhý reboot není nutný.")
            return first

        self._set(stage="router_extroot_first_boot_check", current_index=index, current_ip=MAIN_IP,
                  current_name="ROUTER", action_sent=False, progress=94)
        self._log(
            f"ROUTER .1: první boot je na interním overlay ({first_source or 'N/A'}). "
            "Ověřuji nový OpenWrt, Extroot balíčky, ext4 a původní USB UUID."
        )
        detail = self._validate_and_restore_extroot_first_boot(expected_uuid)
        self._log("ROUTER .1: first-boot kontrola OK, interní fstab.extroot je ověřen. Provádím druhý restart.")

        self._set(stage="router_second_reboot", current_index=index, current_ip=MAIN_IP,
                  current_name="ROUTER", action_sent=False, progress=96)
        before = self._router_info(MAIN_IP)
        self._send_reboot(MAIN_IP)
        self._set(action_sent=True, action_sent_at=_now_text(), status="waiting")
        self._wait_offline(MAIN_IP, OFFLINE_TIMEOUT)
        after = self._wait_online_stable(MAIN_IP, ONLINE_TIMEOUT)
        if before.get("boot_id") and after.get("boot_id") == before.get("boot_id"):
            raise RuntimeError("ROUTER .1: druhý restart nepotvrdil změnu boot_id.")
        current_source = str(after.get("overlay") or "")
        if not current_source.startswith("/dev/sd"):
            raise RuntimeError(f"ROUTER .1: USB overlay po druhém restartu není aktivní ({current_source or 'N/A'}).")
        new_uuid = str(after.get("overlay_uuid") or "")
        if not new_uuid or new_uuid.lower() != expected_uuid.lower():
            raise RuntimeError(f"ROUTER .1: UUID overlay po druhém bootu nesouhlasí ({new_uuid or 'N/A'} != {expected_uuid}).")
        self._log(f"ROUTER .1: USB overlay aktivní ({current_source}), UUID {new_uuid} ověřeno.")
        return after

"""

extroot_pattern = re.compile(
    r"    def _second_router_reboot_if_extroot\(self, index: int, before_overlay: Dict\[str, Any\]\) -> Dict\[str, Any\]:.*?(?=\n    def _owut_one\()",
    re.S,
)
text, count = extroot_pattern.subn(lambda _m: extroot_block, text, count=1)
if count != 1:
    raise SystemExit(f"v{VERSION}: nepodařilo se nahradit persistent Extroot druhý reboot")

# Bez dostupného sysupgrade se NESMÍ vytvářet záloha, zapisovat fstab ani rebootovat.
old_no_update_finish = '                    self._finish_success("OWUT kontrola dokončena – nový sysupgrade není dostupný.")\n                    return\n'
new_no_update_finish = (
    '                    self._log("AUTO/RUČNÍ OWUT: bez změn – žádný sysupgrade, žádný reboot, USB Extroot beze změny.")\n'
    '                    self._finish_success("OWUT kontrola dokončena – nový sysupgrade není dostupný; USB Extroot beze změny.")\n'
    '                    return\n'
)
if new_no_update_finish not in text:
    if old_no_update_finish not in text:
        raise SystemExit(f"v{VERSION}: nenalezen persistent no-update finish")
    text = text.replace(old_no_update_finish, new_no_update_finish, 1)

# Je-li update dostupný i pro ROUTER, ověřit Extroot ještě před zálohou a před
# aktualizací kteréhokoli uzlu. Tím se při chybné .1 konfiguraci nic neflashuje.
old_backup_start = '                backup_id, backup_dir = self._backup_all()\n                self._set(backup_id=backup_id, backup_dir=backup_dir)\n'
new_backup_start = '''                if MAIN_IP in available:
                    main_info = self._wait_online_stable(MAIN_IP, 180)
                    main_overlay = str(main_info.get("overlay") or "")
                    main_uuid = str(main_info.get("overlay_uuid") or "").strip()
                    if not main_overlay.startswith("/dev/sd") or not main_uuid:
                        raise RuntimeError(
                            f"ROUTER .1: před OWUT není zdravý USB Extroot "
                            f"(overlay={main_overlay or 'N/A'}, UUID={main_uuid or 'N/A'}). Nic se nebude flashovat."
                        )
                    self._set(pre_overlay={"overlay": main_overlay, "overlay_uuid": main_uuid})
                    self._log(f"ROUTER .1: preflight USB Extroot OK – {main_overlay}, UUID {main_uuid}.")
                backup_id, backup_dir = self._backup_all()
                self._set(backup_id=backup_id, backup_dir=backup_dir)
'''
if new_backup_start not in text:
    if old_backup_start not in text:
        raise SystemExit(f"v{VERSION}: nenalezen persistent backup start")
    text = text.replace(old_backup_start, new_backup_start, 1)

# Těsně před MAIN sysupgrade znovu ověřit, že se Extroot mezitím nezměnil.
old_main_store = '''            if ip == MAIN_IP:
                self._set(pre_overlay={
                    "overlay": info.get("overlay", ""),
                    "overlay_uuid": info.get("overlay_uuid", ""),
                })
'''
new_main_store = '''            if ip == MAIN_IP:
                current_overlay = str(info.get("overlay") or "")
                current_uuid = str(info.get("overlay_uuid") or "").strip()
                expected = self.snapshot().get("pre_overlay") or {}
                expected_uuid = str(expected.get("overlay_uuid") or "").strip()
                if not current_overlay.startswith("/dev/sd") or not current_uuid:
                    raise RuntimeError(
                        f"ROUTER .1: USB Extroot před samotným sysupgrade není aktivní "
                        f"(overlay={current_overlay or 'N/A'}, UUID={current_uuid or 'N/A'})."
                    )
                if expected_uuid and current_uuid.lower() != expected_uuid.lower():
                    raise RuntimeError(
                        f"ROUTER .1: UUID Extrootu se od preflightu změnilo ({expected_uuid} -> {current_uuid})."
                    )
                self._set(pre_overlay={"overlay": current_overlay, "overlay_uuid": current_uuid})
'''
if new_main_store not in text:
    if old_main_store not in text:
        raise SystemExit(f"v{VERSION}: nenalezen persistent MAIN pre_overlay store")
    text = text.replace(old_main_store, new_main_store, 1)

# Report/version text sjednotit s release, aby plánovaný report neukazoval staré v6.0.x.
text = text.replace("OpenWRT MESH CONTROLLER PRO v6.0.2", f"OpenWRT MESH CONTROLLER PRO v{VERSION}")
text = text.replace("Persistent Operation Manager v6.0.0", f"Persistent Operation Manager v{VERSION}")
text = text.replace('self._log(f"START v6.0.0: {kind}', f'self._log(f"START v{VERSION}: {{kind}}')

OPS.write_text(text, encoding="utf-8")

print(f"v{VERSION}: persistent/plánovaný OWUT launcher bez nohup + PID/RC/log heartbeat")
print(f"v{VERSION}: MAIN OWUT používá --add Extroot balíčků i v scheduler-v500 cestě")
print(f"v{VERSION}: plánovaný MAIN sysupgrade má USB UUID preflight + first-boot package/ext4/USB/fstab gate")
print(f"v{VERSION}: no-update plánovaný běh výslovně nedělá sysupgrade/reboot/fstab změnu")
