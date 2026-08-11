from __future__ import annotations

import copy
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import paramiko
from flask import jsonify

VERSION = "6.0.0"
ROUTERS: List[Tuple[str, str]] = [
    ("192.168.30.1", "ROUTER"),
    ("192.168.30.2", "MESH1"),
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
]
SSH_USER = os.environ.get("MESH_SSH_USER", "root")
SSH_PASS = os.environ.get("MESH_SSH_PASS", "root")
SSH_TIMEOUT = max(2, int(os.environ.get("MESH_SSH_TIMEOUT", "6")))
START_DELAY = max(0, int(os.environ.get("MESH_WIFI_POLICY_START_DELAY", "20")))
RETRY_SECONDS = max(10, int(os.environ.get("MESH_WIFI_POLICY_RETRY_SECONDS", "30")))
MAX_RETRIES = max(1, int(os.environ.get("MESH_WIFI_POLICY_MAX_RETRIES", "20")))
MAX_INACTIVITY = max(30, int(os.environ.get("MESH_WIFI_MAX_INACTIVITY", "60")))
SKIP_INACTIVITY_POLL = os.environ.get("MESH_WIFI_SKIP_INACTIVITY_POLL", "0").strip()
if SKIP_INACTIVITY_POLL not in {"0", "1"}:
    SKIP_INACTIVITY_POLL = "0"

