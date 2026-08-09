from __future__ import annotations

import threading
import time
from flask import Flask, jsonify, render_template, request

from mesh_core import MeshController

app = Flask(__name__)
controller = MeshController()


def result_json(fn, *args, **kwargs):
    try:
        return jsonify(fn(*args, **kwargs))
    except Exception as exc:
        controller.log(f"[API CHYBA] {exc}")
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


@app.post("/api/refresh")
def api_refresh():
    return result_json(controller.refresh)


@app.post("/api/active-scan")
def api_active_scan():
    return result_json(controller.active_scan)


@app.post("/api/backup")
def api_backup():
    return result_json(controller.backup_configs)


@app.post("/api/ping")
def api_ping():
    return result_json(controller.ping_all)


@app.get("/api/maintenance")
def api_maintenance():
    return result_json(controller.maintenance_status)


@app.post("/api/reboot")
def api_reboot():
    return result_json(controller.reboot_all)


@app.post("/api/led")
def api_led():
    payload = request.get_json(silent=True) or {}
    return result_json(controller.led_mode, payload.get("mode", "default"), payload.get("targets"))


@app.post("/api/update")
def api_update():
    return result_json(controller.update_all)


@app.post("/api/safe-mesh")
def api_safe_mesh():
    payload = request.get_json(silent=True) or {}
    return result_json(controller.safe_mesh_deploy, payload)


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
            controller.refresh()
        except Exception as exc:
            controller.log(f"[AUTO REFRESH CHYBA] {exc}")
        time.sleep(controller.refresh_seconds)


if __name__ == "__main__":
    threading.Thread(target=auto_refresh_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8088, debug=False, threaded=True)
