from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import paramiko
from flask import jsonify

MAIN_IP = os.environ.get("MESH_MAIN_IP", "192.168.30.1")
SSH_USER = os.environ.get("MESH_SSH_USER", "root")
SSH_PASS = os.environ.get("MESH_SSH_PASS", "root")
SSH_TIMEOUT = int(os.environ.get("MESH_SSH_TIMEOUT", "6"))
DATA_FILE = Path(os.environ.get("WAN_USAGE_FILE", "/data/wan_usage.json"))
POLL_SECONDS = max(10, int(os.environ.get("WAN_USAGE_POLL_SECONDS", "30")))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WanUsageCollector:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.state: Dict[str, Any] = {
            "version": 1,
            "total_rx_bytes": 0,
            "total_tx_bytes": 0,
            "last_rx_bytes": None,
            "last_tx_bytes": None,
            "last_boot_id": "",
            "last_device": "",
            "started_at": _utc_now(),
            "updated_at": "",
            "status": "starting",
            "error": "",
        }
        self._load()

    def _load(self) -> None:
        try:
            if DATA_FILE.exists():
                raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key in self.state:
                        if key in raw:
                            self.state[key] = raw[key]
                    # Celkové čítače nikdy nesmí být záporné.
                    self.state["total_rx_bytes"] = max(0, int(self.state.get("total_rx_bytes") or 0))
                    self.state["total_tx_bytes"] = max(0, int(self.state.get("total_tx_bytes") or 0))
        except Exception as exc:
            self.state["status"] = "error"
            self.state["error"] = f"Načtení {DATA_FILE}: {exc}"

    def _save(self) -> None:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_suffix(DATA_FILE.suffix + ".tmp")
        payload = json.dumps(self.state, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, DATA_FILE)
        try:
            os.chmod(DATA_FILE, 0o600)
        except OSError:
            pass

    @staticmethod
    def _parse_kv(output: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for line in output.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
        return result

    def _read_router_counters(self) -> Tuple[str, str, int, int]:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: Dict[str, Any] = {
            "hostname": MAIN_IP,
            "username": SSH_USER,
            "timeout": SSH_TIMEOUT,
            "banner_timeout": SSH_TIMEOUT,
            "auth_timeout": SSH_TIMEOUT,
        }
        if SSH_PASS:
            kwargs.update({
                "password": SSH_PASS,
                "look_for_keys": False,
                "allow_agent": False,
            })
        try:
            ssh.connect(**kwargs)
            command = r'''set -eu
STATUS="$(ubus call network.interface.wan status 2>/dev/null || true)"
DEV=""
if command -v jsonfilter >/dev/null 2>&1; then
    DEV="$(printf '%s' "$STATUS" | jsonfilter -e '@.l3_device' 2>/dev/null || true)"
    [ -n "$DEV" ] || DEV="$(printf '%s' "$STATUS" | jsonfilter -e '@.device' 2>/dev/null || true)"
fi
[ -n "$DEV" ] || DEV="$(ifstatus wan 2>/dev/null | sed -n 's/.*"l3_device"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
[ -n "$DEV" ] || { echo 'WAN_DEVICE_NOT_FOUND' >&2; exit 21; }
RX="$(cat "/sys/class/net/$DEV/statistics/rx_bytes" 2>/dev/null || true)"
TX="$(cat "/sys/class/net/$DEV/statistics/tx_bytes" 2>/dev/null || true)"
BOOT="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || cat /proc/uptime 2>/dev/null | awk '{print $1}')"
case "$RX" in ''|*[!0-9]*) echo 'INVALID_RX_COUNTER' >&2; exit 22;; esac
case "$TX" in ''|*[!0-9]*) echo 'INVALID_TX_COUNTER' >&2; exit 23;; esac
printf 'WAN_DEVICE=%s\nBOOT_ID=%s\nRX_BYTES=%s\nTX_BYTES=%s\n' "$DEV" "$BOOT" "$RX" "$TX"
'''
            _stdin, stdout, stderr = ssh.exec_command(command, timeout=12)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()
            if code != 0:
                raise RuntimeError((err or out).strip() or f"SSH návratový kód {code}")
            values = self._parse_kv(out)
            device = values.get("WAN_DEVICE", "")
            boot_id = values.get("BOOT_ID", "")
            rx = int(values["RX_BYTES"])
            tx = int(values["TX_BYTES"])
            if not device:
                raise RuntimeError("WAN zařízení nebylo zjištěno")
            return device, boot_id, rx, tx
        finally:
            ssh.close()

    def sample(self) -> None:
        try:
            device, boot_id, rx, tx = self._read_router_counters()
            with self.lock:
                last_rx = self.state.get("last_rx_bytes")
                last_tx = self.state.get("last_tx_bytes")
                same_source = (
                    last_rx is not None
                    and last_tx is not None
                    and self.state.get("last_device") == device
                    and self.state.get("last_boot_id") == boot_id
                )

                if same_source:
                    last_rx_i = int(last_rx)
                    last_tx_i = int(last_tx)
                    # Při neočekávaném resetu čítače pouze vytvoříme nový baseline.
                    if rx >= last_rx_i:
                        self.state["total_rx_bytes"] = int(self.state.get("total_rx_bytes") or 0) + (rx - last_rx_i)
                    if tx >= last_tx_i:
                        self.state["total_tx_bytes"] = int(self.state.get("total_tx_bytes") or 0) + (tx - last_tx_i)

                self.state["last_rx_bytes"] = rx
                self.state["last_tx_bytes"] = tx
                self.state["last_device"] = device
                self.state["last_boot_id"] = boot_id
                self.state["updated_at"] = _utc_now()
                self.state["status"] = "ok"
                self.state["error"] = ""
                self._save()
        except Exception as exc:
            with self.lock:
                self.state["status"] = "error"
                self.state["error"] = str(exc)
                self.state["updated_at"] = _utc_now()
                # Chyba spojení nesmí vynulovat dosud nasčítaná data.
                try:
                    self._save()
                except Exception:
                    pass

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.state)

    def _loop(self) -> None:
        # První baseline se vezme hned po startu kontejneru.
        self.sample()
        while not self.stop_event.wait(POLL_SECONDS):
            self.sample()

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, name="wan-usage", daemon=True)
            self.thread.start()


_collector: Optional[WanUsageCollector] = None


def init_wan_usage(app: Any) -> WanUsageCollector:
    """Zaregistruje persistentní WAN čítač a API. Volání je idempotentní."""
    global _collector
    existing = app.extensions.get("wan_usage") if hasattr(app, "extensions") else None
    if existing is not None:
        return existing

    if _collector is None:
        _collector = WanUsageCollector()
    collector = _collector
    app.extensions["wan_usage"] = collector

    endpoint_name = "wan_usage_api_v389"
    if endpoint_name not in app.view_functions:
        @app.get("/api/wan-usage", endpoint=endpoint_name)
        def _wan_usage_api():
            state = collector.snapshot()
            return jsonify({
                "ok": state.get("status") == "ok",
                "status": state.get("status", "unknown"),
                "download_bytes": int(state.get("total_rx_bytes") or 0),
                "upload_bytes": int(state.get("total_tx_bytes") or 0),
                "wan_device": state.get("last_device", ""),
                "started_at": state.get("started_at", ""),
                "updated_at": state.get("updated_at", ""),
                "error": state.get("error", ""),
            })

    collector.start()
    return collector
