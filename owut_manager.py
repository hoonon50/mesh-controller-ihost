from __future__ import annotations

import json
import os
import re
import shlex
import smtplib
import ssl
import tarfile
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify, request

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SETTINGS_FILE = DATA_DIR / "owut_settings.json"
PENDING_MAIL_FILE = DATA_DIR / "owut_pending_mail.json"
BACKUP_ROOT = DATA_DIR / "backups"
MAIN_IP = "192.168.30.1"
ROUTERS = [
    ("192.168.30.1", "ROUTER"),
    ("192.168.30.2", "MESH1"),
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
]
UPDATE_ORDER = [
    ("192.168.30.2", "MESH1"),
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
    ("192.168.30.1", "ROUTER"),
]
EXTROOT_ADD = "block-mount,kmod-fs-ext4,kmod-usb-storage,kmod-usb-storage-uas"

DEFAULT_SETTINGS = {
    "auto_enabled": False,
    "weekday": 6,              # neděle (0 = pondělí)
    "time": "03:00",
    "gmail_from": "",
    "gmail_to": "",
    "gmail_app_password": "",
    "last_auto_date": "",
}

_state_lock = threading.RLock()
_operation: Dict[str, Any] = {
    "running": False,
    "kind": "",
    "started": None,
    "finished": None,
    "progress": 0,
    "message": "Připraveno",
    "log": [],
    "result": None,
}


def _now_text() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _load_settings() -> Dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            parsed = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                data.update(parsed)
    except Exception:
        pass
    return data


