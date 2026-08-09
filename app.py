from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, render_template, request

from mesh_core import MeshController

app = Flask(__name__)
controller = MeshController()


class OperationManager:
    """Jedna dlouhá operace najednou + živý stav pro webové UI."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._started_monotonic: Optional[float] = None
        self._state: Dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> Dict[str, Any]:
        return {
            "status": "idle",
            "kind": "",
            "title": "Připraveno",
            "progress": 0,
            "message": "Žádná operace neběží.",
            "started_at": "",
            "finished_at": "",
            "elapsed_seconds": 0,
            "nodes": {},
            "logs": [],
            "result": None,
            "error": "",
        }

    def is_running(self) -> bool:
        with self._lock:
            return self._state.get("status") == "running"

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            state = copy.deepcopy(self._state)
            if state.get("status") == "running" and self._started_monotonic is not None:
                state["elapsed_seconds"] = max(0, int(time.monotonic() - self._started_monotonic))
            return state

    def clear(self) -> Dict[str, Any]:
        with self._lock:
            if self._state.get("status") == "running":
                raise RuntimeError("Probíhající operaci nelze vyčistit.")
            self._state = self._idle_state()
            self._started_monotonic = None
            return copy.deepcopy(self._state)

    def _append_log_locked(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._state.setdefault("logs", []).append(f"[{stamp}] {message}")
        self._state["logs"] = self._state["logs"][-250:]

    def progress_callback(
        self,
        percent: int,
        message: str,
        ip: Optional[str] = None,
        status: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        with self._lock:
            if self._state.get("status") != "running":
                return
            self._state["progress"] = max(0, min(100, int(percent)))
            if message:
                self._state["message"] = message
                self._append_log_locked(message)
            if ip:
                node = self._state.setdefault("nodes", {}).setdefault(
                    ip,
                    {"name": ip, "status": "queued", "detail": "Čeká na spuštění."},
                )
                if status:
                    node["status"] = status
                if detail is not None:
                    node["detail"] = detail

    def start(
        self,
        kind: str,
        title: str,
        fn: Callable[..., Dict[str, Any]],
        *args: Any,
        include_nodes: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        with self._lock:
            if self._state.get("status") == "running":
                raise RuntimeError(f"Už probíhá operace: {self._state.get('title', 'jiná operace')}")

            nodes: Dict[str, Dict[str, str]] = {}
            if include_nodes:
                nodes = {
                    str(router["ip"]): {
                        "name": str(router.get("name") or router["ip"]),
                        "status": "queued",
                        "detail": "Čeká na spuštění.",
                    }
                    for router in controller.routers
                }

            self._started_monotonic = time.monotonic()
            self._state = {
                "status": "running",
                "kind": kind,
                "title": title,
                "progress": 0,
                "message": "Operace byla spuštěna.",
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": "",
                "elapsed_seconds": 0,
                "nodes": nodes,
                "logs": [],
                "result": None,
                "error": "",
            }
            self._append_log_locked(f"START: {title}")

        thread = threading.Thread(
            target=self._run,
            args=(fn, args, kwargs),
            daemon=True,
            name=f"mesh-operation-{kind}",
        )
        thread.start()
        return self.snapshot()

    def _run(self, fn: Callable[..., Dict[str, Any]], args: tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
        try:
            result = fn(*args, progress=self.progress_callback, **kwargs)
            with self._lock:
                self._state["status"] = "done"
                self._state["progress"] = 100
                self._state["message"] = "Operace byla dokončena."
                self._state["result"] = result
                self._state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if self._started_monotonic is not None:
                    self._state["elapsed_seconds"] = max(0, int(time.monotonic() - self._started_monotonic))
                self._append_log_locked("HOTOVO: operace dokončena.")
        except Exception as exc:
            controller.log(f"[OPERACE CHYBA] {exc}")
            with self._lock:
                self._state["status"] = "error"
                self._state["message"] = f"Operace selhala: {exc}"
                self._state["error"] = str(exc)
                self._state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if self._started_monotonic is not None:
                    self._state["elapsed_seconds"] = max(0, int(time.monotonic() - self._started_monotonic))
                self._append_log_locked(f"CHYBA: {exc}")


operations = OperationManager()


def result_json(fn: Callable[..., Any], *args: Any, **kwargs: Any):
    try:
        return jsonify(fn(*args, **kwargs))
    except Exception as exc:
        controller.log(f"[API CHYBA] {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 500


def start_operation(kind: str, title: str, fn: Callable[..., Dict[str, Any]], *args: Any, include_nodes: bool = True, **kwargs: Any):
    try:
        state = operations.start(kind, title, fn, *args, include_nodes=include_nodes, **kwargs)
        return jsonify({"ok": True, "started": True, "operation": state})
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc), "operation": operations.snapshot()}), 409
    except Exception as exc:
        controller.log(f"[API OPERACE CHYBA] {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/")
def index():
    return render_template("index.html", refresh_seconds=controller.refresh_seconds)


@app.get("/api/status")
def api_status():
    return jsonify(controller.snapshot())


@app.get("/api/logs")
def api_logs():
    return jsonify({"logs": controller.logs(int(request.args.get("limit", "250")))})


@app.get("/api/operation")
def api_operation():
    return jsonify(operations.snapshot())


@app.post("/api/operation/clear")
def api_operation_clear():
    return result_json(operations.clear)


@app.post("/api/refresh")
def api_refresh():
    return start_operation("refresh", "Obnovení stavu sítě", controller.refresh)


@app.post("/api/active-scan")
def api_active_scan():
    return start_operation("active-scan", "Aktivní vyhledání zařízení v LAN", controller.active_scan)


@app.post("/api/backup")
def api_backup():
    return start_operation("backup", "Záloha konfigurace všech routerů", controller.backup_configs)


@app.post("/api/ping")
def api_ping():
    return start_operation("ping", "Ping test všech 5 uzlů", controller.ping_all)


@app.get("/api/maintenance")
def api_maintenance():
    return result_json(controller.maintenance_status)


@app.post("/api/reboot")
def api_reboot():
    return start_operation("reboot", "Restart všech 5 routerů", controller.reboot_all)


@app.post("/api/led")
def api_led():
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode", "default")
    mode_title = {"off": "LED trvale OFF", "on": "LED trvale ON", "default": "LED výchozí režim"}.get(mode, "LED změna")
    return start_operation("led", mode_title, controller.led_mode, mode, payload.get("targets"))


@app.post("/api/update")
def api_update():
    return start_operation("update", "Aktualizace balíčků na všech 5 routerech", controller.update_all)


@app.post("/api/uplinks")
def api_uplinks():
    payload = request.get_json(silent=True) or {}
    try:
        controller.save_uplinks(payload)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def auto_refresh_worker() -> None:
    time.sleep(2)
    while True:
        try:
            if not operations.is_running():
                controller.refresh()
        except Exception as exc:
            controller.log(f"[AUTO REFRESH CHYBA] {exc}")
        time.sleep(controller.refresh_seconds)


if __name__ == "__main__":
    threading.Thread(target=auto_refresh_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8088, debug=False, threaded=True)
