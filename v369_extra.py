from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import jsonify


def _fmt_uptime(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _read_one(controller, router):
    ip = str(router.get("ip", "")).strip()
    name = str(router.get("name", ip)).strip() or ip
    result = {
        "ip": ip,
        "name": name,
        "cpu_temp": None,
        "uptime": None,
        "online": False,
    }
    if not ip:
        return result

    client = None
    try:
        client = controller.ssh_client(ip, 4)
        cmd = r'''T=""
for f in /sys/class/thermal/thermal_zone*/temp; do
    [ -r "$f" ] || continue
    T="$(cat "$f" 2>/dev/null | head -n1)"
    [ -n "$T" ] && break
done
U="$(cut -d. -f1 /proc/uptime 2>/dev/null)"
printf 'TEMP=%s\nUPTIME=%s\n' "$T" "$U"
'''
        out, _err, code = controller.command(client, cmd, 7)
        if code not in (0, None):
            return result

        raw_temp = ""
        raw_uptime = ""
        for line in str(out or "").splitlines():
            if line.startswith("TEMP="):
                raw_temp = line.split("=", 1)[1].strip()
            elif line.startswith("UPTIME="):
                raw_uptime = line.split("=", 1)[1].strip()

        if raw_temp:
            try:
                value = float(raw_temp)
                if abs(value) >= 1000:
                    value /= 1000.0
                result["cpu_temp"] = int(round(value))
            except ValueError:
                pass

        if raw_uptime:
            try:
                result["uptime"] = _fmt_uptime(int(float(raw_uptime)))
            except ValueError:
                pass

        result["online"] = True
        return result
    except Exception:
        return result
    finally:
        try:
            if client:
                client.close()
        except Exception:
            pass


def register_v369(app, controller):
    if getattr(app, "_v369_registered", False):
        return
    app._v369_registered = True

    @app.get("/api/v369/router-health")
    def v369_router_health():
        try:
            if hasattr(controller, "runtime_routers"):
                routers = list(controller.runtime_routers())
            else:
                routers = list(getattr(controller, "routers", []) or [])
        except Exception:
            routers = list(getattr(controller, "routers", []) or [])

        rows = []
        with ThreadPoolExecutor(max_workers=max(1, min(5, len(routers) or 1))) as pool:
            futures = [pool.submit(_read_one, controller, r) for r in routers]
            for future in as_completed(futures):
                try:
                    rows.append(future.result())
                except Exception:
                    pass

        rows.sort(key=lambda x: tuple(int(p) if p.isdigit() else 999 for p in x.get("ip", "").split(".")))
        return jsonify({"routers": rows})