# DŮLEŽITÉ:
# - script vybírá výhradně wifi-iface s mode='ap'
# - mode='mesh' / sta se nikdy nemění
# - uci commit se provede jen při skutečné změně
# - žádný wifi reload / network restart / reboot
POLICY_SCRIPT = r'''set -eu
TARGET_MAX="$1"
TARGET_SKIP="$2"
AP_COUNT=0
CHANGED=0
CHANGED_SECTIONS=''

SECTIONS="$(uci -q show wireless 2>/dev/null | sed -n 's/^wireless\.\([^=]*\)=wifi-iface$/\1/p')"
for SEC in $SECTIONS; do
    MODE="$(uci -q get "wireless.$SEC.mode" 2>/dev/null || true)"
    [ "$MODE" = 'ap' ] || continue
    AP_COUNT=$((AP_COUNT + 1))

    CUR_MAX="$(uci -q get "wireless.$SEC.max_inactivity" 2>/dev/null || true)"
    CUR_SKIP="$(uci -q get "wireless.$SEC.skip_inactivity_poll" 2>/dev/null || true)"
    SEC_CHANGED=0

    if [ "$CUR_MAX" != "$TARGET_MAX" ]; then
        uci set "wireless.$SEC.max_inactivity=$TARGET_MAX"
        SEC_CHANGED=1
    fi
    if [ "$CUR_SKIP" != "$TARGET_SKIP" ]; then
        uci set "wireless.$SEC.skip_inactivity_poll=$TARGET_SKIP"
        SEC_CHANGED=1
    fi

    if [ "$SEC_CHANGED" -eq 1 ]; then
        CHANGED=1
        CHANGED_SECTIONS="$CHANGED_SECTIONS $SEC"
    fi
done

COMMIT=0
if [ "$CHANGED" -eq 1 ]; then
    uci commit wireless
    COMMIT=1
fi

VERIFY_OK=1
for SEC in $SECTIONS; do
    MODE="$(uci -q get "wireless.$SEC.mode" 2>/dev/null || true)"
    [ "$MODE" = 'ap' ] || continue
    VMAX="$(uci -q get "wireless.$SEC.max_inactivity" 2>/dev/null || true)"
    VSKIP="$(uci -q get "wireless.$SEC.skip_inactivity_poll" 2>/dev/null || true)"
    if [ "$VMAX" != "$TARGET_MAX" ] || [ "$VSKIP" != "$TARGET_SKIP" ]; then
        VERIFY_OK=0
    fi
done

printf 'POLICY_VERSION=6.0.0\n'
printf 'AP_COUNT=%s\n' "$AP_COUNT"
printf 'CHANGED=%s\n' "$CHANGED"
printf 'COMMIT=%s\n' "$COMMIT"
printf 'VERIFY_OK=%s\n' "$VERIFY_OK"
printf 'CHANGED_SECTIONS=%s\n' "${CHANGED_SECTIONS# }"
'''


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_kv(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        out[key.strip()] = value.strip()
    return out


class WifiApPolicyManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.thread: Optional[threading.Thread] = None
        self.state: Dict[str, Any] = {
            "version": VERSION,
            "started_at": _utc_now(),
            "finished_at": "",
            "running": False,
            "complete": False,
            "target_max_inactivity": MAX_INACTIVITY,
            "target_skip_inactivity_poll": int(SKIP_INACTIVITY_POLL),
            "routers": {
                ip: {
                    "name": name,
                    "checked": False,
                    "ok": False,
                    "attempts": 0,
                    "ap_count": 0,
                    "changed": False,
                    "commit": False,
                    "verify_ok": False,
                    "changed_sections": [],
                    "checked_at": "",
                    "error": "",
                }
                for ip, name in ROUTERS
            },
        }

    def _connect(self, ip: str) -> paramiko.SSHClient:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: Dict[str, Any] = {
            "hostname": ip,
            "username": SSH_USER,
            "timeout": SSH_TIMEOUT,
            "banner_timeout": SSH_TIMEOUT,
            "auth_timeout": SSH_TIMEOUT,
        }
        if SSH_PASS:
            kwargs.update({"password": SSH_PASS, "look_for_keys": False, "allow_agent": False})
        ssh.connect(**kwargs)
        return ssh

    def _check_router(self, ip: str, name: str) -> Dict[str, Any]:
        ssh: Optional[paramiko.SSHClient] = None
        try:
            ssh = self._connect(ip)
            cmd = "/bin/sh -s -- %s %s" % (MAX_INACTIVITY, SKIP_INACTIVITY_POLL)
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
            stdin.write(POLICY_SCRIPT)
            if not POLICY_SCRIPT.endswith("\n"):
                stdin.write("\n")
            stdin.flush()
            stdin.channel.shutdown_write()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()
            if code != 0:
                raise RuntimeError((err or out).strip() or f"SSH návratový kód {code}")
            values = _parse_kv(out)
            ap_count = int(values.get("AP_COUNT", "0") or 0)
            verify_ok = values.get("VERIFY_OK") == "1"
            if ap_count <= 0:
                raise RuntimeError("Nebyla nalezena žádná wifi-iface s mode=ap")
            if not verify_ok:
                raise RuntimeError("Ověření hodnot po UCI commit selhalo")
            sections = [s for s in values.get("CHANGED_SECTIONS", "").split() if s]
            return {
                "name": name,
                "checked": True,
                "ok": True,
                "ap_count": ap_count,
                "changed": values.get("CHANGED") == "1",
                "commit": values.get("COMMIT") == "1",
                "verify_ok": True,
                "changed_sections": sections,
                "checked_at": _utc_now(),
                "error": "",
            }
        finally:
            if ssh is not None:
                ssh.close()

    def _run(self) -> None:
        with self.lock:
            self.state["running"] = True
            self.state["complete"] = False

        if START_DELAY:
            time.sleep(START_DELAY)

        pending = {ip: name for ip, name in ROUTERS}
        for attempt in range(1, MAX_RETRIES + 1):
            if not pending:
                break

            current = list(pending.items())
            with ThreadPoolExecutor(max_workers=len(current), thread_name_prefix="v600-wifi-policy") as pool:
                futures = {pool.submit(self._check_router, ip, name): (ip, name) for ip, name in current}
                for future in as_completed(futures):
                    ip, name = futures[future]
                    with self.lock:
                        row = self.state["routers"][ip]
                        row["attempts"] = attempt
                    try:
                        result = future.result()
                    except Exception as exc:
                        with self.lock:
                            row = self.state["routers"][ip]
                            row["checked"] = False
                            row["ok"] = False
                            row["error"] = str(exc)
                            row["checked_at"] = _utc_now()
                    else:
                        with self.lock:
                            self.state["routers"][ip].update(result)
                        pending.pop(ip, None)

            if pending and attempt < MAX_RETRIES:
                time.sleep(RETRY_SECONDS)

        with self.lock:
            self.state["running"] = False
            self.state["complete"] = not pending
            self.state["finished_at"] = _utc_now()

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            # Kontrola se spustí přesně jednou za život procesu Controlleru.
            self.thread = threading.Thread(target=self._run, name="mesh-v600-wifi-ap-policy", daemon=True)
            self.thread.start()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.state)


_manager: Optional[WifiApPolicyManager] = None


def init_wifi_ap_policy_v600(app: Any) -> WifiApPolicyManager:
    global _manager
    existing = app.extensions.get("wifi_ap_policy_v600") if hasattr(app, "extensions") else None
    if existing is not None:
        return existing
    if _manager is None:
        _manager = WifiApPolicyManager()
    manager = _manager
    app.extensions["wifi_ap_policy_v600"] = manager

    endpoint = "wifi_ap_policy_v600_status"
    if endpoint not in app.view_functions:
        @app.get("/api/v600/wifi-ap-policy", endpoint=endpoint)
        def _status():
            return jsonify(manager.snapshot())

    manager.start()
    return manager
