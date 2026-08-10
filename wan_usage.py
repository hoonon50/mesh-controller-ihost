from __future__ import annotations

import atexit
import copy
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

import paramiko
from flask import jsonify

MAIN_IP = os.environ.get("MESH_MAIN_IP", "192.168.30.1")
SSH_USER = os.environ.get("MESH_SSH_USER", "root")
SSH_PASS = os.environ.get("MESH_SSH_PASS", "root")
SSH_TIMEOUT = int(os.environ.get("MESH_SSH_TIMEOUT", "6"))
DATA_FILE = Path(os.environ.get("WAN_USAGE_FILE", "/data/wan_usage.json"))
POLL_SECONDS = max(10, int(os.environ.get("WAN_USAGE_POLL_SECONDS", "30")))
SAVE_SECONDS = max(300, int(os.environ.get("WAN_USAGE_SAVE_SECONDS", "3600")))
LOCAL_TZ_NAME = os.environ.get("WAN_USAGE_TIMEZONE", "Europe/Prague")
try:
    LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)
except Exception:
    LOCAL_TZ = timezone.utc


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _year_month() -> Tuple[str, str]:
    now = _local_now()
    return f"{now.year:04d}", f"{now.month:02d}"


def _empty_bucket() -> Dict[str, int]:
    return {"rx_bytes": 0, "tx_bytes": 0}


