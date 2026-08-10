from __future__ import annotations

import html
import json
import os
import re
import shlex
import smtplib
import ssl
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "schedule_mode": "weekly", # daily = každý den, weekly = vybraný den
    "weekday": 6,              # 0 = pondělí ... 6 = neděle; -1 = zpětná kompatibilita pro každý den
    "time": "03:00",
    "gmail_from": "",
    "gmail_to": "",
    "gmail_app_password": "",
    "mail_report_format": "html",
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

_upgrade_summary_lock = threading.RLock()
_last_upgrade_summary: Dict[str, Any] = {}


def _store_upgrade_summary(run_id: str, automatic: bool, overall_ok: bool, rows: List[Dict[str, Any]], backup_id: str, extra: str) -> None:
    global _last_upgrade_summary
    with _upgrade_summary_lock:
        _last_upgrade_summary = {
            "run_id": str(run_id or ""),
            "automatic": bool(automatic),
            "overall_ok": bool(overall_ok),
            "rows": json.loads(json.dumps(rows, ensure_ascii=False)),
            "backup_id": str(backup_id or ""),
            "extra": str(extra or ""),
            "finished": _now_text(),
        }


def _get_upgrade_summary(run_id: str) -> Dict[str, Any]:
    with _upgrade_summary_lock:
        data = json.loads(json.dumps(_last_upgrade_summary, ensure_ascii=False))
    if str(data.get("run_id") or "") != str(run_id or ""):
        return {}
    return data


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
    # Zpětná kompatibilita: staré nastavení používalo weekday=-1 pro každý den.
    mode = str(out.get("schedule_mode") or "").strip().lower()
    try:
        wd = int(out.get("weekday", 6))
    except Exception:
        wd = 6
    if mode not in {"daily", "weekly"}:
        mode = "daily" if wd == -1 else "weekly"
    out["schedule_mode"] = mode
    if mode == "daily":
        out["weekday"] = -1
    elif not 0 <= wd <= 6:
        out["weekday"] = 6
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


def _normalize_temp(raw: str) -> Optional[float]:
    try:
        value = float(str(raw).strip())
    except Exception:
        return None
    if abs(value) >= 1000:
        value /= 1000.0
    if not (-20.0 <= value <= 150.0):
        return None
    return round(value, 1)


def _pick_temperature(candidates: List[Tuple[str, float]]) -> Optional[float]:
    if not candidates:
        return None

    def score(item: Tuple[str, float]) -> Tuple[int, float]:
        label, value = item
        low = label.lower()
        rank = 0
        for token, points in (("cpu", 100), ("soc", 90), ("package", 80), ("core", 70), ("thermal", 50)):
            if token in low:
                rank = max(rank, points)
        return rank, value

    return max(candidates, key=score)[1]


def _router_temperature(controller, ip: str) -> Optional[float]:
    cmd = """for z in /sys/class/thermal/thermal_zone*; do
  [ -r "$z/temp" ] || continue
  ty="$(cat "$z/type" 2>/dev/null || basename "$z")"
  tv="$(cat "$z/temp" 2>/dev/null)"
  printf 'T\t%s\t%s\n' "$ty" "$tv"
done
for h in /sys/class/hwmon/hwmon*/temp*_input; do
  [ -r "$h" ] || continue
  base="${h%_input}"
  label="$(cat "${base}_label" 2>/dev/null || basename "$h")"
  tv="$(cat "$h" 2>/dev/null)"
  printf 'H\t%s\t%s\n' "$label" "$tv"
done"""
    try:
        out, _err, code = _ssh_exec(controller, ip, cmd, 8)
        if code not in (0, None):
            return None
        candidates: List[Tuple[str, float]] = []
        for line in str(out or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            value = _normalize_temp(parts[2])
            if value is not None:
                candidates.append((parts[1], value))
        return _pick_temperature(candidates)
    except Exception:
        return None


def _ihost_temperature() -> Optional[float]:
    candidates: List[Tuple[str, float]] = []
    try:
        thermal = Path("/sys/class/thermal")
        if thermal.exists():
            for zone in thermal.glob("thermal_zone*"):
                try:
                    temp_path = zone / "temp"
                    if not temp_path.exists():
                        continue
                    type_path = zone / "type"
                    label = type_path.read_text(encoding="utf-8", errors="ignore").strip() if type_path.exists() else zone.name
                    value = _normalize_temp(temp_path.read_text(encoding="utf-8", errors="ignore"))
                    if value is not None:
                        candidates.append((label, value))
                except Exception:
                    pass
        hwmon = Path("/sys/class/hwmon")
        if hwmon.exists():
            for inp in hwmon.glob("hwmon*/temp*_input"):
                try:
                    base = str(inp)[:-6]
                    label_path = Path(base + "_label")
                    label = label_path.read_text(encoding="utf-8", errors="ignore").strip() if label_path.exists() else inp.name
                    value = _normalize_temp(inp.read_text(encoding="utf-8", errors="ignore"))
                    if value is not None:
                        candidates.append((label, value))
                except Exception:
                    pass
    except Exception:
        pass
    return _pick_temperature(candidates)


def _collect_temperatures(controller) -> Dict[str, Any]:
    router_temps: Dict[str, Optional[float]] = {ip: None for ip, _ in ROUTERS}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_router_temperature, controller, ip): ip for ip, _ in ROUTERS}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                router_temps[ip] = future.result()
            except Exception:
                router_temps[ip] = None
    return {"routers": router_temps, "ihost": _ihost_temperature()}


