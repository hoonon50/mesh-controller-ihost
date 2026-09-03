from __future__ import annotations

import copy
import html
import json
import os
import re
import shlex
import smtplib
import ssl
import threading
import time
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from ihost_temperature_v636 import read_ihost_temperature
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import paramiko
from flask import jsonify, request

VERSION = "7.0.2"
MAIN_IP = "192.168.30.1"
IHOT_MESH_IP = "192.168.30.2"
ROUTERS: List[Tuple[str, str]] = [
    ("192.168.30.1", "ROUTER"),
    ("192.168.30.2", "MESH1"),
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
]
# iHost je kabelem na MESH1, proto je MESH1 poslední satelit.
ROLLING_ORDER: List[Tuple[str, str]] = [
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
    ("192.168.30.2", "MESH1"),
    ("192.168.30.1", "ROUTER"),
]
REBOOT_ORDER = [
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
    ("192.168.30.1", "ROUTER"),
    ("192.168.30.2", "MESH1"),
]

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
STATE_FILE = DATA_DIR / "mesh_operation.json"
SCHEDULER_FILE = DATA_DIR / "mesh_scheduler_v500.json"
SETTINGS_FILE = DATA_DIR / "owut_settings.json"
PENDING_MAIL_FILE = DATA_DIR / "owut_pending_mail.json"
BACKUP_ROOT = DATA_DIR / "backups"

SSH_USER = os.environ.get("MESH_SSH_USER", "root")
SSH_PASS = os.environ.get("MESH_SSH_PASS", "root")
SSH_TIMEOUT = int(os.environ.get("MESH_SSH_TIMEOUT", "6"))
OFFLINE_TIMEOUT = int(os.environ.get("MESH_OFFLINE_TIMEOUT", "120"))
ONLINE_TIMEOUT = int(os.environ.get("MESH_ONLINE_TIMEOUT", "600"))
OWUT_TIMEOUT = int(os.environ.get("MESH_OWUT_TIMEOUT", "2400"))
STABLE_COUNT = int(os.environ.get("MESH_STABLE_COUNT", "3"))
STABLE_INTERVAL = int(os.environ.get("MESH_STABLE_INTERVAL", "5"))
POLL_INTERVAL = int(os.environ.get("MESH_OPERATION_POLL", "5"))

try:
    LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "Europe/Prague"))
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")


def _now_dt() -> datetime:
    return datetime.now(LOCAL_TZ)


def _now_text() -> str:
    return _now_dt().strftime("%Y-%m-%d %H:%M:%S")


def _atomic_json_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else copy.deepcopy(default)
    except Exception:
        return copy.deepcopy(default)


def _default_node_states() -> List[Dict[str, Any]]:
    return [
        {
            "ip": ip,
            "name": name,
            "status": "pending",
            "detail": "",
            "before_boot_id": "",
            "after_boot_id": "",
            "before_revision": "",
            "after_revision": "",
            "temperature_c": None,
        }
        for ip, name in ROLLING_ORDER
    ]


def _default_state() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "operation_id": "",
        "kind": "",
        "automatic": False,
        "status": "idle",  # idle/running/waiting/paused/error/done/cancelled
        "stage": "idle",
        "message": "Připraveno",
        "progress": 0,
        "created_at": "",
        "updated_at": "",
        "finished_at": "",
        "current_index": 0,
        "current_ip": "",
        "current_name": "",
        "action_sent": False,
        "action_sent_at": "",
        "cancel_requested": False,
        "pause_reason": "",
        "backup_id": "",
        "backup_dir": "",
        "owut_checks": {},
        "controller_backup": {},
        "pre_overlay": {},
        "nodes": _default_node_states(),
        "log": [],
        "report": {"sent": False, "detail": ""},
    }


class PersistentMeshOperationManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.worker_lock = threading.Lock()
        self.worker: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.state = _read_json(STATE_FILE, _default_state())
        if str(self.state.get("version")) != VERSION:
            # Zachováme rozpracovanou operaci, pouze aktualizujeme formátovou verzi.
            self.state["version"] = VERSION
        self._save_locked()

    # ------------------------------------------------------------ state/log --
    def _save_locked(self) -> None:
        self.state["updated_at"] = _now_text()
        _atomic_json_write(STATE_FILE, self.state)

    def _save(self) -> None:
        with self.lock:
            self._save_locked()

    def _log(self, message: str) -> None:
        line = f"[{_now_dt().strftime('%H:%M:%S')}] {message}"
        with self.lock:
            log = self.state.setdefault("log", [])
            log.append(line)
            if len(log) > 250:
                del log[:-250]
            self.state["message"] = message
            self._save_locked()

    def _set(self, **values: Any) -> None:
        with self.lock:
            self.state.update(values)
            self._save_locked()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.state)

    def _node(self, ip: str) -> Dict[str, Any]:
        with self.lock:
            for row in self.state.get("nodes", []):
                if row.get("ip") == ip:
                    return row
            row = {"ip": ip, "name": ip, "status": "pending", "detail": ""}
            self.state.setdefault("nodes", []).append(row)
            return row

    def _node_update(self, ip: str, **values: Any) -> None:
        with self.lock:
            row = self._node(ip)
            row.update(values)
            self._save_locked()

    def _progress_for(self, index: int, phase: float = 0.0) -> int:
        total = max(1, len(ROLLING_ORDER))
        return min(99, int(((index + phase) / total) * 100))

    def _check_cancel(self) -> None:
        if self.snapshot().get("cancel_requested"):
            raise InterruptedError("Operace byla zrušena uživatelem.")

    # --------------------------------------------------------------- SSH --
    def _connect(self, ip: str, timeout: int = SSH_TIMEOUT) -> paramiko.SSHClient:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: Dict[str, Any] = {
            "hostname": ip,
            "username": SSH_USER,
            "timeout": timeout,
            "banner_timeout": timeout,
            "auth_timeout": timeout,
        }
        if SSH_PASS:
            kwargs.update({"password": SSH_PASS, "look_for_keys": False, "allow_agent": False})
        ssh.connect(**kwargs)
        return ssh

    def _exec(self, ip: str, command: str, timeout: int = 30) -> Tuple[str, str, int]:
        ssh = self._connect(ip)
        try:
            _stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()
            return out, err, code
        finally:
            ssh.close()

    def _is_online(self, ip: str) -> bool:
        try:
            out, _err, code = self._exec(ip, "printf READY", timeout=8)
            return code == 0 and "READY" in out
        except Exception:
            return False

    def _router_info(self, ip: str) -> Dict[str, Any]:
        command = r'''set -u
HOST="$(uci -q get system.@system[0].hostname || hostname 2>/dev/null || true)"
BOOT="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
REV="$(ubus call system board 2>/dev/null | jsonfilter -e '@.release.revision' 2>/dev/null || true)"
VER="$(ubus call system board 2>/dev/null | jsonfilter -e '@.release.version' 2>/dev/null || true)"
UP="$(cut -d' ' -f1 /proc/uptime 2>/dev/null || true)"
OVERLAY="$(df -P /overlay 2>/dev/null | awk 'NR==2 {print $1}')"
OVUUID=""
case "$OVERLAY" in /dev/*) OVUUID="$(blkid -s UUID -o value "$OVERLAY" 2>/dev/null || true)";; esac
TEMP=""
for f in /sys/class/thermal/thermal_zone*/temp /sys/class/hwmon/hwmon*/temp*_input; do
  [ -r "$f" ] || continue
  v="$(cat "$f" 2>/dev/null || true)"
  case "$v" in ''|*[!0-9-]*) continue;; esac
  if [ "$v" -gt 1000 ] 2>/dev/null; then v=$((v / 1000)); fi
  if [ "$v" -gt 0 ] 2>/dev/null && [ "$v" -lt 150 ] 2>/dev/null; then TEMP="$v"; break; fi
done
printf 'HOSTNAME=%s\nBOOT_ID=%s\nREVISION=%s\nVERSION=%s\nUPTIME=%s\nOVERLAY=%s\nOVERLAY_UUID=%s\nTEMP=%s\n' "$HOST" "$BOOT" "$REV" "$VER" "$UP" "$OVERLAY" "$OVUUID" "$TEMP"
'''
        out, err, code = self._exec(ip, command, timeout=15)
        if code != 0:
            raise RuntimeError(err.strip() or f"Router info rc={code}")
        result: Dict[str, Any] = {}
        for line in out.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                result[key.lower()] = value.strip()
        temp = result.get("temp", "")
        try:
            result["temperature_c"] = int(temp) if temp != "" else None
        except ValueError:
            result["temperature_c"] = None
        return result

    def _wait_offline(self, ip: str, timeout: int = OFFLINE_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_cancel()
            if not self._is_online(ip):
                return True
            time.sleep(POLL_INTERVAL)
        return False

    def _wait_online_stable(self, ip: str, timeout: int = ONLINE_TIMEOUT) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        consecutive = 0
        last_info: Dict[str, Any] = {}
        while time.monotonic() < deadline:
            self._check_cancel()
            try:
                info = self._router_info(ip)
                consecutive += 1
                last_info = info
                if consecutive >= STABLE_COUNT:
                    return last_info
            except Exception:
                consecutive = 0
            time.sleep(STABLE_INTERVAL)
        raise TimeoutError(f"{ip} se nevrátil stabilně přes SSH do {timeout} s.")

    # --------------------------------------------------------------- reboot --
    def _send_reboot(self, ip: str) -> None:
        # Příkaz se oddělí od SSH relace; odpojení je očekávané.
        try:
            ssh = self._connect(ip)
            try:
                ssh.exec_command("(sleep 2; reboot) >/dev/null 2>&1 &")
                time.sleep(0.4)
            finally:
                ssh.close()
        except Exception as exc:
            raise RuntimeError(f"Nepodařilo se odeslat reboot na {ip}: {exc}") from exc

    def _reboot_one(self, index: int, ip: str, name: str, resume: bool = False) -> None:
        self._check_cancel()
        state = self.snapshot()
        stage = str(state.get("stage") or "") if state.get("current_ip") == ip else ""
        row = self._node(ip)
        before_boot = str(row.get("before_boot_id") or "")

        if not before_boot:
            self._set(stage="precheck", current_index=index, current_ip=ip, current_name=name,
                      progress=self._progress_for(index, 0.05), action_sent=False, action_sent_at="")
            self._log(f"{name} ({ip}): ověřuji SSH před restartem.")
            info = self._wait_online_stable(ip, 180)
            before_boot = str(info.get("boot_id") or "")
            self._node_update(ip, status="precheck_ok", before_boot_id=before_boot,
                              before_revision=info.get("revision", ""), temperature_c=info.get("temperature_c"))

        # Pokud po restartu Dockeru nevíme, zda byl příkaz skutečně odeslán,
        # porovnáme boot_id. Změněný boot_id znamená, že reboot už proběhl.
        if stage in {"action_sent", "waiting_offline", "waiting_online", "postcheck"} or state.get("action_sent"):
            self._log(f"{name} ({ip}): obnovuji rozpracovaný restart, příkaz znovu neposílám.")
        elif stage == "sending" and resume:
            try:
                current = self._router_info(ip)
                if before_boot and current.get("boot_id") != before_boot:
                    self._log(f"{name} ({ip}): boot_id se změnil, restart již proběhl.")
                else:
                    self._log(f"{name} ({ip}): restart nebyl potvrzen, odesílám jej znovu.")
                    self._send_reboot(ip)
            except Exception:
                self._log(f"{name} ({ip}): uzel je nedostupný, předpokládám probíhající restart.")
        else:
            self._set(stage="sending", current_index=index, current_ip=ip, current_name=name,
                      progress=self._progress_for(index, 0.20), action_sent=False)
            self._node_update(ip, status="reboot_sending", detail="Odesílám reboot")
            self._log(f"{name} ({ip}): odesílám reboot.")
            self._send_reboot(ip)
            self._set(stage="action_sent", action_sent=True, action_sent_at=_now_text(),
                      progress=self._progress_for(index, 0.35))

        self._set(stage="waiting_offline", status="waiting", progress=self._progress_for(index, 0.45))
        self._node_update(ip, status="waiting_offline", detail="Čekám na odpojení")
        went_offline = self._wait_offline(ip, OFFLINE_TIMEOUT)
        if not went_offline:
            # Pokud jsme krátké offline okno neviděli, rozhoduje boot_id.
            try:
                current = self._router_info(ip)
                if before_boot and current.get("boot_id") == before_boot:
                    raise TimeoutError(f"{name} ({ip}) se po reboot příkazu neodpojil a boot_id se nezměnil.")
            except TimeoutError:
                raise
            except Exception:
                pass

        self._set(stage="waiting_online", status="waiting", progress=self._progress_for(index, 0.60))
        self._node_update(ip, status="waiting_online", detail="Čekám na návrat SSH")
        self._log(f"{name} ({ip}): čekám na stabilní návrat SSH.")
        after = self._wait_online_stable(ip)

        if before_boot and after.get("boot_id") == before_boot:
            raise RuntimeError(f"{name} ({ip}): po restartu se nezměnil boot_id.")

        self._set(stage="postcheck", status="running", progress=self._progress_for(index, 0.80))
        self._node_update(ip, status="online", detail="Restart dokončen",
                          after_boot_id=after.get("boot_id", ""), after_revision=after.get("revision", ""),
                          temperature_c=after.get("temperature_c"))

        if ip == IHOT_MESH_IP:
            self._log("MESH1 .2 je zpět. Ověřuji znovu MESH1 .2 a cestu k ROUTERu .1.")
            self._wait_online_stable(IHOT_MESH_IP, ONLINE_TIMEOUT)
            self._wait_online_stable(MAIN_IP, ONLINE_TIMEOUT)
            self._log("MESH1 .2 i ROUTER .1 jsou dostupné. Lze bezpečně pokračovat.")

        self._set(stage="node_done", action_sent=False, action_sent_at="",
                  progress=self._progress_for(index, 1.0))
        self._node_update(ip, status="done", detail="HOTOVO")

    # --------------------------------------------------------------- backup --
    def _backup_all(self) -> Tuple[str, str]:
        backup_id = _now_dt().strftime("%Y-%m-%d_%H-%M-%S")
        target = BACKUP_ROOT / f"BACKUP_{backup_id}"
        target.mkdir(parents=True, exist_ok=True)
        self._set(stage="backup", backup_id=backup_id, backup_dir=str(target), message="Vytvářím zálohu 5 routerů")
        manifest: Dict[str, Any] = {"created": _now_text(), "nodes": {}}
        for ip, name in ROUTERS:
            self._check_cancel()
            self._log(f"ZÁLOHA {name} ({ip}): vytvářím standardní sysupgrade archiv.")
            remote = f"/tmp/v500-{name.lower()}.tar.gz"
            out, err, code = self._exec(
                ip,
                f"rm -f {remote}; (sysupgrade --create-backup {remote} 2>/dev/null || sysupgrade -b {remote}); test -s {remote}",
                timeout=90,
            )
            if code != 0:
                raise RuntimeError(f"Záloha {name} ({ip}) selhala: {(err or out).strip()}")
            local = target / f"{name}.tar.gz"
            ssh = self._connect(ip)
            try:
                sftp = ssh.open_sftp()
                try:
                    sftp.get(remote, str(local))
                finally:
                    sftp.close()
            finally:
                ssh.close()
            if not local.exists() or local.stat().st_size < 100:
                raise RuntimeError(f"Stažená záloha {name} ({ip}) je neplatná.")
            manifest["nodes"][ip] = {"name": name, "file": local.name, "bytes": local.stat().st_size}
            try:
                self._exec(ip, f"rm -f {remote}", timeout=10)
            except Exception:
                pass
        _atomic_json_write(target / "backup_info.json", manifest)
        self._log(f"Záloha všech 5 routerů dokončena: {backup_id}")
        return backup_id, str(target)

    # ---------------------------------------------------------------- OWUT --
    @staticmethod
    def _parse_owut_versions(text: str) -> Tuple[str, str]:
        vf = ""
        vt = ""
        for line in text.splitlines():
            m = re.match(r"\s*Version-from\s+(.+?)\s*$", line)
            if m:
                vf = m.group(1).strip()
            m = re.match(r"\s*Version-to\s+(.+?)\s*$", line)
            if m:
                vt = m.group(1).strip()
        return vf, vt

    def _owut_check_one(self, ip: str, name: str) -> Dict[str, Any]:
        self._log(f"OWUT KONTROLA {name} ({ip})…")
        out, err, code = self._exec(ip, "command -v owut >/dev/null 2>&1 && owut check --verbose", timeout=180)
        text = (out + "\n" + err).strip()
        if code != 0:
            raise RuntimeError(f"OWUT check {name} ({ip}) selhal: {text[-1200:]}")
        version_from, version_to = self._parse_owut_versions(text)
        if not version_from or not version_to:
            # Některé verze mohou při bezezměnovém stavu formulovat výstup jinak.
            no_change = bool(re.search(r"no changes|nothing to do|up.to.date|same version", text, re.I))
            if not no_change:
                raise RuntimeError(f"OWUT check {name} ({ip}) nevrátil Version-from/Version-to.")
            available = False
        else:
            available = version_from != version_to
        return {
            "available": available,
            "version_from": version_from,
            "version_to": version_to,
            "summary": text[-2400:],
        }

    def _start_owut_detached(self, ip: str) -> None:
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


    def _validate_and_restore_extroot_first_boot(self, expected_uuid: str) -> str:
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

    def _repair_extroot_fstab_fallback(self, expected_uuid: str) -> str:
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


    def _owut_one(self, index: int, ip: str, name: str, check: Dict[str, Any], resume: bool = False) -> None:
        if not check.get("available"):
            self._node_update(ip, status="no_update", detail="Není nový sysupgrade",
                              before_revision=check.get("version_from", ""), after_revision=check.get("version_from", ""))
            self._log(f"{name} ({ip}): není k dispozici nový sysupgrade.")
            return

        state = self.snapshot()
        row = self._node(ip)
        stage = str(state.get("stage") or "") if state.get("current_ip") == ip else ""
        before_boot = str(row.get("before_boot_id") or "")

        if not before_boot:
            self._set(stage="owut_precheck", current_index=index, current_ip=ip, current_name=name,
                      status="running", progress=self._progress_for(index, 0.05), action_sent=False)
            info = self._wait_online_stable(ip, 180)
            before_boot = str(info.get("boot_id") or "")
            self._node_update(ip, status="upgrade_precheck", detail=f"{check.get('version_from')} -> {check.get('version_to')}",
                              before_boot_id=before_boot, before_revision=info.get("revision", ""),
                              temperature_c=info.get("temperature_c"))
            if ip == MAIN_IP:
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

        if stage in {"owut_action_sent", "owut_waiting_reboot", "owut_waiting_online", "owut_postcheck"} or state.get("action_sent"):
            self._log(f"{name} ({ip}): obnovuji rozpracovaný OWUT, upgrade znovu nespouštím.")
        elif stage == "owut_sending" and resume:
            try:
                current = self._router_info(ip)
                if before_boot and current.get("boot_id") != before_boot:
                    self._log(f"{name} ({ip}): boot_id se změnil, OWUT již provedl restart.")
                else:
                    out, _err, _code = self._exec(ip, "test -f /tmp/v500_owut.rc && cat /tmp/v500_owut.rc || pgrep -f '[o]wut upgrade' >/dev/null && echo RUNNING || true", timeout=15)
                    if "RUNNING" not in out and not re.search(r"^\d+", out.strip()):
                        self._log(f"{name} ({ip}): OWUT nebyl potvrzen, spouštím znovu.")
                        self._start_owut_detached(ip)
            except Exception:
                self._log(f"{name} ({ip}): uzel je nedostupný, čekám na jeho návrat.")
        else:
            self._set(stage="owut_sending", current_index=index, current_ip=ip, current_name=name,
                      progress=self._progress_for(index, 0.20), action_sent=False)
            self._node_update(ip, status="upgrading", detail=f"OWUT {check.get('version_to', '')}")
            self._log(f"{name} ({ip}): spouštím OWUT upgrade bez --force.")
            self._start_owut_detached(ip)
            self._set(stage="owut_action_sent", action_sent=True, action_sent_at=_now_text(),
                      status="waiting", progress=self._progress_for(index, 0.35))

        self._set(stage="owut_waiting_reboot", status="waiting", progress=self._progress_for(index, 0.55))
        after = self._wait_owut_reboot(ip, name, before_boot)
        self._set(stage="owut_postcheck", status="running", progress=self._progress_for(index, 0.80))

        if ip == IHOT_MESH_IP:
            self._log("MESH1 .2 po OWUT naběhl. Ověřuji MESH1 .2 i cestu k ROUTERu .1.")
            self._wait_online_stable(IHOT_MESH_IP, ONLINE_TIMEOUT)
            self._wait_online_stable(MAIN_IP, ONLINE_TIMEOUT)

        if ip == MAIN_IP:
            after = self._second_router_reboot_if_extroot(index, self.snapshot().get("pre_overlay") or {})

        self._node_update(ip, status="done", detail="SYSUPGRADE HOTOVO",
                          after_boot_id=after.get("boot_id", ""), after_revision=after.get("revision", ""),
                          temperature_c=after.get("temperature_c"))
        self._set(stage="node_done", action_sent=False, action_sent_at="",
                  progress=self._progress_for(index, 1.0))
        self._log(f"{name} ({ip}): OWUT/sysupgrade dokončen a SSH stabilní.")

    # -------------------------------------------------------------- reports --
    def _ihost_temperature(self) -> Optional[float]:
        return read_ihost_temperature()


    def _mail_settings(self) -> Dict[str, Any]:
        return _read_json(SETTINGS_FILE, {})

    def _build_report(self, ok: bool) -> Tuple[str, str, str]:
        state = self.snapshot()
        title = "KOMPLETNÍ REBOOT MESH" if state.get("kind") == "reboot_all" else "OWUT SYSUPGRADE"
        result = "VŠE V POŘÁDKU" if ok else "CHYBA / NEDOKONČENO"
        subject = f"{'OK' if ok else 'CHYBA'} – OpenWRT MESH {title}"
        rows_text: List[str] = []
        html_rows: List[str] = []
        by_ip = {str(r.get("ip")): r for r in state.get("nodes", [])}
        for ip, name in ROUTERS:
            row = by_ip.get(ip, {})
            status = str(row.get("status") or "pending")
            success = status in {"done", "no_update", "online"}
            mark = "OK" if success else "CHYBA" if status in {"error", "paused"} else status.upper()
            temp = row.get("temperature_c")
            temp_text = f"{temp} °C" if temp is not None else "N/A"
            detail = str(row.get("detail") or "")
            rows_text.append(f"{name:<7} {ip:<15} {mark:<12} CPU {temp_text}  {detail}")
            color = "#16a34a" if success else "#dc2626" if status in {"error", "paused"} else "#64748b"
            html_rows.append(
                f'<tr><td style="padding:7px 8px;font-weight:700">{html.escape(name)}</td>'
                f'<td style="padding:7px 8px;color:#64748b">{html.escape(ip)}</td>'
                f'<td style="padding:7px 8px;color:{color};font-weight:700">{html.escape(mark)}</td>'
                f'<td style="padding:7px 8px">{html.escape(temp_text)}</td>'
                f'<td style="padding:7px 8px;color:#64748b">{html.escape(detail)}</td></tr>'
            )

        ihost_temp = self._ihost_temperature()
        ihost_text = f"{ihost_temp} °C" if ihost_temp is not None else "N/A"

        controller_backup = state.get("controller_backup") or {}
        auto_owut = state.get("kind") == "owut_upgrade" and bool(state.get("automatic"))
        local_ok = bool(controller_backup.get("local_backup_ok"))
        nextcloud_ok = bool(controller_backup.get("nextcloud_ok"))
        backup_filename = str(controller_backup.get("filename") or "—")
        backup_detail = str(controller_backup.get("detail") or "")

        nl = chr(10)
        text_lines = [
            f"OpenWRT MESH CONTROLLER PRO v{VERSION}",
            "",
            f"Operace: {title}",
            f"Datum: {_now_text()}",
            f"Výsledek: {result}",
            f"Záloha: {state.get('backup_id') or '—'}",
            "",
            *rows_text,
            "",
            f"iHost teplota: {ihost_text}",
        ]
        if auto_owut:
            text_lines.extend([
                "",
                f"CONTROLLER BACKUP: {'OK' if local_ok else 'CHYBA'}",
                f"NEXTCLOUD BACKUP: {'OK' if nextcloud_ok else 'CHYBA'}",
                f"SOUBOR: {backup_filename}",
            ])
            if backup_detail:
                text_lines.append(f"BACKUP DETAIL: {backup_detail}")
        text_lines.extend(["", str(state.get("message") or "")])
        text_body = nl.join(text_lines)

        banner = "#16a34a" if ok else "#dc2626"
        controller_backup_html = ""
        if auto_owut:
            nc_color = "#16a34a" if nextcloud_ok else "#dc2626"
            local_color = "#16a34a" if local_ok else "#dc2626"
            controller_backup_html = (
                '<tr><td style="padding:0 20px 18px">'
                '<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;font-size:12px">'
                '<tr style="background:#f8fafc"><th colspan="2" style="padding:8px;text-align:left">ZÁLOHA CONTROLLERU · AUTOMATICKÝ OWUT</th></tr>'
                f'<tr><td style="padding:7px 8px">CONTROLLER BACKUP</td><td style="padding:7px 8px;color:{local_color};font-weight:700">{"OK" if local_ok else "CHYBA"}</td></tr>'
                f'<tr><td style="padding:7px 8px">NEXTCLOUD BACKUP</td><td style="padding:7px 8px;color:{nc_color};font-weight:700">{"OK" if nextcloud_ok else "CHYBA"}</td></tr>'
                f'<tr><td style="padding:7px 8px">SOUBOR</td><td style="padding:7px 8px;color:#334155">{html.escape(backup_filename)}</td></tr>'
                + (f'<tr><td style="padding:7px 8px">DETAIL</td><td style="padding:7px 8px;color:#64748b">{html.escape(backup_detail)}</td></tr>' if backup_detail else '')
                + '</table></td></tr>'
            )

        html_body = f'''<!doctype html><html><body style="margin:0;background:#f3f6f9;padding:20px 8px">
<table role="presentation" width="100%"><tr><td align="center"><table role="presentation" width="760" style="width:100%;max-width:760px;background:#fff;border:1px solid #dce3ea;border-radius:14px;overflow:hidden;border-spacing:0;font-family:Arial,sans-serif">
<tr><td style="background:#071a2d;padding:20px 24px;color:#fff"><b style="font-size:20px">OpenWRT MESH CONTROLLER PRO v{VERSION}</b><div style="font-size:12px;color:#cbd5e1;margin-top:4px">{html.escape(title)}</div></td></tr>
<tr><td style="padding:18px 20px"><div style="background:{banner};color:#fff;border-radius:10px;padding:16px 18px"><b style="font-size:19px">{html.escape(result)}</b><div style="font-size:12px;margin-top:5px">{html.escape(_now_text())}</div></div></td></tr>
<tr><td style="padding:0 20px 18px"><table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;font-size:12px"><tr style="background:#f8fafc"><th style="padding:7px">UZEL</th><th>IP</th><th>STAV</th><th>CPU</th><th>DETAIL</th></tr>{''.join(html_rows)}</table></td></tr>
{controller_backup_html}
<tr><td style="padding:0 20px 20px;color:#334155;font-size:12px">Záloha: <b>{html.escape(str(state.get('backup_id') or '—'))}</b> &nbsp; · &nbsp; iHost teplota: <b>{html.escape(ihost_text)}</b></td></tr>
<tr><td style="background:#071a2d;padding:12px 20px;color:#cbd5e1;font-size:10px">Persistent Operation Manager v{VERSION}</td></tr>
</table></td></tr></table></body></html>'''
        return subject, text_body, html_body

    def _send_mail(self, ok: bool) -> Tuple[bool, str]:
        settings = self._mail_settings()
        sender = str(settings.get("gmail_from") or "").strip()
        recipient = str(settings.get("gmail_to") or "").strip()
        password = str(settings.get("gmail_app_password") or "").replace(" ", "")
        if not sender or not recipient or not password:
            return False, "Gmail není kompletně nastavený."
        subject, text_body, html_body = self._build_report(ok)
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(text_body)
        if str(settings.get("mail_report_format") or "html").lower() == "html":
            msg.add_alternative(html_body, subtype="html")
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
                smtp.login(sender, password)
                smtp.send_message(msg)
            try:
                PENDING_MAIL_FILE.unlink()
            except FileNotFoundError:
                pass
            return True, "E-mail odeslán."
        except Exception as exc:
            try:
                _atomic_json_write(PENDING_MAIL_FILE, {
                    "subject": subject,
                    "body": text_body,
                    "text_body": text_body,
                    "html_body": html_body,
                    "created": _now_text(),
                })
            except Exception:
                pass
            return False, f"{exc}; report uložen do fronty."

    def _retry_pending_mail(self) -> None:
        if not PENDING_MAIL_FILE.exists():
            return
        settings = self._mail_settings()
        sender = str(settings.get("gmail_from") or "").strip()
        recipient = str(settings.get("gmail_to") or "").strip()
        password = str(settings.get("gmail_app_password") or "").replace(" ", "")
        if not sender or not recipient or not password:
            return
        try:
            data = _read_json(PENDING_MAIL_FILE, {})
            msg = EmailMessage()
            msg["From"] = sender
            msg["To"] = recipient
            msg["Subject"] = str(data.get("subject") or "OpenWRT MESH report")
            msg.set_content(str(data.get("text_body") or data.get("body") or ""))
            if str(settings.get("mail_report_format") or "html").lower() == "html" and data.get("html_body"):
                msg.add_alternative(str(data.get("html_body")), subtype="html")
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
                smtp.login(sender, password)
                smtp.send_message(msg)
            PENDING_MAIL_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    # --------------------------------------------------------------- health --
    def _final_health(self) -> None:
        self._set(stage="final_health", status="running", progress=98, message="Finální kontrola 5 routerů")
        for ip, name in ROUTERS:
            self._check_cancel()
            info = self._wait_online_stable(ip, 240)
            self._node_update(ip, temperature_c=info.get("temperature_c"), after_revision=info.get("revision", ""))
            self._log(f"HEALTH {name} ({ip}): SSH OK, rev {info.get('revision') or '?'}.")

    # -------------------------------------------------------------- workers --
    def _finish_success(self, message: str) -> None:
        self._set(status="done", stage="done", progress=100, message=message, finished_at=_now_text(),
                  action_sent=False, current_ip="", current_name="")
        sent, detail = self._send_mail(True)
        self._set(report={"sent": sent, "detail": detail})
        self._log(f"Gmail report: {'odeslán' if sent else 'neodeslán'} – {detail}")

    def _finish_failure(self, exc: Exception, paused: bool = False) -> None:
        status = "paused" if paused else "error"
        self._set(status=status, stage=status, message=str(exc), pause_reason=str(exc), finished_at=_now_text())
        current = self.snapshot().get("current_ip")
        if current:
            self._node_update(str(current), status=status, detail=str(exc)[:300])
        sent, detail = self._send_mail(False)
        self._set(report={"sent": sent, "detail": detail})
        self._log(f"Operace {status}: {exc}")
        self._log(f"Gmail report: {'odeslán' if sent else 'neodeslán'} – {detail}")

    def _run_reboot(self, resume: bool = False) -> None:
        try:
            start_index = int(self.snapshot().get("current_index") or 0) if resume else 0
            for index, (ip, name) in enumerate(REBOOT_ORDER):
                row = self._node(ip)
                if row.get("status") == "done":
                    continue
                if index < start_index and resume:
                    continue
                self._reboot_one(index, ip, name, resume=resume)
            self._final_health()
            self._finish_success("Kompletní rolling reboot všech 5 routerů dokončen.")
        except InterruptedError as exc:
            self._set(status="cancelled", stage="cancelled", message=str(exc), finished_at=_now_text())
        except (TimeoutError, paramiko.SSHException, OSError) as exc:
            # Síťový problém se pozastaví a lze jej automaticky/ručně obnovit bez opakování hotových uzlů.
            self._finish_failure(exc, paused=True)
        except Exception as exc:
            self._finish_failure(exc, paused=False)

    def _run_owut(self, resume: bool = False) -> None:
        try:
            state = self.snapshot()
            # v7.0.1 automatic controller/Nextcloud backup gate
            if bool(state.get("automatic")) and not resume and not state.get("controller_backup"):
                from controller_backup_v701 import automatic_backup_result_for_now
                controller_backup = automatic_backup_result_for_now()
                self._set(controller_backup=controller_backup)
                state = self.snapshot()
                if not bool(controller_backup.get("ok")):
                    detail = str(controller_backup.get("detail") or "Automatická záloha Controlleru/Nextcloudu pro tento termín není potvrzená.")
                    raise RuntimeError(f"NEXTCLOUD BACKUP: CHYBA – {detail} Automatický OWUT nebyl spuštěn.")
            checks = state.get("owut_checks") or {}
            if not checks:
                self._set(stage="owut_check_all", status="running", progress=2, message="OWUT kontrola všech 5 routerů")
                checks = {}
                for ip, name in ROUTERS:
                    self._wait_online_stable(ip, 180)
                    checks[ip] = self._owut_check_one(ip, name)
                    self._set(owut_checks=checks)
                available = [ip for ip, result in checks.items() if result.get("available")]
                if not available:
                    for ip, name in ROUTERS:
                        info = self._router_info(ip)
                        check = checks.get(ip, {})
                        self._node_update(ip, status="no_update", detail="Není nový sysupgrade",
                                          before_revision=info.get("revision", ""), after_revision=info.get("revision", ""),
                                          temperature_c=info.get("temperature_c"))
                    self._final_health()
                    self._log("AUTO/RUČNÍ OWUT: bez změn – žádný sysupgrade, žádný reboot, USB Extroot beze změny.")
                    self._finish_success("OWUT kontrola dokončena – nový sysupgrade není dostupný; USB Extroot beze změny.")
                    return
                if MAIN_IP in available:
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

            start_index = int(self.snapshot().get("current_index") or 0) if resume else 0
            for index, (ip, name) in enumerate(ROLLING_ORDER):
                row = self._node(ip)
                if row.get("status") in {"done", "no_update"}:
                    continue
                if index < start_index and resume:
                    continue
                check = checks.get(ip) or self._owut_check_one(ip, name)
                self._owut_one(index, ip, name, check, resume=resume)
            self._final_health()
            self._finish_success("OWUT/sysupgrade operace dokončena.")
        except InterruptedError as exc:
            self._set(status="cancelled", stage="cancelled", message=str(exc), finished_at=_now_text())
        except (TimeoutError, paramiko.SSHException, OSError) as exc:
            self._finish_failure(exc, paused=True)
        except Exception as exc:
            self._finish_failure(exc, paused=False)

    def _thread_entry(self, kind: str, resume: bool) -> None:
        try:
            if kind == "reboot_all":
                self._run_reboot(resume=resume)
            elif kind == "owut_upgrade":
                self._run_owut(resume=resume)
        finally:
            with self.worker_lock:
                self.worker = None

    def _start_thread(self, kind: str, resume: bool = False) -> bool:
        with self.worker_lock:
            if self.worker and self.worker.is_alive():
                return False
            self.worker = threading.Thread(
                target=self._thread_entry,
                args=(kind, resume),
                daemon=True,
                name=f"mesh-v500-{kind}",
            )
            self.worker.start()
            return True

    def start_operation(self, kind: str, automatic: bool = False, source: str = "web") -> Tuple[bool, str]:
        with self.lock:
            current = str(self.state.get("status") or "idle")
            if current in {"running", "waiting"}:
                return False, "Jiná mesh operace už probíhá."
            self.state = _default_state()
            self.state.update({
                "operation_id": uuid.uuid4().hex[:12],
                "kind": kind,
                "automatic": bool(automatic),
                "status": "running",
                "stage": "starting",
                "message": "Operace se připravuje",
                "created_at": _now_text(),
                "updated_at": _now_text(),
                "source": source,
            })
            self._save_locked()
        self._log(f"START v7.0.2: {kind} ({'automaticky' if automatic else source}).")
        if not self._start_thread(kind, resume=False):
            return False, "Worker se nepodařilo spustit."
        return True, "Operace spuštěna."

    def resume_operation(self, automatic: bool = False) -> Tuple[bool, str]:
        state = self.snapshot()
        kind = str(state.get("kind") or "")
        if kind not in {"reboot_all", "owut_upgrade"}:
            return False, "Není co obnovit."
        if state.get("status") == "done":
            return False, "Operace už je dokončená."
        self._set(status="running", stage=str(state.get("stage") or "resuming"), pause_reason="",
                  cancel_requested=False, message="Obnovuji rozpracovanou operaci")
        self._log("RESUME: pokračuji z uloženého /data/mesh_operation.json.")
        if not self._start_thread(kind, resume=True):
            return False, "Worker už běží."
        return True, "Operace obnovena."

    def cancel(self) -> Tuple[bool, str]:
        state = self.snapshot()
        if state.get("status") not in {"running", "waiting", "paused"}:
            return False, "Žádná aktivní operace."
        self._set(cancel_requested=True, message="Požadavek na zrušení byl uložen")
        return True, "Operace bude zastavena v nejbližším bezpečném bodě."

    # ------------------------------------------------------------ scheduler --
    def _scheduler_state(self) -> Dict[str, Any]:
        return _read_json(SCHEDULER_FILE, {"fingerprint": "", "last_date": ""})

    def _save_scheduler(self, data: Dict[str, Any]) -> None:
        _atomic_json_write(SCHEDULER_FILE, data)

    def _scheduler_loop(self) -> None:
        last_retry = 0.0
        while not self.stop_event.wait(20):
            try:
                now_mono = time.monotonic()
                if now_mono - last_retry >= 300:
                    last_retry = now_mono
                    self._retry_pending_mail()

                settings = self._mail_settings()
                if not bool(settings.get("auto_enabled")):
                    continue
                mode = str(settings.get("schedule_mode") or "weekly").lower()
                try:
                    weekday = int(settings.get("weekday", 6))
                except Exception:
                    weekday = 6
                time_str = str(settings.get("time") or "03:00")
                m = re.fullmatch(r"(\d{1,2}):(\d{2})", time_str)
                if not m:
                    continue
                hh, mm = int(m.group(1)), int(m.group(2))
                fingerprint = f"{mode}|{weekday}|{hh:02d}:{mm:02d}|{bool(settings.get('auto_enabled'))}"
                sched = self._scheduler_state()
                if sched.get("fingerprint") != fingerprint:
                    sched = {"fingerprint": fingerprint, "last_date": ""}
                    self._save_scheduler(sched)

                now = _now_dt()
                today = now.strftime("%Y-%m-%d")
                day_ok = mode == "daily" or weekday == -1 or now.weekday() == weekday
                scheduled_minute = hh * 60 + mm
                current_minute = now.hour * 60 + now.minute
                due = day_ok and scheduled_minute <= current_minute < scheduled_minute + 5
                if due and sched.get("last_date") != today:
                    sched["last_date"] = today
                    self._save_scheduler(sched)
                    if self.snapshot().get("status") in {"running", "waiting"}:
                        self._log("AUTO OWUT: čas nastal, ale jiná operace běží; dnešní běh přeskočen.")
                    else:
                        self.start_operation("owut_upgrade", automatic=True, source="scheduler-v500")
            except Exception:
                pass

    def _resume_on_start(self) -> None:
        time.sleep(8)
        state = self.snapshot()
        if state.get("status") in {"running", "waiting"} and state.get("kind") in {"reboot_all", "owut_upgrade"}:
            self.resume_operation(automatic=True)

    def start_background(self) -> None:
        threading.Thread(target=self._scheduler_loop, daemon=True, name="mesh-v500-scheduler").start()
        threading.Thread(target=self._resume_on_start, daemon=True, name="mesh-v500-resume").start()


_manager: Optional[PersistentMeshOperationManager] = None


def get_operation_manager() -> Optional[PersistentMeshOperationManager]:
    return _manager


def v500_scheduler_owned() -> bool:
    return _manager is not None


def init_operation_manager(app: Any) -> PersistentMeshOperationManager:
    global _manager
    existing = app.extensions.get("mesh_operation_v500") if hasattr(app, "extensions") else None
    if existing is not None:
        return existing
    if _manager is None:
        _manager = PersistentMeshOperationManager()
    manager = _manager
    app.extensions["mesh_operation_v500"] = manager

    if "v500_operation_state" not in app.view_functions:
        @app.get("/api/v500/operation", endpoint="v500_operation_state")
        def _v500_operation_state():
            return jsonify({"ok": True, "state": manager.snapshot()})

    if "v500_operation_reboot" not in app.view_functions:
        @app.post("/api/v500/reboot", endpoint="v500_operation_reboot")
        def _v500_operation_reboot():
            ok, detail = manager.start_operation("reboot_all", automatic=False, source="web")
            return jsonify({"ok": ok, "message": detail, "state": manager.snapshot()}), (200 if ok else 409)

    if "v500_operation_owut" not in app.view_functions:
        @app.post("/api/v500/owut", endpoint="v500_operation_owut")
        def _v500_operation_owut():
            payload = request.get_json(silent=True) or {}
            automatic = bool(payload.get("automatic", False))
            ok, detail = manager.start_operation("owut_upgrade", automatic=automatic, source="web")
            return jsonify({"ok": ok, "message": detail, "state": manager.snapshot()}), (200 if ok else 409)

    if "v500_operation_resume" not in app.view_functions:
        @app.post("/api/v500/resume", endpoint="v500_operation_resume")
        def _v500_operation_resume():
            ok, detail = manager.resume_operation()
            return jsonify({"ok": ok, "message": detail, "state": manager.snapshot()}), (200 if ok else 409)

    if "v500_operation_cancel" not in app.view_functions:
        @app.post("/api/v500/cancel", endpoint="v500_operation_cancel")
        def _v500_operation_cancel():
            ok, detail = manager.cancel()
            return jsonify({"ok": ok, "message": detail, "state": manager.snapshot()}), (200 if ok else 409)

    manager.start_background()
    return manager