class WanUsageCollector:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.state: Dict[str, Any] = {
            "version": 2,
            "total_rx_bytes": 0,
            "total_tx_bytes": 0,
            "last_rx_bytes": None,
            "last_tx_bytes": None,
            "last_boot_id": "",
            "last_device": "",
            "started_at": _utc_now(),
            "updated_at": "",
            "persisted_at": "",
            "status": "starting",
            "error": "",
            "history_initialized": False,
            "history_started_at": "",
            "history": {},
        }
        self._dirty = False
        self._migration_needed = False
        self._last_persist_monotonic = time.monotonic()
        self._load()
        self._ensure_history_initialized()
        # Jednorázová migrace starého v3.8.11 souboru se uloží ihned. Běžný
        # provoz už zapisuje na SD pouze podle SAVE_SECONDS (standardně 1 h).
        if self._migration_needed and DATA_FILE.exists():
            try:
                with self.lock:
                    self._save()
            except Exception:
                pass
        atexit.register(self.flush)

    def _sanitize_history(self, raw: Any) -> Dict[str, Dict[str, Dict[str, int]]]:
        clean: Dict[str, Dict[str, Dict[str, int]]] = {}
        if not isinstance(raw, dict):
            return clean
        for year, months in raw.items():
            year_s = str(year)
            if not (len(year_s) == 4 and year_s.isdigit()) or not isinstance(months, dict):
                continue
            out_months: Dict[str, Dict[str, int]] = {}
            for month, bucket in months.items():
                month_s = str(month).zfill(2)
                if month_s not in {f"{m:02d}" for m in range(1, 13)} or not isinstance(bucket, dict):
                    continue
                try:
                    rx = max(0, int(bucket.get("rx_bytes", bucket.get("download_bytes", 0)) or 0))
                    tx = max(0, int(bucket.get("tx_bytes", bucket.get("upload_bytes", 0)) or 0))
                except (TypeError, ValueError):
                    continue
                out_months[month_s] = {"rx_bytes": rx, "tx_bytes": tx}
            if out_months:
                clean[year_s] = out_months
        return clean

    def _load(self) -> None:
        try:
            if DATA_FILE.exists():
                raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key in self.state:
                        if key in raw and key != "history":
                            self.state[key] = raw[key]
                    self.state["history"] = self._sanitize_history(raw.get("history", {}))
                    self.state["total_rx_bytes"] = max(0, int(self.state.get("total_rx_bytes") or 0))
                    self.state["total_tx_bytes"] = max(0, int(self.state.get("total_tx_bytes") or 0))
        except Exception as exc:
            self.state["status"] = "error"
            self.state["error"] = f"Načtení {DATA_FILE}: {exc}"

    def _ensure_history_initialized(self) -> None:
        """Jednorázově převede celoživotní součet v3.8.11 do aktuálního měsíce."""
        with self.lock:
            history = self.state.setdefault("history", {})
            initialized = bool(self.state.get("history_initialized"))
            year, month = _year_month()
            if initialized:
                history.setdefault(year, {})
                history[year].setdefault(month, _empty_bucket())
                self.state["version"] = 2
                return

            any_history = any(
                int(bucket.get("rx_bytes", 0) or 0) > 0 or int(bucket.get("tx_bytes", 0) or 0) > 0
                for months in history.values() if isinstance(months, dict)
                for bucket in months.values() if isinstance(bucket, dict)
            )
            if not any_history:
                history.setdefault(year, {})
                history[year][month] = {
                    "rx_bytes": int(self.state.get("total_rx_bytes") or 0),
                    "tx_bytes": int(self.state.get("total_tx_bytes") or 0),
                }
            else:
                history.setdefault(year, {})
                history[year].setdefault(month, _empty_bucket())

            self.state["history_initialized"] = True
            self.state["history_started_at"] = self.state.get("history_started_at") or _utc_now()
            self.state["version"] = 2
            self._dirty = True
            self._migration_needed = True

    def _save(self) -> None:
        # Volá se pouze při drženém self.lock. Běžné WAN vzorky zůstávají v RAM
        # a na SD kartu se zapisuje nejvýše 1x za SAVE_SECONDS.
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.state["persisted_at"] = _utc_now()
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
        self._dirty = False
        self._migration_needed = False
        self._last_persist_monotonic = time.monotonic()

    def flush(self) -> None:
        """Zapíše rozpracovaný součet při korektním ukončení procesu."""
        try:
            with self.lock:
                if self._dirty:
                    self._save()
        except Exception:
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

    def _add_history_delta(self, rx_delta: int, tx_delta: int) -> None:
        year, month = _year_month()
        history = self.state.setdefault("history", {})
        months = history.setdefault(year, {})
        bucket = months.setdefault(month, _empty_bucket())
        bucket["rx_bytes"] = int(bucket.get("rx_bytes") or 0) + max(0, int(rx_delta))
        bucket["tx_bytes"] = int(bucket.get("tx_bytes") or 0) + max(0, int(tx_delta))

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

                source_changed = (
                    last_rx is not None
                    and last_tx is not None
                    and not same_source
                )
                counter_reset = False
                delta_rx = 0
                delta_tx = 0

                if same_source:
                    last_rx_i = int(last_rx)
                    last_tx_i = int(last_tx)
                    if rx >= last_rx_i:
                        delta_rx = rx - last_rx_i
                    else:
                        counter_reset = True
                    if tx >= last_tx_i:
                        delta_tx = tx - last_tx_i
                    else:
                        counter_reset = True

                if delta_rx or delta_tx:
                    self.state["total_rx_bytes"] = int(self.state.get("total_rx_bytes") or 0) + delta_rx
                    self.state["total_tx_bytes"] = int(self.state.get("total_tx_bytes") or 0) + delta_tx
                    self._add_history_delta(delta_rx, delta_tx)

                self.state["last_rx_bytes"] = rx
                self.state["last_tx_bytes"] = tx
                self.state["last_device"] = device
                self.state["last_boot_id"] = boot_id
                self.state["updated_at"] = _utc_now()
                self.state["status"] = "ok"
                self.state["error"] = ""
                self.state["version"] = 2
                self._dirty = True

                due = (time.monotonic() - self._last_persist_monotonic) >= SAVE_SECONDS
                if (not DATA_FILE.exists()) or source_changed or counter_reset or due:
                    self._save()
        except Exception as exc:
            with self.lock:
                self.state["status"] = "error"
                self.state["error"] = str(exc)
                self.state["updated_at"] = _utc_now()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.state)

    def history_snapshot(self) -> Dict[str, Any]:
        with self.lock:
            history = copy.deepcopy(self.state.get("history", {}))
            years = sorted(history.keys(), reverse=True)
            current_year, current_month = _year_month()
            if current_year not in years:
                years.insert(0, current_year)
            return {
                "history": history,
                "years": years,
                "current_year": current_year,
                "current_month": current_month,
                "history_started_at": self.state.get("history_started_at", ""),
                "updated_at": self.state.get("updated_at", ""),
                "persisted_at": self.state.get("persisted_at", ""),
                "status": self.state.get("status", "unknown"),
                "error": self.state.get("error", ""),
            }

    def _loop(self) -> None:
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
    """Zaregistruje persistentní WAN čítač, měsíční historii a API."""
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
                "persisted_at": state.get("persisted_at", ""),
                "save_interval_seconds": SAVE_SECONDS,
                "error": state.get("error", ""),
            })

    history_endpoint_name = "wan_history_api_v3812"
    if history_endpoint_name not in app.view_functions:
        @app.get("/api/wan-history", endpoint=history_endpoint_name)
        def _wan_history_api():
            snap = collector.history_snapshot()
            return jsonify({
                "ok": snap.get("status") == "ok",
                "status": snap.get("status", "unknown"),
                "years": snap.get("years", []),
                "current_year": snap.get("current_year", ""),
                "current_month": snap.get("current_month", ""),
                "history_started_at": snap.get("history_started_at", ""),
                "updated_at": snap.get("updated_at", ""),
                "persisted_at": snap.get("persisted_at", ""),
                "history": snap.get("history", {}),
                "error": snap.get("error", ""),
            })

    collector.start()
    return collector