def _temp_text(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    if abs(value - round(value)) < 0.05:
        return f"{int(round(value))} °C"
    return f"{value:.1f} °C"


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


def _save_pending_mail(subject: str, text_body: str, html_body: str = "") -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "subject": subject,
        "body": text_body,
        "text_body": text_body,
        "html_body": html_body,
        "created": _now_text(),
    }
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
        text_body = str(data.get("text_body") or data.get("body") or "")
        html_body = str(data.get("html_body") or "")
    except Exception as exc:
        return False, f"Čekající report nelze načíst: {exc}"
    ok, detail = _send_gmail(subject, text_body, html_body)
    if ok:
        try:
            PENDING_MAIL_FILE.unlink()
        except FileNotFoundError:
            pass
    return ok, detail


def _send_report_or_queue(subject: str, text_body: str, html_body: str = "") -> Tuple[bool, str]:
    ok, detail = _send_gmail(subject, text_body, html_body)
    if ok:
        try:
            PENDING_MAIL_FILE.unlink()
        except FileNotFoundError:
            pass
        return True, detail
    try:
        _save_pending_mail(subject, text_body, html_body)
        return False, f"{detail} Report uložen do /data a bude automaticky odeslán později."
    except Exception as exc:
        return False, f"{detail} Navíc se nepodařilo uložit čekající report: {exc}"


def _send_gmail(subject: str, text_body: str, html_body: str = "") -> Tuple[bool, str]:
    settings = _load_settings()
    sender = str(settings.get("gmail_from") or "").strip()
    recipient = str(settings.get("gmail_to") or "").strip()
    password = str(settings.get("gmail_app_password") or "").replace(" ", "")
    if not sender or not recipient or not password:
        return False, "Gmail není kompletně nastavený."

    report_format = str(settings.get("mail_report_format") or "html").strip().lower()
    if report_format not in {"html", "text"}:
        report_format = "html"

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(text_body or "OpenWRT MESH CONTROLLER PRO")
    if report_format == "html" and html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
        return True, "E-mail odeslán."
    except Exception as exc:
        return False, str(exc)


def _build_report_text(
    kind: str,
    ok: bool,
    rows: List[Dict[str, Any]],
    backup_id: str = "",
    extra: str = "",
    temperatures: Optional[Dict[str, Any]] = None,
) -> str:
    temps = temperatures or {}
    router_temps = temps.get("routers") or {}
    lines = [
        "OpenWRT MESH CONTROLLER PRO",
        "",
        f"Operace: {kind}",
        f"Datum: {_now_text()}",
    ]
    if backup_id:
        lines.append(f"Záloha: {backup_id}")

    lines.extend(["", "TEPLOTY CPU:"])
    for ip, label in ROUTERS:
        lines.append(f"{label:<8} {ip:<15} {_temp_text(router_temps.get(ip))}")
    lines.append(f"iHost                    {_temp_text(temps.get('ihost'))}")

    lines.extend(["", "STAV ROUTERŮ:"])
    for row in rows:
        status = "OK" if row.get("ok") else "CHYBA"
        ip = str(row.get("ip") or "")
        lines.append(f"{row.get('name', ''):<8} {ip:<15} {status} | CPU {_temp_text(router_temps.get(ip))}")
        detail = str(row.get("detail") or row.get("error") or "").strip()
        if detail:
            detail = " ".join(detail.split())
            if len(detail) > 500:
                detail = detail[:500] + "…"
            lines.append(f"  {detail}")
    if extra:
        lines.extend(["", extra])
    lines.extend(["", f"VÝSLEDEK: {'VŠE V POŘÁDKU' if ok else 'CHYBA / NEDOKONČENO'}"])
    return "\\n".join(lines)


