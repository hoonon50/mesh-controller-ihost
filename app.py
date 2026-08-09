from __future__ import annotations

import threading
import time
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file

from mesh_core import controller

app = Flask(__name__)

@app.get("/")
def index():
    return render_template("index.html", routers=controller.routers)

@app.get("/api/status")
def api_status():
    snap = controller.get_snapshot()
    if not snap.get("updated"):
        try:
            snap = controller.refresh_snapshot()
        except Exception:
            pass
    return jsonify(snap)

@app.post("/api/refresh")
def api_refresh():
    def worker():
        try: controller.refresh_snapshot()
        except Exception: pass
    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})

@app.get("/api/operation")
def api_operation():
    return jsonify(controller.operation.snapshot())

@app.post("/api/action/<name>")
def api_action(name: str):
    if name == "backup": ok = controller.start_backup()
    elif name == "update": ok = controller.start_update()
    elif name == "ping": ok = controller.start_ping()
    elif name == "reboot": ok = controller.start_reboot()
    elif name == "led_on": ok = controller.start_led("on", (request.json or {}).get("target", "all"))
    elif name == "led_off": ok = controller.start_led("off", (request.json or {}).get("target", "all"))
    else: return jsonify({"ok": False, "error": "Neznámá akce"}), 404
    return jsonify({"ok": bool(ok)}), (200 if ok else 409)

@app.get("/api/backups")
def api_backups():
    return jsonify(controller.list_backups())

@app.get("/api/backups/<set_id>/<filename>")
def download_backup_file(set_id: str, filename: str):
    p = controller.backup_file(set_id, filename)
    if not p: return jsonify({"error": "Soubor nenalezen"}), 404
    return send_file(p, as_attachment=True, download_name=p.name)

@app.get("/api/backups/<set_id>.zip")
def download_backup_zip(set_id: str):
    p = controller.build_backup_zip(set_id)
    if not p: return jsonify({"error": "Záloha nenalezena"}), 404
    return send_file(p, as_attachment=True, download_name=p.name)

@app.delete("/api/backups/<set_id>")
def delete_backup(set_id: str):
    return jsonify({"ok": controller.delete_backup(set_id)})


def refresh_loop():
    time.sleep(2)
    while True:
        try: controller.refresh_snapshot()
        except Exception: pass
        seconds = int(controller.cfg.get("refresh_seconds", 30) or 30)
        time.sleep(max(15, seconds))

threading.Thread(target=refresh_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088, debug=False)
