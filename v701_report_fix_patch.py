from pathlib import Path
import os
import re

VERSION = "7.0.1"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
OPS = ROOT / "mesh_operation_manager.py"

ops = OPS.read_text(encoding="utf-8")
pattern = re.compile(
    r'    def _build_report\(self, ok: bool\) -> Tuple\[str, str, str\]:.*?(?=\n    def _send_mail\()',
    re.S,
)
match = pattern.search(ops)
if not match:
    raise SystemExit(f"v{VERSION}: _build_report nenalezen")

method = '''    def _build_report(self, ok: bool) -> Tuple[str, str, str]:
        state = self.snapshot()
        title = "KOMPLETNÍ REBOOT MESH" if state.get("kind") == "reboot_all" else "OWUT SYSUPGRADE"
        result = "VŠE V POŘÁDKU" if ok else "CHYBA / NEDOKONČENO"
        subject = f"{'OK' if ok else 'CHYBA'} – OpenWRT MESH {title}"
        rows_text: List[str] = []
        html_rows: List[str] = []
        by_ip = {str(r.get("ip")): r for r in state.get("nodes", [])}
        for ip, name in ROUTERS:
            row = by_ip.get(ip, {})
            status = str(row.get("status") or "pending")
            success = status in {"done", "no_update", "online"}
            mark = "OK" if success else "CHYBA" if status in {"error", "paused"} else status.upper()
            temp = row.get("temperature_c")
            temp_text = f"{temp} °C" if temp is not None else "N/A"
            detail = str(row.get("detail") or "")
            rows_text.append(f"{name:<7} {ip:<15} {mark:<12} CPU {temp_text}  {detail}")
            color = "#16a34a" if success else "#dc2626" if status in {"error", "paused"} else "#64748b"
            html_rows.append(
                f'<tr><td style="padding:7px 8px;font-weight:700">{html.escape(name)}</td>'
                f'<td style="padding:7px 8px;color:#64748b">{html.escape(ip)}</td>'
                f'<td style="padding:7px 8px;color:{color};font-weight:700">{html.escape(mark)}</td>'
                f'<td style="padding:7px 8px">{html.escape(temp_text)}</td>'
                f'<td style="padding:7px 8px;color:#64748b">{html.escape(detail)}</td></tr>'
            )

        ihost_temp = self._ihost_temperature()
        ihost_text = f"{ihost_temp} °C" if ihost_temp is not None else "N/A"

        controller_backup = state.get("controller_backup") or {}
        auto_owut = state.get("kind") == "owut_upgrade" and bool(state.get("automatic"))
        local_ok = bool(controller_backup.get("local_backup_ok"))
        nextcloud_ok = bool(controller_backup.get("nextcloud_ok"))
        backup_filename = str(controller_backup.get("filename") or "—")
        backup_detail = str(controller_backup.get("detail") or "")

        nl = chr(10)
        text_lines = [
            f"OpenWRT MESH CONTROLLER PRO v{VERSION}",
            "",
            f"Operace: {title}",
            f"Datum: {_now_text()}",
            f"Výsledek: {result}",
            f"Záloha: {state.get('backup_id') or '—'}",
            "",
            *rows_text,
            "",
            f"iHost teplota: {ihost_text}",
        ]
        if auto_owut:
            text_lines.extend([
                "",
                f"CONTROLLER BACKUP: {'OK' if local_ok else 'CHYBA'}",
                f"NEXTCLOUD BACKUP: {'OK' if nextcloud_ok else 'CHYBA'}",
                f"SOUBOR: {backup_filename}",
            ])
            if backup_detail:
                text_lines.append(f"BACKUP DETAIL: {backup_detail}")
        text_lines.extend(["", str(state.get("message") or "")])
        text_body = nl.join(text_lines)

        banner = "#16a34a" if ok else "#dc2626"
        controller_backup_html = ""
        if auto_owut:
            nc_color = "#16a34a" if nextcloud_ok else "#dc2626"
            local_color = "#16a34a" if local_ok else "#dc2626"
            controller_backup_html = (
                '<tr><td style="padding:0 20px 18px">'
                '<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;font-size:12px">'
                '<tr style="background:#f8fafc"><th colspan="2" style="padding:8px;text-align:left">ZÁLOHA CONTROLLERU PŘED AUTOMATICKÝM OWUT</th></tr>'
                f'<tr><td style="padding:7px 8px">CONTROLLER BACKUP</td><td style="padding:7px 8px;color:{local_color};font-weight:700">{"OK" if local_ok else "CHYBA"}</td></tr>'
                f'<tr><td style="padding:7px 8px">NEXTCLOUD BACKUP</td><td style="padding:7px 8px;color:{nc_color};font-weight:700">{"OK" if nextcloud_ok else "CHYBA"}</td></tr>'
                f'<tr><td style="padding:7px 8px">SOUBOR</td><td style="padding:7px 8px;color:#334155">{html.escape(backup_filename)}</td></tr>'
                + (f'<tr><td style="padding:7px 8px">DETAIL</td><td style="padding:7px 8px;color:#64748b">{html.escape(backup_detail)}</td></tr>' if backup_detail else '')
                + '</table></td></tr>'
            )

        html_body = f'''<!doctype html><html><body style="margin:0;background:#f3f6f9;padding:20px 8px">
<table role="presentation" width="100%"><tr><td align="center"><table role="presentation" width="760" style="width:100%;max-width:760px;background:#fff;border:1px solid #dce3ea;border-radius:14px;overflow:hidden;border-spacing:0;font-family:Arial,sans-serif">
<tr><td style="background:#071a2d;padding:20px 24px;color:#fff"><b style="font-size:20px">OpenWRT MESH CONTROLLER PRO v{VERSION}</b><div style="font-size:12px;color:#cbd5e1;margin-top:4px">{html.escape(title)}</div></td></tr>
<tr><td style="padding:18px 20px"><div style="background:{banner};color:#fff;border-radius:10px;padding:16px 18px"><b style="font-size:19px">{html.escape(result)}</b><div style="font-size:12px;margin-top:5px">{html.escape(_now_text())}</div></div></td></tr>
<tr><td style="padding:0 20px 18px"><table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;font-size:12px"><tr style="background:#f8fafc"><th style="padding:7px">UZEL</th><th>IP</th><th>STAV</th><th>CPU</th><th>DETAIL</th></tr>{''.join(html_rows)}</table></td></tr>
{controller_backup_html}
<tr><td style="padding:0 20px 20px;color:#334155;font-size:12px">Záloha: <b>{html.escape(str(state.get('backup_id') or '—'))}</b> &nbsp; · &nbsp; iHost teplota: <b>{html.escape(ihost_text)}</b></td></tr>
<tr><td style="background:#071a2d;padding:12px 20px;color:#cbd5e1;font-size:10px">Persistent Operation Manager v{VERSION}</td></tr>
</table></td></tr></table></body></html>'''
        return subject, text_body, html_body
'''

ops = ops[:match.start()] + method + ops[match.end():]
OPS.write_text(ops, encoding="utf-8")

print(f"v{VERSION}: HTML/text OWUT report rebuilt syntax-safe with Controller/Nextcloud backup block")