def _build_report_html(
    kind: str,
    ok: bool,
    rows: List[Dict[str, Any]],
    backup_id: str = "",
    extra: str = "",
    temperatures: Optional[Dict[str, Any]] = None,
) -> str:
    completed = sum(1 for row in rows if row.get("ok"))
    total = 5
    color = "#16a34a" if ok else "#dc2626"
    result_title = "VÝSLEDEK: VŠE V POŘÁDKU" if ok else "VÝSLEDEK: CHYBA / NEDOKONČENO"
    result_icon = "✓" if ok else "✕"
    by_ip = {str(row.get("ip") or ""): row for row in rows}
    temps = temperatures or {}
    router_temps = temps.get("routers") or {}
    ihost_temp = temps.get("ihost")

    cards = []
    for ip, fallback_name in ROUTERS:
        row = by_ip.get(ip)
        if row:
            row_ok = bool(row.get("ok"))
            status = "HOTOVO" if row_ok else "CHYBA"
            status_color = "#15803d" if row_ok else "#dc2626"
            mark = "✓" if row_ok else "✕"
            name = html.escape(str(row.get("name") or fallback_name))
            detail = " ".join(str(row.get("detail") or row.get("error") or "").split())
        else:
            status = "NEPROVEDENO"
            status_color = "#64748b"
            mark = "—"
            name = html.escape(fallback_name)
            detail = ""
        if len(detail) > 130:
            detail = detail[:130] + "…"
        cards.append(
            '<td style="width:20%;padding:5px;vertical-align:top;">'
            '<div style="border:1px solid #d7dde5;border-radius:10px;padding:12px 10px;background:#ffffff;min-height:128px;font-family:Arial,sans-serif;">'
            f'<div style="font-size:15px;font-weight:700;color:#111827;">{name}</div>'
            f'<div style="font-size:12px;color:#475569;margin:3px 0 10px;">{html.escape(ip)}</div>'
            f'<div style="display:inline-block;padding:5px 9px;border-radius:999px;background:#f8fafc;color:{status_color};font-size:11px;font-weight:700;">{mark} {status}</div>'
            f'<div style="font-size:11px;color:#334155;margin-top:9px;"><b>CPU:</b> {html.escape(_temp_text(router_temps.get(ip)))}</div>'
            f'<div style="font-size:10px;line-height:1.35;color:#64748b;margin-top:7px;">{html.escape(detail) if detail else "&nbsp;"}</div>'
            '</div></td>'
        )

    note = ""
    if extra:
        note_bg = "#f0fdf4" if ok else "#fef2f2"
        note_border = "#bbf7d0" if ok else "#fecaca"
        note_color = "#166534" if ok else "#991b1b"
        note_title = "Poznámka" if ok else "Důvod / detail"
        note = (
            '<tr><td style="padding:0 24px 22px;">'
            f'<div style="border:1px solid {note_border};background:{note_bg};border-radius:9px;padding:12px 14px;color:{note_color};font-family:Arial,sans-serif;font-size:13px;line-height:1.45;">'
            f'<strong>{note_title}</strong><br>{html.escape(str(extra))}</div></td></tr>'
        )

    backup = html.escape(backup_id) if backup_id else "—"
    success = round(100 * completed / total)
    return f'''<!doctype html>
<html><body style="margin:0;padding:0;background:#f3f6f9;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f3f6f9;padding:20px 8px;"><tr><td align="center">
<table role="presentation" width="760" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:760px;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #dce3ea;">
<tr><td style="background:#071a2d;padding:20px 24px;color:#ffffff;font-family:Arial,sans-serif;"><div style="font-size:20px;font-weight:700;">◉ OpenWRT MESH CONTROLLER PRO</div><div style="font-size:12px;color:#cbd5e1;margin-top:4px;">{html.escape(kind)}</div></td></tr>
<tr><td style="padding:18px 20px 10px;"><div style="background:{color};border-radius:10px;padding:17px 20px;color:white;font-family:Arial,sans-serif;"><div style="font-size:20px;font-weight:700;">{result_icon} &nbsp;{result_title}</div><div style="font-size:13px;margin-top:5px;">{completed} / {total} routerů úspěšně dokončeno &nbsp; • &nbsp; {_now_text()}</div></div></td></tr>
<tr><td style="padding:10px 20px 4px;font-family:Arial,sans-serif;font-size:15px;font-weight:700;color:#1f2937;">STAV ROUTERŮ + CPU</td></tr>
<tr><td style="padding:2px 15px 14px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>{''.join(cards)}</tr></table></td></tr>
<tr><td style="padding:0 20px 14px;"><div style="border:1px solid #bae6fd;background:#f0f9ff;border-radius:9px;padding:11px 14px;font-family:Arial,sans-serif;color:#0c4a6e;font-size:13px;"><b>iHost CPU / SoC:</b> {html.escape(_temp_text(ihost_temp))}</div></td></tr>
<tr><td style="padding:0 20px 18px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="border:1px solid #e5e7eb;background:#f8fafc;font-family:Arial,sans-serif;"><tr>
<td style="width:33.33%;padding:10px;text-align:center;border-right:1px solid #e5e7eb;"><div style="font-size:11px;color:#64748b;">Operace</div><div style="font-size:13px;font-weight:700;color:#111827;margin-top:3px;">{html.escape(kind)}</div></td>
<td style="width:33.33%;padding:10px;text-align:center;border-right:1px solid #e5e7eb;"><div style="font-size:11px;color:#64748b;">Záloha</div><div style="font-size:13px;font-weight:700;color:#111827;margin-top:3px;">{backup}</div></td>
<td style="width:33.33%;padding:10px;text-align:center;"><div style="font-size:11px;color:#64748b;">Úspěšnost</div><div style="font-size:13px;font-weight:700;color:{color};margin-top:3px;">{success} %</div></td>
</tr></table></td></tr>
{note}
<tr><td style="background:#071a2d;padding:13px 24px;color:#cbd5e1;font-family:Arial,sans-serif;font-size:10px;">OpenWRT MESH CONTROLLER PRO &nbsp; • &nbsp; Tento e-mail byl odeslán automaticky.</td></tr>
</table></td></tr></table></body></html>'''


