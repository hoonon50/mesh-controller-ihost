from pathlib import Path
import os
import re

VERSION = "6.3.4"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
OWUT = ROOT / "owut_manager.py"

if not OWUT.exists():
    raise SystemExit(f"v{VERSION}: owut_manager.py nenalezen")

text = OWUT.read_text(encoding="utf-8")

replacement = r'''def _start_owut_background(controller, ip: str) -> Tuple[bool, str]:
    add = _owut_args(ip)
    cmd = f"owut upgrade --verbose {add}".strip()

    # v6.3.4: nespoléhat na externí `nohup`. Na některých OpenWrt obrazech
    # nemusí být applet dostupný; starý launcher přesto vytiskl STARTED a
    # background příkaz mohl okamžitě zemřít bez logu/exit souboru.
    # Ignorovaný SIGHUP se nastaví přímo v POSIX/BusyBox ash child shellu.
    inner = (
        "trap '' HUP; "
        f"{cmd}; "
        "rc=$?; printf '%s\\n' \"$rc\" > /tmp/mesh-owut.exit; exit \"$rc\""
    )
    shell = (
        "rm -f /tmp/mesh-owut.exit /tmp/mesh-owut.log /tmp/mesh-owut.pid; "
        ": > /tmp/mesh-owut.log; "
        f"sh -c {shlex.quote(inner)} >> /tmp/mesh-owut.log 2>&1 </dev/null & "
        "pid=$!; printf '%s\\n' \"$pid\" > /tmp/mesh-owut.pid; "
        "sleep 2; "
        "if kill -0 \"$pid\" 2>/dev/null; then "
        "  printf 'STARTED PID=%s\\n' \"$pid\"; exit 0; "
        "fi; "
        "if [ -s /tmp/mesh-owut.exit ]; then "
        "  rc=$(cat /tmp/mesh-owut.exit 2>/dev/null || echo 255); "
        "  printf 'EXIT=%s\\n' \"$rc\"; tail -n 20 /tmp/mesh-owut.log 2>/dev/null || true; "
        "  [ \"$rc\" = 0 ] && exit 0; exit 23; "
        "fi; "
        "printf 'FAILED PID=%s\\n' \"$pid\"; "
        "tail -n 20 /tmp/mesh-owut.log 2>/dev/null || true; exit 24"
    )
    try:
        out, err, code = _ssh_exec(controller, ip, shell, 15)
        detail = (out + ("\n" + err if err else "")).strip()
        if code == 0 and ("STARTED PID=" in out or "EXIT=0" in out):
            return True, detail
        return False, detail or f"OWUT launcher skončil kódem {code}."
    except Exception as exc:
        return False, str(exc)


def _watch_owut(
    controller,
    ip: str,
    build_timeout: int = 1200,
    reboot_timeout: int = 480,
    label: str = "",
    progress_start: Optional[int] = None,
) -> Tuple[bool, str, bool]:
    """Vrací (ok, detail, rebooted). v6.3.4 přidává heartbeat a diagnostiku launcheru."""
    started_at = time.time()
    deadline = started_at + build_timeout
    last_log = ""
    last_heartbeat = 0.0
    dead_without_result = 0
    display = label or ip

    while time.time() < deadline:
        if not _ssh_ok(controller, ip, 4):
            _op_log(f"{display}: router se restartuje po OWUT…", progress_start)
            if not _wait_online(controller, ip, reboot_timeout):
                return False, "Router se po OWUT nevrátil online.", True
            return True, "Router se po OWUT vrátil online.", True

        try:
            out, _err, _code = _ssh_exec(
                controller,
                ip,
                "printf 'EXIT='; cat /tmp/mesh-owut.exit 2>/dev/null || true; printf '\\n'; "
                "pid=$(cat /tmp/mesh-owut.pid 2>/dev/null || true); printf 'PID=%s\\n' \"$pid\"; "
                "if [ -n \"$pid\" ] && kill -0 \"$pid\" 2>/dev/null; then echo 'RUNNING=1'; else echo 'RUNNING=0'; fi; "
                "echo '__LOG__'; tail -n 20 /tmp/mesh-owut.log 2>/dev/null || true",
                10,
            )

            m = re.search(r"^EXIT=(\d+)\s*$", out, re.M)
            if m:
                code = int(m.group(1))
                log_part = out.split("__LOG__", 1)[1].strip() if "__LOG__" in out else ""
                if log_part:
                    last_log = log_part
                low = (log_part or out).lower()
                if code == 0:
                    if "no changes" in low or "nothing to do" in low or "no upgrade" in low:
                        return True, "owut: není co aktualizovat.", False
                    return True, "owut dokončil operaci bez restartu.", False
                return False, (log_part or out.strip() or f"owut skončil kódem {code}"), False

            running = bool(re.search(r"^RUNNING=1\s*$", out, re.M))
            log_part = out.split("__LOG__", 1)[1].strip() if "__LOG__" in out else ""
            if log_part:
                last_log = log_part

            if running:
                dead_without_result = 0
            elif not last_log:
                dead_without_result += 1
                # Launcher už start ověřuje po 2 s. Toto je druhá pojistka pro
                # případ, že proces mezitím beze stopy zanikne.
                if dead_without_result >= 2:
                    return False, "OWUT proces neběží a nevznikl log ani exit kód; background launcher selhal.", False
            else:
                dead_without_result = 0

            now = time.time()
            if now - last_heartbeat >= 30:
                last_heartbeat = now
                elapsed = max(0, int(now - started_at))
                mm, ss = divmod(elapsed, 60)
                total_mm, total_ss = divmod(build_timeout, 60)
                tail_line = ""
                if last_log:
                    for line in reversed(last_log.splitlines()):
                        clean = " ".join(line.split())
                        if clean:
                            tail_line = clean[:180]
                            break
                msg = f"{display}: OWUT běží {mm:02d}:{ss:02d} / {total_mm:02d}:{total_ss:02d}"
                if tail_line:
                    msg += f" · {tail_line}"
                _op_log(msg, progress_start)
        except Exception:
            # Krátký SSH výpadek může být začátek rebootu; další průchod ho zachytí.
            pass

        time.sleep(10)

    detail = "Timeout při čekání na OWUT."
    if last_log:
        detail += " Poslední log: " + " | ".join(last_log.splitlines()[-6:])[-900:]
    return False, detail, False
'''

pattern = re.compile(
    r"def _start_owut_background\(controller, ip: str\) -> Tuple\[bool, str\]:.*?(?=\ndef _reboot_and_wait\()",
    re.S,
)
text, count = pattern.subn(replacement.rstrip() + "\n\n", text, count=1)
if count != 1:
    raise SystemExit(f"v{VERSION}: nepodařilo se nahradit OWUT launcher/watchdog")

old_call = "            ok, detail, rebooted = _watch_owut(controller, ip)\n"
new_call = (
    "            _op_log(f\"{label}: OWUT proces potvrzen – {detail}\", min(90, base_progress + 1))\n"
    "            ok, detail, rebooted = _watch_owut(\n"
    "                controller, ip, label=label, progress_start=min(90, base_progress + 1)\n"
    "            )\n"
)
if old_call not in text:
    raise SystemExit(f"v{VERSION}: nenalezen call-site _watch_owut")
text = text.replace(old_call, new_call, 1)

OWUT.write_text(text, encoding="utf-8")
print(f"v{VERSION}: OWUT launcher bez nohup + ověření PID/exit/log po startu")
print(f"v{VERSION}: OWUT watchdog heartbeat každých 30 s + rychlá detekce falešného startu")