def _save_settings(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(SETTINGS_FILE)
    try:
        os.chmod(SETTINGS_FILE, 0o600)
    except Exception:
        pass


def _public_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(data)
    out["gmail_app_password"] = ""  # heslo nikdy neposíláme zpět do prohlížeče
    out["gmail_password_saved"] = bool(data.get("gmail_app_password"))
    return out


def _op_reset(kind: str, message: str) -> None:
    with _state_lock:
        _operation.update({
            "running": True,
            "kind": kind,
            "started": _now_text(),
            "finished": None,
            "progress": 0,
            "message": message,
            "log": [],
            "result": None,
        })


def _op_log(text: str, progress: Optional[int] = None) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
    with _state_lock:
        _operation["log"].append(line)
        _operation["log"] = _operation["log"][-300:]
        _operation["message"] = text
        if progress is not None:
            _operation["progress"] = max(0, min(100, int(progress)))


def _op_finish(ok: bool, message: str, result: Optional[Dict[str, Any]] = None) -> None:
    with _state_lock:
        _operation["running"] = False
        _operation["finished"] = _now_text()
        _operation["progress"] = 100
        _operation["message"] = message
        _operation["result"] = result or {"ok": ok}
        _operation["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def _snapshot_operation() -> Dict[str, Any]:
    with _state_lock:
        return json.loads(json.dumps(_operation, ensure_ascii=False))


def _ssh_exec(controller, ip: str, cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
    client = None
    try:
        client = controller.ssh_client(ip, min(timeout, 10))
        out, err, code = controller.command(client, cmd, timeout)
        return str(out or ""), str(err or ""), int(code if code is not None else 0)
    finally:
        try:
            if client:
                client.close()
        except Exception:
            pass


def _ssh_ok(controller, ip: str, timeout: int = 5) -> bool:
    try:
        _out, _err, code = _ssh_exec(controller, ip, "true", timeout)
        return code == 0
    except Exception:
        return False


def _wait_offline(controller, ip: str, timeout: int = 180) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _ssh_ok(controller, ip, 4):
            return True
        time.sleep(4)
    return False


def _wait_online(controller, ip: str, timeout: int = 480) -> bool:
    deadline = time.time() + timeout
    consecutive = 0
    while time.time() < deadline:
        if _ssh_ok(controller, ip, 5):
            consecutive += 1
            if consecutive >= 2:
                return True
        else:
            consecutive = 0
        time.sleep(6)
    return False


def _router_hostname(controller, ip: str, fallback: str) -> str:
    try:
        out, _err, code = _ssh_exec(
            controller,
            ip,
            "uci -q get system.@system[0].hostname 2>/dev/null || cat /proc/sys/kernel/hostname 2>/dev/null || echo unknown",
            8,
        )
        name = out.strip().splitlines()[0] if out.strip() else ""
        if code == 0 and name and name != "unknown":
            return name
    except Exception:
        pass
    return fallback


def _release_info(controller, ip: str) -> Dict[str, str]:
    cmd = r'''printf 'VERSION='; . /etc/openwrt_release 2>/dev/null; printf '%s\n' "${DISTRIB_RELEASE:-unknown}"
printf 'REVISION='; . /etc/openwrt_release 2>/dev/null; printf '%s\n' "${DISTRIB_REVISION:-unknown}"
printf 'TARGET='; . /etc/openwrt_release 2>/dev/null; printf '%s\n' "${DISTRIB_TARGET:-unknown}"
printf 'OWUT='; (owut --version 2>/dev/null | head -n1) || true
'''
    out, _err, _code = _ssh_exec(controller, ip, cmd, 12)
    result: Dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.lower()] = v.strip()
    return result


def _overlay_info(controller, ip: str = MAIN_IP) -> Dict[str, Any]:
    cmd = r'''DEV="$(df -P /overlay 2>/dev/null | awk 'NR==2 {print $1}')"
FREE="$(df -hP /overlay 2>/dev/null | awk 'NR==2 {print $4}')"
UUID=""
[ -n "$DEV" ] && UUID="$(blkid -s UUID -o value "$DEV" 2>/dev/null || true)"
printf 'DEV=%s\nFREE=%s\nUUID=%s\n' "$DEV" "$FREE" "$UUID"
'''
    out, err, code = _ssh_exec(controller, ip, cmd, 12)
    data = {"ok": code == 0, "device": "", "free": "", "uuid": "", "usb": False, "error": err.strip()}
    for line in out.splitlines():
        if line.startswith("DEV="):
            data["device"] = line[4:].strip()
        elif line.startswith("FREE="):
            data["free"] = line[5:].strip()
        elif line.startswith("UUID="):
            data["uuid"] = line[5:].strip()
    dev = str(data.get("device") or "")
    data["usb"] = bool(re.match(r"^/dev/sd[a-z][0-9]+$", dev))
    return data


def _ensure_owut(controller, ip: str) -> Tuple[bool, str]:
    try:
        out, _err, code = _ssh_exec(controller, ip, "command -v owut >/dev/null 2>&1 && owut --version | head -n1", 10)
        if code == 0 and out.strip():
            return True, out.strip().splitlines()[0]
    except Exception:
        pass

    # Bootstrap pouze pokud owut chybí. Samotné firmware upgrady níže běží výhradně přes owut.
    install = r'''if command -v apk >/dev/null 2>&1; then
    apk --update-cache add owut
elif command -v opkg >/dev/null 2>&1; then
    opkg update && opkg install owut
else
    exit 127
fi
command -v owut >/dev/null 2>&1 && owut --version | head -n1
'''
    try:
        out, err, code = _ssh_exec(controller, ip, install, 180)
        if code == 0 and out.strip():
            return True, out.strip().splitlines()[-1]
        return False, (err or out or "owut se nepodařilo nainstalovat").strip()
    except Exception as exc:
        return False, str(exc)


def _owut_args(ip: str) -> str:
    if ip == MAIN_IP:
        return f"--add {shlex.quote(EXTROOT_ADD)}"
    return ""


def _owut_check(controller, ip: str) -> Tuple[bool, str, int]:
    add = _owut_args(ip)
    cmd = f"owut check --verbose {add}".strip()
    try:
        out, err, code = _ssh_exec(controller, ip, cmd, 600)
    except Exception as exc:
        return False, str(exc), 255
    text = (out + ("\n" + err if err else "")).strip()
    low = text.lower()
    blockers = (
        "upgrade without keeping config",
        "config is incompatible",
        "sysupgrade validation failed",
        "image check failed",
        "upgrade still possible with '--force'",
        'upgrade still possible with "--force"',
        "checks reveal errors, do not upgrade",
        "cannot upgrade",
    )
    if code != 0 or any(x in low for x in blockers):
        return False, text, code
    return True, text, code


def _stream_remote_file(controller, ip: str, remote_path: str, local_path: Path, timeout: int = 120) -> None:
    client = controller.ssh_client(ip, 8)
    try:
        transport = client.get_transport()
        channel = transport.open_session()
        channel.settimeout(timeout)
        channel.exec_command(f"cat {shlex.quote(remote_path)}")
        with local_path.open("wb") as handle:
            while True:
                chunk = channel.recv(65536)
                if not chunk:
                    break
                handle.write(chunk)
        code = channel.recv_exit_status()
        if code != 0:
            raise RuntimeError(f"cat {remote_path} skončil kódem {code}")
    finally:
        try:
            client.close()
        except Exception:
            pass


def _backup_all(controller) -> Tuple[bool, str, List[Dict[str, Any]]]:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_id = f"OWUT_{stamp}"
    folder = BACKUP_ROOT / backup_id
    folder.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []

    for idx, (ip, label) in enumerate(ROUTERS, 1):
        _op_log(f"Záloha {label} ({ip})…", 5 + idx * 4)
        remote = f"/tmp/{label}.tar.gz"
        local = folder / f"{label}.tar.gz"
        try:
            out, err, code = _ssh_exec(controller, ip, f"sysupgrade -b {shlex.quote(remote)}", 90)
            if code != 0:
                raise RuntimeError((err or out or f"sysupgrade -b skončil {code}").strip())
            _stream_remote_file(controller, ip, remote, local, 120)
            _ssh_exec(controller, ip, f"rm -f {shlex.quote(remote)}", 10)
            with tarfile.open(local, "r:gz") as tf:
                tf.getmembers()
            records.append({"ip": ip, "name": label, "file": local.name, "ok": True})
        except Exception as exc:
            records.append({"ip": ip, "name": label, "file": local.name, "ok": False, "error": str(exc)})
            manifest = {
                "id": backup_id,
                "created": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                "created_epoch": int(time.time()),
                "timezone": os.environ.get("TZ", "Europe/Prague"),
                "type": "owut-preupgrade",
                "routers": records,
            }
            (folder / "backup_info.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return False, backup_id, records

    manifest = {
        "id": backup_id,
        "created": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "created_epoch": int(time.time()),
        "timezone": os.environ.get("TZ", "Europe/Prague"),
        "type": "owut-preupgrade",
        "routers": records,
    }
    (folder / "backup_info.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, backup_id, records


def _start_owut_background(controller, ip: str) -> Tuple[bool, str]:
    add = _owut_args(ip)
    cmd = f"owut upgrade --verbose {add}".strip()
    # SSH relaci ukoncime hned, ale owut musi pokracovat i po jejim zavreni.
    # Proto je upgrade oddeleny pres nohup. Pri skutecnem sysupgrade se /tmp
    # smaze rebootem; pri "neni co aktualizovat" zustane exit kod pro kontrolu.
    inner = f"{cmd} > /tmp/mesh-owut.log 2>&1; echo $? > /tmp/mesh-owut.exit"
    shell = (
        "rm -f /tmp/mesh-owut.exit /tmp/mesh-owut.log; "
        f"nohup sh -c {shlex.quote(inner)} >/dev/null 2>&1 </dev/null & "
        "printf 'STARTED\n'"
    )
    try:
        out, err, code = _ssh_exec(controller, ip, shell, 15)
        return code == 0 and "STARTED" in out, (err or out).strip()
    except Exception as exc:
        return False, str(exc)


def _watch_owut(controller, ip: str, build_timeout: int = 1200, reboot_timeout: int = 480) -> Tuple[bool, str, bool]:
    """Vrací (ok, detail, rebooted)."""
    deadline = time.time() + build_timeout
    last_log = ""
    while time.time() < deadline:
        if not _ssh_ok(controller, ip, 4):
            _op_log(f"{ip}: router se restartuje po owut…")
            if not _wait_online(controller, ip, reboot_timeout):
                return False, "Router se po owut nevrátil online.", True
            return True, "Router se po owut vrátil online.", True

        try:
            out, _err, _code = _ssh_exec(
                controller,
                ip,
                "printf 'EXIT='; cat /tmp/mesh-owut.exit 2>/dev/null || true; printf '\\n'; tail -n 12 /tmp/mesh-owut.log 2>/dev/null || true",
                10,
            )
            last_log = out.strip() or last_log
            m = re.search(r"^EXIT=(\d+)\s*$", out, re.M)
            if m:
                code = int(m.group(1))
                low = out.lower()
                if code == 0:
                    if "no changes" in low or "nothing to do" in low or "no upgrade" in low:
                        return True, "owut: není co aktualizovat.", False
                    return True, "owut dokončil operaci bez restartu.", False
                return False, out.strip(), False
        except Exception:
            pass
        time.sleep(10)

    return False, last_log or "Timeout při čekání na owut.", False


def _reboot_and_wait(controller, ip: str, label: str, timeout: int = 480) -> Tuple[bool, str]:
    try:
        # reboot typicky zavře SSH dřív, než dostaneme exit status; proto spouštíme na pozadí.
        _ssh_exec(controller, ip, "(sleep 2; reboot) >/dev/null 2>&1 &", 8)
    except Exception:
        pass
    _wait_offline(controller, ip, 90)
    if not _wait_online(controller, ip, timeout):
        return False, f"{label} se po restartu nevrátil online."
    return True, f"{label} je po restartu online."


def _save_pending_mail(subject: str, body: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {"subject": subject, "body": body, "created": _now_text()}
    tmp = PENDING_MAIL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(PENDING_MAIL_FILE)
    try:
        os.chmod(PENDING_MAIL_FILE, 0o600)
    except Exception:
        pass


def _retry_pending_mail() -> Tuple[bool, str]:
    if not PENDING_MAIL_FILE.exists():
        return True, "Žádný čekající report."
    try:
        data = json.loads(PENDING_MAIL_FILE.read_text(encoding="utf-8"))
        subject = str(data.get("subject") or "OpenWRT MESH report")
        body = str(data.get("body") or "")
    except Exception as exc:
        return False, f"Čekající report nelze načíst: {exc}"
    ok, detail = _send_gmail(subject, body)
    if ok:
        try:
            PENDING_MAIL_FILE.unlink()
        except FileNotFoundError:
            pass
    return ok, detail


def _send_report_or_queue(subject: str, body: str) -> Tuple[bool, str]:
    ok, detail = _send_gmail(subject, body)
    if ok:
        try:
            PENDING_MAIL_FILE.unlink()
        except FileNotFoundError:
            pass
        return True, detail
    try:
        _save_pending_mail(subject, body)
        return False, f"{detail} Report uložen do /data a bude automaticky odeslán později."
    except Exception as exc:
        return False, f"{detail} Navíc se nepodařilo uložit čekající report: {exc}"


def _send_gmail(subject: str, body: str) -> Tuple[bool, str]:
    settings = _load_settings()
    sender = str(settings.get("gmail_from") or "").strip()
    recipient = str(settings.get("gmail_to") or "").strip()
    password = str(settings.get("gmail_app_password") or "").replace(" ", "")
    if not sender or not recipient or not password:
        return False, "Gmail není kompletně nastavený."

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
        return True, "E-mail odeslán."
    except Exception as exc:
        return False, str(exc)


def _build_report(kind: str, ok: bool, rows: List[Dict[str, Any]], backup_id: str = "", extra: str = "") -> str:
    lines = [
        "OpenWRT MESH CONTROLLER PRO",
        "",
        f"Operace: {kind}",
        f"Datum: {_now_text()}",
    ]
    if backup_id:
        lines.append(f"Záloha: {backup_id}")
    lines.append("")
    for row in rows:
        status = "OK" if row.get("ok") else "CHYBA"
        lines.append(f"{row.get('name', ''):<8} {row.get('ip', ''):<15} {status}")
        detail = str(row.get("detail") or row.get("error") or "").strip()
        if detail:
            detail = " ".join(detail.split())
            if len(detail) > 500:
                detail = detail[:500] + "…"
            lines.append(f"  {detail}")
    if extra:
        lines.extend(["", extra])
    lines.extend(["", f"VÝSLEDEK: {'VŠE V POŘÁDKU' if ok else 'CHYBA / NEDOKONČENO'}"])
    return "\n".join(lines)


def _upgrade_worker(controller, automatic: bool = False) -> None:
    if _snapshot_operation().get("running"):
        return
    _op_reset("auto-upgrade" if automatic else "manual-upgrade", "Příprava OWUT aktualizace…")
    rows: List[Dict[str, Any]] = []
    backup_id = ""
    overall_ok = False
    extra = ""

    try:
        # 1) Všechny routery musí být online a mít owut.
        _op_log("Kontroluji dostupnost všech 5 routerů…", 2)
        for ip, label in ROUTERS:
            if not _ssh_ok(controller, ip, 6):
                raise RuntimeError(f"{label} ({ip}) není dostupný. Aktualizace se nespustí.")
            ok, detail = _ensure_owut(controller, ip)
            if not ok:
                raise RuntimeError(f"{label} ({ip}): {detail}")

        # 2) Hlavní router musí mít aktivní USB extroot, protože to je jeho očekávaná konfigurace.
        overlay_before = _overlay_info(controller, MAIN_IP)
        if not overlay_before.get("usb"):
            raise RuntimeError(
                f"ROUTER {MAIN_IP}: USB overlay není aktivní (aktuálně {overlay_before.get('device') or 'neznámé'}). "
                "OWUT sysupgrade byl z bezpečnostních důvodů zastaven."
            )
        _op_log(
            f"ROUTER: USB overlay OK – {overlay_before.get('device')} / UUID {overlay_before.get('uuid') or 'N/A'}.",
            5,
        )

        # 3) Preflight owut check na všech routerech. Žádný --force.
        # Pokud není změna na žádném uzlu, nic neflashujeme a nevytváříme zbytečnou zálohu.
        preflight: List[Dict[str, Any]] = []
        for idx, (ip, label) in enumerate(UPDATE_ORDER, 1):
            _op_log(f"{label}: owut check --verbose…", 8 + idx * 3)
            ok, output, _code = _owut_check(controller, ip)
            low = output.lower()
            no_changes = "there are no changes, upgrade not necessary" in low
            preflight.append({"ip": ip, "name": label, "ok": ok, "no_changes": no_changes, "detail": output})
            if not ok:
                rows.append({"ip": ip, "name": label, "ok": False, "detail": output})
                raise RuntimeError(f"{label}: owut preflight odmítl aktualizaci. Žádný --force nebude použit.")

        if preflight and all(x.get("no_changes") for x in preflight):
            rows = [
                {"ip": x["ip"], "name": x["name"], "ok": True, "detail": "OWUT: není dostupná nová změna."}
                for x in preflight
            ]
            overall_ok = True
            extra = "OWUT na všech 5 routerech hlásí, že není co aktualizovat. Firmware nebyl flashován."
            _op_finish(True, "OWUT: není dostupná aktualizace – nic se neflashovalo.", {"ok": True, "rows": rows, "backup_id": "", "no_update": True})
            return

        # 4) Plná záloha všech routerů až ve chvíli, kdy je skutečně co aktualizovat.
        ok_backup, backup_id, backup_rows = _backup_all(controller)
        if not ok_backup:
            failed = next((x for x in backup_rows if not x.get("ok")), {})
            raise RuntimeError(f"Záloha selhala na {failed.get('name', '?')}: {failed.get('error', '')}")
        _op_log(f"Záloha všech routerů hotová: {backup_id}", 30)

        # 5) Satelity první, hlavní router poslední.
        total = len(UPDATE_ORDER)
        for idx, (ip, label) in enumerate(UPDATE_ORDER, 1):
            base_progress = 45 + int((idx - 1) * 45 / total)
            _op_log(f"{label}: spouštím owut upgrade…", base_progress)
            started, detail = _start_owut_background(controller, ip)
            if not started:
                rows.append({"ip": ip, "name": label, "ok": False, "detail": detail})
                raise RuntimeError(f"{label}: owut upgrade se nepodařilo spustit.")

            ok, detail, rebooted = _watch_owut(controller, ip)
            if not ok:
                rows.append({"ip": ip, "name": label, "ok": False, "detail": detail})
                raise RuntimeError(f"{label}: owut aktualizace selhala nebo se nedokončila.")

            # Hlavní router s extrootem: po prvním bootu je dle OpenWrt potřeba ještě druhý reboot.
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

            rows.append({"ip": ip, "name": label, "ok": True, "detail": detail})
            _op_log(f"{label}: OK", base_progress + 8)

        # 6) Finální kontrola celé sítě.
        _op_log("Finální kontrola všech routerů…", 96)
        offline = []
        for ip, label in ROUTERS:
            if not _ssh_ok(controller, ip, 6):
                offline.append(f"{label} {ip}")
        if offline:
            raise RuntimeError("Po aktualizaci nejsou online: " + ", ".join(offline))

        overall_ok = True
        extra = "Všech 5 routerů je po operaci dostupných přes SSH."
        _op_finish(True, "OWUT aktualizace dokončena – všech 5 routerů OK.", {"ok": True, "rows": rows, "backup_id": backup_id})
    except Exception as exc:
        extra = str(exc)
        _op_log(f"CHYBA: {exc}")
        _op_finish(False, f"OWUT aktualizace nedokončena: {exc}", {"ok": False, "rows": rows, "backup_id": backup_id})
    finally:
        report = _build_report("AUTOMATICKÝ OWUT SYSUPGRADE" if automatic else "RUČNÍ OWUT SYSUPGRADE", overall_ok, rows, backup_id, extra)
        mail_ok, mail_detail = _send_report_or_queue(
            f"{'OK' if overall_ok else 'CHYBA'} – OpenWRT MESH OWUT aktualizace",
            report,
        )
        _op_log(f"Gmail report: {'odeslán' if mail_ok else 'neodeslán'} – {mail_detail}")


def _check_worker(controller) -> None:
    if _snapshot_operation().get("running"):
        return
    _op_reset("owut-check", "Kontrola OWUT…")
    rows: List[Dict[str, Any]] = []
    try:
        for idx, (ip, label) in enumerate(ROUTERS, 1):
            _op_log(f"{label}: kontroluji owut…", idx * 18)
            if not _ssh_ok(controller, ip, 6):
                rows.append({"ip": ip, "name": label, "ok": False, "detail": "OFFLINE"})
                continue
            installed, detail = _ensure_owut(controller, ip)
            if not installed:
                rows.append({"ip": ip, "name": label, "ok": False, "detail": detail})
                continue
            ok, output, _code = _owut_check(controller, ip)
            info = _release_info(controller, ip)
            detail_text = f"OpenWrt {info.get('version','?')} {info.get('revision','')} | {detail}"
            if output:
                # Do UI posíláme jen poslední relevantní řádky, plný log není potřeba.
                tail = " | ".join([x.strip() for x in output.splitlines()[-4:] if x.strip()])
                if tail:
                    detail_text += " | " + tail[:900]
            rows.append({"ip": ip, "name": label, "ok": ok, "detail": detail_text})
        ok_all = all(x.get("ok") for x in rows) and len(rows) == 5
        _op_finish(ok_all, "OWUT kontrola dokončena." if ok_all else "OWUT kontrola našla problém.", {"ok": ok_all, "rows": rows})
    except Exception as exc:
        _op_finish(False, f"OWUT kontrola selhala: {exc}", {"ok": False, "rows": rows})


def _overlay_setup_worker(controller) -> None:
    if _snapshot_operation().get("running"):
        return
    _op_reset("overlay-setup", "Připravuji ruční USB overlay na ROUTERu…")
    try:
        current = _overlay_info(controller, MAIN_IP)
        if current.get("usb"):
            raise RuntimeError(f"USB overlay je už aktivní na {current.get('device')}; instalace byla zrušena.")

        _op_log("ROUTER: instaluji nástroje pro USB/ext4…", 10)
        setup = r'''set -e
apk update
apk add block-mount fdisk e2fsprogs kmod-fs-ext4 kmod-usb-storage kmod-usb-storage-uas blkid wipefs
USB_DEV="$(ls /dev/sd[a-z] 2>/dev/null | head -n1)"
[ -n "$USB_DEV" ] || { echo 'USB disk nenalezen'; exit 20; }
echo "USB_DEV=$USB_DEV"
if df -P /overlay | awk 'NR==2 {print $1}' | grep -q '^/dev/sd'; then
  echo 'USB overlay je již aktivní'; exit 21
fi
umount ${USB_DEV}* 2>/dev/null || true
wipefs -a "$USB_DEV"
dd if=/dev/zero of="$USB_DEV" bs=1M count=10 conv=notrunc
sync
printf "o\nn\np\n1\n\n\nw\n" | fdisk "$USB_DEV"
sleep 3
PART="${USB_DEV}1"
mkfs.ext4 -F "$PART"
mkdir -p /mnt/usb
mount "$PART" /mnt/usb
cp -a /overlay/. /mnt/usb/
sync
MY_UUID="$(blkid -s UUID -o value "$PART")"
[ -n "$MY_UUID" ] || { echo 'UUID nenalezeno'; exit 22; }
cat > /etc/config/fstab <<EOF
config global
        option delay_root '10'
        option auto_mount '1'
        option auto_swap '1'

config mount
        option target '/overlay'
        option uuid '$MY_UUID'
        option enabled '1'
        option fstype 'ext4'
EOF
sync
umount /mnt/usb
echo "PART=$PART"
echo "UUID=$MY_UUID"
'''
        out, err, code = _ssh_exec(controller, MAIN_IP, setup, 900)
        if code != 0:
            raise RuntimeError((err or out or f"Overlay setup skončil kódem {code}").strip())
        _op_log("USB disk připraven. Restartuji ROUTER…", 65)
        ok, detail = _reboot_and_wait(controller, MAIN_IP, "ROUTER", 480)
        if not ok:
            raise RuntimeError(detail)
        time.sleep(8)
        info = _overlay_info(controller, MAIN_IP)
        if not info.get("usb"):
            _op_log("Po prvním bootu ještě není USB overlay aktivní. Provádím druhý restart…", 82)
            ok, detail = _reboot_and_wait(controller, MAIN_IP, "ROUTER", 480)
            if not ok:
                raise RuntimeError(detail)
            time.sleep(8)
            info = _overlay_info(controller, MAIN_IP)
        if not info.get("usb"):
            raise RuntimeError(f"USB overlay se neaktivoval; /overlay je na {info.get('device') or 'N/A'}.")
        _op_finish(True, f"USB overlay aktivní: {info.get('device')} ({info.get('free')} volno).", {"ok": True, "overlay": info})
    except Exception as exc:
        _op_finish(False, f"USB overlay se nepodařilo nastavit: {exc}", {"ok": False, "error": str(exc)})


def _reboot_worker(controller, targets: List[Tuple[str, str]]) -> None:
    if _snapshot_operation().get("running"):
        return
    _op_reset("reboot", "Restart routerů…")
    rows = []
    try:
        total = max(1, len(targets))
        for idx, (ip, label) in enumerate(targets, 1):
            _op_log(f"Restartuji {label} ({ip})…", int((idx - 1) * 90 / total))
            ok, detail = _reboot_and_wait(controller, ip, label)
            rows.append({"ip": ip, "name": label, "ok": ok, "detail": detail})
            if not ok:
                raise RuntimeError(detail)
        _op_finish(True, "Restart dokončen.", {"ok": True, "rows": rows})
    except Exception as exc:
        _op_finish(False, f"Restart nedokončen: {exc}", {"ok": False, "rows": rows})


def _scheduler_loop(controller) -> None:
    last_mail_retry = 0.0
    while True:
        try:
            now_mono = time.monotonic()
            if PENDING_MAIL_FILE.exists() and now_mono - last_mail_retry >= 300:
                last_mail_retry = now_mono
                _retry_pending_mail()
            settings = _load_settings()
            if settings.get("auto_enabled"):
                now = datetime.now()
                try:
                    hh, mm = [int(x) for x in str(settings.get("time", "03:00")).split(":", 1)]
                except Exception:
                    hh, mm = 3, 0
                weekday = int(settings.get("weekday", 6))
                today = now.strftime("%Y-%m-%d")
                due = now.weekday() == weekday and now.hour == hh and now.minute == mm
                if due and settings.get("last_auto_date") != today and not _snapshot_operation().get("running"):
                    settings["last_auto_date"] = today
                    _save_settings(settings)
                    threading.Thread(target=_upgrade_worker, args=(controller, True), daemon=True).start()
        except Exception:
            pass
        time.sleep(30)


def register_owut_manager(app, controller) -> None:
    if getattr(app, "_owut_manager_registered", False):
        return
    app._owut_manager_registered = True

    @app.get("/api/owut/settings")
    def owut_settings_get():
        return jsonify(_public_settings(_load_settings()))

    @app.post("/api/owut/settings")
    def owut_settings_save():
        incoming = request.get_json(silent=True) or {}
        data = _load_settings()
        data["auto_enabled"] = bool(incoming.get("auto_enabled", False))
        try:
            wd = int(incoming.get("weekday", data.get("weekday", 6)))
            data["weekday"] = wd if 0 <= wd <= 6 else 6
        except Exception:
            data["weekday"] = 6
        tm = str(incoming.get("time", data.get("time", "03:00"))).strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", tm):
            return jsonify({"ok": False, "error": "Čas musí být HH:MM."}), 400
        data["time"] = tm
        data["gmail_from"] = str(incoming.get("gmail_from", data.get("gmail_from", ""))).strip()
        data["gmail_to"] = str(incoming.get("gmail_to", data.get("gmail_to", ""))).strip()
        password = str(incoming.get("gmail_app_password", ""))
        if password.strip():
            data["gmail_app_password"] = password.strip()
        if incoming.get("clear_gmail_password"):
            data["gmail_app_password"] = ""
        if data.get("auto_enabled"):
            if not str(data.get("gmail_from") or "").strip() or not str(data.get("gmail_to") or "").strip() or not str(data.get("gmail_app_password") or "").strip():
                return jsonify({"ok": False, "error": "Pro automatickou aktualizaci nastav Gmail odesílatele, příjemce a heslo aplikace."}), 400
        _save_settings(data)
        return jsonify({"ok": True, "settings": _public_settings(data)})

    @app.post("/api/owut/test-email")
    def owut_test_email():
        ok, detail = _send_gmail(
            "TEST – OpenWRT MESH CONTROLLER PRO",
            f"Testovací e-mail z OpenWRT MESH CONTROLLER PRO.\n\nDatum: {_now_text()}\n\nSMTP komunikace funguje.",
        )
        return jsonify({"ok": ok, "message": detail}), (200 if ok else 400)

    @app.get("/api/owut/status")
    def owut_status():
        routers = []
        for ip, label in ROUTERS:
            item: Dict[str, Any] = {"ip": ip, "name": label, "online": False}
            try:
                item["online"] = _ssh_ok(controller, ip, 5)
                if item["online"]:
                    item["name"] = _router_hostname(controller, ip, label)
                    item.update(_release_info(controller, ip))
            except Exception as exc:
                item["error"] = str(exc)
            routers.append(item)
        overlay = {}
        try:
            if routers and routers[0].get("online"):
                overlay = _overlay_info(controller, MAIN_IP)
        except Exception as exc:
            overlay = {"ok": False, "error": str(exc)}
        return jsonify({"routers": routers, "overlay": overlay, "operation": _snapshot_operation()})

    @app.get("/api/owut/operation")
    def owut_operation():
        return jsonify(_snapshot_operation())

    @app.post("/api/owut/check")
    def owut_check_start():
        if _snapshot_operation().get("running"):
            return jsonify({"ok": False, "error": "Jiná operace už probíhá."}), 409
        threading.Thread(target=_check_worker, args=(controller,), daemon=True).start()
        return jsonify({"ok": True})

    @app.post("/api/owut/upgrade")
    def owut_upgrade_start():
        if _snapshot_operation().get("running"):
            return jsonify({"ok": False, "error": "Jiná operace už probíhá."}), 409
        threading.Thread(target=_upgrade_worker, args=(controller, False), daemon=True).start()
        return jsonify({"ok": True})

    @app.post("/api/owut/overlay-setup")
    def owut_overlay_setup():
        data = request.get_json(silent=True) or {}
        if str(data.get("confirm", "")).strip().upper() != "SMAZAT USB":
            return jsonify({"ok": False, "error": "Vyžadováno potvrzení SMAZAT USB."}), 400
        if _snapshot_operation().get("running"):
            return jsonify({"ok": False, "error": "Jiná operace už probíhá."}), 409
        threading.Thread(target=_overlay_setup_worker, args=(controller,), daemon=True).start()
        return jsonify({"ok": True})

    @app.post("/api/owut/reboot")
    def owut_reboot():
        data = request.get_json(silent=True) or {}
        target = str(data.get("target", "all")).strip()
        if _snapshot_operation().get("running"):
            return jsonify({"ok": False, "error": "Jiná operace už probíhá."}), 409
        if target == "all":
            targets = UPDATE_ORDER[:]  # hlavní router poslední
        else:
            found = [x for x in ROUTERS if x[0] == target]
            if not found:
                return jsonify({"ok": False, "error": "Neznámý router."}), 400
            targets = found
        threading.Thread(target=_reboot_worker, args=(controller, targets), daemon=True).start()
        return jsonify({"ok": True})

    threading.Thread(target=_scheduler_loop, args=(controller,), daemon=True, name="owut-scheduler").start()