def _build_test_email(controller) -> Tuple[str, str]:
    now = _now_text()
    temperatures = _collect_temperatures(controller)
    router_temps = temperatures.get("routers") or {}
    ihost_temp = temperatures.get("ihost")
    temp_lines = "\\n".join(f"{label}: {_temp_text(router_temps.get(ip))}" for ip, label in ROUTERS)
    text_body = (
        "OpenWRT MESH CONTROLLER PRO\\n\\nTESTOVACÍ E-MAIL\\n"
        f"Datum: {now}\\n\\nSMTP komunikace funguje a nastavení e-mailu je v pořádku.\\n\\n"
        f"TEPLOTY CPU:\\n{temp_lines}\\niHost: {_temp_text(ihost_temp)}"
    )
    html_temp_rows = "<br>".join(
        html.escape(f"{label}: {_temp_text(router_temps.get(ip))}") for ip, label in ROUTERS
    )
    html_body = f'''<!doctype html><html><body style="margin:0;background:#f3f6f9;padding:20px 8px;">
<table role="presentation" width="100%"><tr><td align="center"><table role="presentation" width="620" style="width:100%;max-width:620px;background:#fff;border:1px solid #dce3ea;border-radius:14px;overflow:hidden;border-spacing:0;">
<tr><td style="background:#071a2d;padding:20px 24px;color:white;font-family:Arial,sans-serif;"><b style="font-size:19px;">◉ OpenWRT MESH CONTROLLER PRO</b><div style="font-size:12px;color:#cbd5e1;margin-top:4px;">Test nastavení Gmailu</div></td></tr>
<tr><td style="padding:18px 20px;"><div style="background:#1267c4;color:white;border-radius:10px;padding:16px 18px;font-family:Arial,sans-serif;"><b style="font-size:19px;">✉ &nbsp; TESTOVACÍ E-MAIL</b><div style="font-size:12px;margin-top:5px;">Nastavení e-mailu je v pořádku</div></div></td></tr>
<tr><td style="padding:10px 28px 28px;text-align:center;font-family:Arial,sans-serif;color:#1f2937;"><div style="font-size:44px;color:#1267c4;">✉</div><div style="font-size:15px;font-weight:700;margin:8px 0;">OpenWRT MESH CONTROLLER PRO</div><div style="font-size:13px;line-height:1.5;color:#475569;">Testovací zpráva byla úspěšně vytvořena.<br>SMTP komunikace s Gmailem funguje.</div><div style="margin-top:18px;border:1px solid #bfdbfe;background:#eff6ff;border-radius:9px;padding:11px;font-size:12px;color:#1e3a8a;text-align:left;"><b>Detaily testu</b><br>Datum: {html.escape(now)}<br>Výsledek: ÚSPĚCH</div><div style="margin-top:10px;border:1px solid #d7dde5;background:#f8fafc;border-radius:9px;padding:11px;font-size:12px;color:#334155;text-align:left;"><b>Teploty CPU</b><br>{html_temp_rows}<br><b>iHost: {html.escape(_temp_text(ihost_temp))}</b></div></td></tr>
<tr><td style="background:#071a2d;padding:12px 20px;color:#cbd5e1;font-family:Arial,sans-serif;font-size:10px;">OpenWRT MESH CONTROLLER PRO</td></tr>
</table></td></tr></table></body></html>'''
    return text_body, html_body


