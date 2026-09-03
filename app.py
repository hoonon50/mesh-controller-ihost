from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file

# v7.0.1 controller restore before /data consumers
from controller_backup_v701 import apply_pending_restore
apply_pending_restore()

from mesh_core import controller
app = Flask(__name__)








# v6.3.1 topology node device inspector
from topology_inspector_v631 import init_topology_inspector_v631
init_topology_inspector_v631(app)

# v6.3.0 LAN port device inspector
from lan_port_inspector_v630 import init_lan_port_inspector_v630
init_lan_port_inspector_v630(app)

# v6.2.0 LAN port runtime control
from lan_port_control_v620 import init_lan_port_control_v620
init_lan_port_control_v620(app)

# v6.0.0 silent AP inactivity policy
from wifi_ap_policy_v600 import init_wifi_ap_policy_v600
init_wifi_ap_policy_v600(app)

# v5.0.7 explicit live topology API
from live_topology_v503 import init_live_topology_v503
init_live_topology_v503(app)

# v5.0.0 persistent operation manager
from mesh_operation_manager import init_operation_manager
init_operation_manager(app)

# v7.0.1 controller backup manager
from controller_backup_v701 import init_controller_backup_v701
init_controller_backup_v701(app)
# v3.8.9 WAN usage
from wan_usage import init_wan_usage
init_wan_usage(app)

def get_ihost_ip() -> str:
    """Vrátí IPv4 adresu iHostu použitou pro cestu do LAN s routery."""
    targets = ["192.168.30.1", "1.1.1.1"]
    for target in targets:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            sock.close()
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "IP nezjištěna"

@app.get("/")
def index():
    return render_template("index.html", routers=controller.routers, ihost_ip=get_ihost_ip())

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
        time.sleep(max(60, seconds))

threading.Thread(target=refresh_loop, daemon=True).start()

# v3.6.12 – CPU teplota + uptime v topologii
from v369_extra import register_v369
register_v369(app, controller)

# v3.8.7 – daily schedule + reliable automatic reports
from owut_manager import register_owut_manager
register_owut_manager(app, controller)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088, debug=False)