def _deliver_upgrade_report_safe(
    controller,
    automatic: bool,
    overall_ok: bool,
    rows: List[Dict[str, Any]],
    backup_id: str,
    extra: str,
) -> Tuple[bool, str]:
    """Vždy se pokusí vytvořit a doručit report.

    Chyba měření teplot nebo HTML renderu nesmí zabránit odeslání e-mailu.
    Pokud selže grafický report, vytvoří se minimální textová varianta.
    """
    report_kind = "AUTOMATICKÝ OWUT SYSUPGRADE" if automatic else "RUČNÍ OWUT SYSUPGRADE"
    subject = f"{'OK' if overall_ok else 'CHYBA'} – OpenWRT MESH OWUT aktualizace"
    try:
        _op_log("Měřím aktuální CPU teploty pro report…")
        temperatures = _collect_temperatures(controller)
    except Exception as exc:
        temperatures = {"routers": {}, "ihost": None}
        _op_log(f"Teploty pro report se nepodařilo načíst: {exc}")

    try:
        report_text = _build_report_text(report_kind, overall_ok, rows, backup_id, extra, temperatures)
    except Exception as exc:
        report_text = (
            "OpenWRT MESH CONTROLLER PRO\n\n"
            f"Operace: {report_kind}\n"
            f"Datum: {_now_text()}\n"
            f"Výsledek: {'OK' if overall_ok else 'CHYBA / NEDOKONČENO'}\n"
            f"Detail: {extra or 'Bez detailu'}\n\n"
            f"Poznámka: plný textový report se nepodařilo vytvořit ({exc})."
        )
        _op_log(f"Textový report byl vytvořen v nouzovém režimu: {exc}")

    try:
        report_html = _build_report_html(report_kind, overall_ok, rows, backup_id, extra, temperatures)
    except Exception as exc:
        report_html = ""
        _op_log(f"HTML report se nepodařilo vytvořit, použiji TEXT: {exc}")

    try:
        ok, detail = _send_report_or_queue(subject, report_text, report_html)
        return ok, detail
    except Exception as exc:
        # Poslední záchrana: report uložit do pending souboru, aby ho retry loop
        # mohl zkusit odeslat po obnovení konektivity.
        try:
            _save_pending_mail(subject, report_text, report_html)
            return False, f"Odeslání reportu selhalo ({exc}); report byl uložen do fronty."
        except Exception as queue_exc:
            return False, f"Odeslání reportu selhalo ({exc}); uložení do fronty selhalo ({queue_exc})."


def _upgrade_worker(controller, automatic: bool = False, send_report: bool = True, run_id: str = "") -> None:
    if _snapshot_operation().get("running"):
        # U plánované operace uložíme i stav SKIPPED, aby wrapper mohl poslat report.
        if run_id:
            _store_upgrade_summary(run_id, automatic, False, [], "", "Plánovaná aktualizace nebyla spuštěna, protože už probíhala jiná operace.")
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
        _store_upgrade_summary(run_id, automatic, overall_ok, rows, backup_id, extra)
        if send_report:
            mail_ok, mail_detail = _deliver_upgrade_report_safe(
                controller, automatic, overall_ok, rows, backup_id, extra
            )
            _op_log(f"Gmail report: {'odeslán' if mail_ok else 'neodeslán'} – {mail_detail}")
            if automatic:
                try:
                    settings = _load_settings()
                    settings["last_auto_result"] = "ok" if overall_ok else "error"
                    settings["last_auto_mail_ok"] = bool(mail_ok)
                    settings["last_auto_mail_detail"] = str(mail_detail)[:500]
                    settings["last_auto_finished"] = _now_text()
                    _save_settings(settings)
                except Exception:
                    pass


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


def _scheduled_upgrade_worker(controller, run_id: str) -> None:
    """Plánovaná cesta: OWUT a e-mail jsou dvě oddělené fáze.

    Tím se automatický report neposílá z vnitřku upgrade workeru, ale až po jeho
    úplném návratu. Ruční aktualizace používá původní přímou cestu.
    """
    mail_ok = False
    mail_detail = "Report nebyl odeslán."
    try:
        _upgrade_worker(controller, automatic=True, send_report=False, run_id=run_id)
        summary = _get_upgrade_summary(run_id)
        if not summary:
            summary = {
                "overall_ok": False,
                "rows": [],
                "backup_id": "",
                "extra": "Plánovaná aktualizace skončila bez dostupného výsledku.",
            }
        mail_ok, mail_detail = _deliver_upgrade_report_safe(
            controller,
            True,
            bool(summary.get("overall_ok")),
            list(summary.get("rows") or []),
            str(summary.get("backup_id") or ""),
            str(summary.get("extra") or ""),
        )
        _op_log(f"Automatický Gmail report: {'odeslán' if mail_ok else 'neodeslán'} – {mail_detail}")
    except Exception as exc:
        # Ani neočekávaná chyba wrapperu nesmí report úplně ztratit.
        fallback = (
            "OpenWRT MESH CONTROLLER PRO\n\n"
            "AUTOMATICKÁ OWUT AKTUALIZACE\n"
            f"Datum: {_now_text()}\n"
            "Výsledek: CHYBA / NEDOKONČENO\n"
            f"Detail scheduleru: {exc}"
        )
        try:
            mail_ok, mail_detail = _send_report_or_queue(
                "CHYBA – OpenWRT MESH plánovaná aktualizace", fallback, ""
            )
        except Exception as mail_exc:
            mail_ok = False
            mail_detail = f"{exc}; navíc selhalo odeslání reportu: {mail_exc}"
    finally:
        try:
            settings = _load_settings()
            summary = _get_upgrade_summary(run_id)
            settings["last_auto_result"] = "ok" if summary.get("overall_ok") else "error"
            settings["last_auto_mail_ok"] = bool(mail_ok)
            settings["last_auto_mail_detail"] = str(mail_detail)[:500]
            settings["last_auto_finished"] = _now_text()
            settings["last_auto_run_id"] = run_id
            _save_settings(settings)
        except Exception:
            pass


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
                try:
                    weekday = int(settings.get("weekday", 6))
                except Exception:
                    weekday = 6
                mode = str(settings.get("schedule_mode") or "").strip().lower()
                if mode not in {"daily", "weekly"}:
                    mode = "daily" if weekday == -1 else "weekly"
                today = now.strftime("%Y-%m-%d")
                day_matches = True if mode == "daily" else now.weekday() == weekday
                scheduled_minute = hh * 60 + mm
                current_minute = now.hour * 60 + now.minute
                # Pětiminutové okno zabrání vynechání úlohy, když scheduler právě
                # v přesné minutě dokončuje retry e-mailu nebo jinou krátkou práci.
                due = day_matches and scheduled_minute <= current_minute < scheduled_minute + 5
                if due and settings.get("last_auto_date") != today and not _snapshot_operation().get("running"):
                    run_id = now.strftime("%Y%m%d-%H%M%S")
                    settings["last_auto_date"] = today
                    settings["last_auto_started"] = _now_text()
                    settings["last_auto_run_id"] = run_id
                    settings["last_auto_mail_ok"] = None
                    settings["last_auto_mail_detail"] = "Čekám na dokončení plánované aktualizace."
                    _save_settings(settings)
                    threading.Thread(
                        target=_scheduled_upgrade_worker,
                        args=(controller, run_id),
                        daemon=True,
                        name="owut-auto-upgrade",
                    ).start()
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
        old_auto_enabled = bool(data.get("auto_enabled", False))
        old_schedule_mode = str(data.get("schedule_mode") or "weekly")
        old_weekday = int(data.get("weekday", 6)) if str(data.get("weekday", 6)).lstrip("-").isdigit() else 6
        old_time = str(data.get("time") or "03:00")
        data["auto_enabled"] = bool(incoming.get("auto_enabled", False))
        mode = str(incoming.get("schedule_mode", data.get("schedule_mode", "weekly"))).strip().lower()
        if mode not in {"daily", "weekly"}:
            mode = "weekly"
        data["schedule_mode"] = mode
        try:
            wd = int(incoming.get("weekday", data.get("weekday", 6)))
        except Exception:
            wd = 6
        if mode == "daily":
            data["weekday"] = -1
        else:
            data["weekday"] = wd if 0 <= wd <= 6 else 6
        tm = str(incoming.get("time", data.get("time", "03:00"))).strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", tm):
            return jsonify({"ok": False, "error": "Čas musí být HH:MM."}), 400
        data["time"] = tm
        data["gmail_from"] = str(incoming.get("gmail_from", data.get("gmail_from", ""))).strip()
        data["gmail_to"] = str(incoming.get("gmail_to", data.get("gmail_to", ""))).strip()
        report_format = str(incoming.get("mail_report_format", data.get("mail_report_format", "html"))).strip().lower()
        if report_format not in {"html", "text"}:
            return jsonify({"ok": False, "error": "MAIL REPORT musí být HTML nebo TEXT."}), 400
        data["mail_report_format"] = report_format
        password = str(incoming.get("gmail_app_password", ""))
        if password.strip():
            data["gmail_app_password"] = password.strip()
        if incoming.get("clear_gmail_password"):
            data["gmail_app_password"] = ""
        if data.get("auto_enabled"):
            if not str(data.get("gmail_from") or "").strip() or not str(data.get("gmail_to") or "").strip() or not str(data.get("gmail_app_password") or "").strip():
                return jsonify({"ok": False, "error": "Pro automatickou aktualizaci nastav Gmail odesílatele, příjemce a heslo aplikace."}), 400

        # Změna plánování nebo nové zapnutí automatiky odemkne dnešní běh.
        # Gmail/HTML nastavení samo o sobě nový OWUT běh nevyvolá.
        schedule_changed = (
            old_schedule_mode != str(data.get("schedule_mode") or "weekly")
            or old_weekday != int(data.get("weekday", 6))
            or old_time != str(data.get("time") or "03:00")
            or (not old_auto_enabled and bool(data.get("auto_enabled")))
        )
        if schedule_changed:
            data["last_auto_date"] = ""
            data["last_auto_started"] = ""
            data["last_auto_finished"] = ""
            data["last_auto_mail_ok"] = None
            data["last_auto_mail_detail"] = "Plán změněn – čekám na další plánovaný běh."

        _save_settings(data)
        return jsonify({"ok": True, "settings": _public_settings(data)})

    @app.post("/api/owut/test-email")
    def owut_test_email():
        text_body, html_body = _build_test_email(controller)
        ok, detail = _send_gmail(
            "TEST – OpenWRT MESH CONTROLLER PRO",
            text_body,
            html_body,
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
