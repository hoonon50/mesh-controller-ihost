from pathlib import Path
import os
import re

VERSION = "7.0.2"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
BACKUP = ROOT / "controller_backup_v701.py"
OPS = ROOT / "mesh_operation_manager.py"
INDEX = ROOT / "templates" / "index.html"
JS = ROOT / "static" / "v701_controller_backup.js"


def sub_once(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    new, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"v{VERSION}: nenalezen patch bod: {label}")
    return new


# ------------------------------------------------------ Controller backup --
backup = BACKUP.read_text(encoding="utf-8")
backup = sub_once(
    backup,
    r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
    f'VERSION = "{VERSION}"',
    "backup version",
)
if "import re\n" not in backup:
    backup = backup.replace("import os\n", "import os\nimport re\n", 1)
if "import xml.etree.ElementTree as ET\n" not in backup:
    backup = backup.replace("import time\n", "import time\nimport xml.etree.ElementTree as ET\n", 1)
backup = backup.replace(
    "from urllib.parse import quote, urlsplit, urlunsplit",
    "from urllib.parse import quote, unquote, urlsplit, urlunsplit",
    1,
)
if "REMOTE_KEEP = 10" not in backup:
    backup = backup.replace("AUTO_RETRY_SECONDS = 120\n", "AUTO_RETRY_SECONDS = 120\nREMOTE_KEEP = 10\n", 1)

upload_block = '''    def _remote_controller_backups(self, cfg: Dict[str, Any], remote_dir: str) -> List[Tuple[str, str]]:
        propfind = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
        )
        _status, _headers, body = self._dav_request(
            "PROPFIND", remote_dir, cfg, data=propfind,
            extra_headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
        )
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise RuntimeError("Nextcloud WebDAV vrátil neplatný seznam souborů.") from exc

        pattern = re.compile(r"^mesh-controller-backup_v[^_]+_(\\d{8}-\\d{6})\\.tar\\.gz$")
        rows: List[Tuple[str, str]] = []
        for response in root.findall(".//{DAV:}response"):
            href = response.findtext("{DAV:}href") or ""
            name = unquote(urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1])
            match = pattern.fullmatch(name)
            if match:
                rows.append((match.group(1), name))
        rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return rows

    def _prune_nextcloud(self, cfg: Dict[str, Any], remote_dir: str, keep: int = REMOTE_KEEP) -> Dict[str, Any]:
        rows = self._remote_controller_backups(cfg, remote_dir)
        deleted: List[str] = []
        for _stamp, name in rows[max(0, int(keep)):]:
            target = remote_dir + quote(name, safe="")
            status, _headers, _body = self._dav_request("DELETE", target, cfg)
            if status not in {200, 202, 204}:
                raise RuntimeError(f"Nextcloud DELETE vrátil HTTP {status} pro {name}.")
            deleted.append(name)
        return {"keep": int(keep), "found": len(rows), "deleted": len(deleted), "deleted_files": deleted}

    def upload_nextcloud(self, archive: Path, filename: str) -> Dict[str, Any]:
        cfg = self._settings_raw()
        if not self._configured(cfg):
            raise ValueError("Nextcloud není kompletně nastavený.")
        remote_dir = self._ensure_remote_dir(cfg)
        target = remote_dir + quote(filename, safe="")
        data = archive.read_bytes()
        status, _headers, _body = self._dav_request(
            "PUT", target, cfg, data=data,
            extra_headers={"Content-Type": "application/gzip", "Content-Length": str(len(data))},
        )
        if status not in {200, 201, 204}:
            raise RuntimeError(f"Nextcloud PUT vrátil HTTP {status}.")
        self._dav_request("PROPFIND", target, cfg, data=b"", extra_headers={"Depth": "0"})

        retention: Dict[str, Any] = {"keep": REMOTE_KEEP, "found": 0, "deleted": 0, "deleted_files": []}
        try:
            retention = self._prune_nextcloud(cfg, remote_dir, REMOTE_KEEP)
        except Exception as exc:
            # Upload je platný backup. Chyba úklidu starých souborů nesmí zrušit
            # právě vytvořenou pojistku ani následný automatický OWUT.
            retention["warning"] = str(exc)
        return {"ok": True, "url": target, "size": len(data), "retention": retention}
'''
backup = sub_once(
    backup,
    r'    def upload_nextcloud\(self, archive: Path, filename: str\) -> Dict\[str, Any\]:.*?(?=\n    # -------------------------------------------------------------- schedule --)',
    upload_block,
    "Nextcloud retention block",
    flags=re.S,
)

backup = sub_once(
    backup,
    r'    def _due_backup_occurrence\(self, now: datetime\) -> Optional\[datetime\]:.*?(?=\n    def _current_owut_occurrence)',
    '''    def _due_backup_occurrence(self, now: datetime) -> Optional[datetime]:
        # v7.0.2: žádné T-10 okno. Backup patří přímo do startu automatického OWUT.
        return self._current_owut_occurrence(now)
''',
    "same-time due window",
    flags=re.S,
)

backup = sub_once(
    backup,
    r'    def next_backup\(self, now: Optional\[datetime\] = None\) -> Dict\[str, str\]:.*?(?=\n    def _auto_backup_once)',
    '''    def next_backup(self, now: Optional[datetime] = None) -> Dict[str, str]:
        now = now or _now()
        schedule = self._schedule_cfg()
        if schedule is None:
            return {"owut": "", "backup": ""}
        mode, weekday, hh, mm = schedule
        for offset in range(0, 9):
            day = (now + timedelta(days=offset)).date()
            candidate = datetime(day.year, day.month, day.day, hh, mm, tzinfo=LOCAL_TZ)
            if not self._day_matches(candidate, mode, weekday):
                continue
            if candidate > now:
                stamp = candidate.isoformat(timespec="minutes")
                return {"owut": stamp, "backup": stamp}
        return {"owut": "", "backup": ""}
''',
    "same-time next backup",
    flags=re.S,
)

auto_block = '''    def _auto_backup_once(self, scheduled_for: datetime) -> Dict[str, Any]:
        key = scheduled_for.isoformat(timespec="minutes")
        status: Dict[str, Any] = {
            "schedule_key": key,
            "scheduled_for": key,
            "attempted_at": _now_text(),
            "ok": False,
            "local_backup_ok": False,
            "nextcloud_ok": False,
            "filename": "",
            "sha256": "",
            "retention_keep": REMOTE_KEEP,
            "retention_deleted": 0,
            "retention_warning": "",
            "detail": "",
        }
        archive: Optional[Path] = None
        try:
            archive, manifest = self.create_archive()
            filename = str(manifest.get("filename") or archive.name)
            status["filename"] = filename
            status["local_backup_ok"] = True
            status["sha256"] = self._sha256(archive)
            uploaded = self.upload_nextcloud(archive, filename)
            retention = uploaded.get("retention") if isinstance(uploaded, dict) else {}
            if not isinstance(retention, dict):
                retention = {}
            status["retention_deleted"] = int(retention.get("deleted") or 0)
            status["retention_warning"] = str(retention.get("warning") or "")
            status["nextcloud_ok"] = True
            status["ok"] = True
            status["detail"] = (
                f"Záloha Controlleru byla ověřena a uložena na Nextcloud. "
                f"Retence: max. {REMOTE_KEEP} záloh, smazáno {status['retention_deleted']} starších."
            )
            if status["retention_warning"]:
                status["detail"] += f" Upozornění retence: {status['retention_warning']}"
        except Exception as exc:
            status["detail"] = str(exc)
        finally:
            if archive is not None:
                archive.unlink(missing_ok=True)
        _atomic_json_write(STATUS_FILE, status)
        return status

'''
backup = sub_once(
    backup,
    r'    def _auto_backup_once\(self, scheduled_for: datetime\) -> Dict\[str, Any\]:.*?(?=\n    def automatic_result_for_now)',
    auto_block,
    "automatic backup retention result",
    flags=re.S,
)

backup = sub_once(
    backup,
    r'    def automatic_result_for_now\(self\) -> Dict\[str, Any\]:.*?(?=\n    def status_public)',
    '''    def automatic_result_for_now(self) -> Dict[str, Any]:
        # Volá se synchronně z _run_owut() po spuštění naplánované operace.
        # Backup tedy začíná stejným scheduler triggerem jako OWUT, nikoli T-10.
        occurrence = self._current_owut_occurrence()
        if occurrence is None:
            return {
                "ok": False,
                "local_backup_ok": False,
                "nextcloud_ok": False,
                "filename": "",
                "detail": "Není aktivní časové okno automatického OWUT.",
            }
        key = occurrence.isoformat(timespec="minutes")
        status = _read_json(STATUS_FILE, {})
        if status.get("schedule_key") == key and bool(status.get("ok")):
            return status
        return self._auto_backup_once(occurrence)
''',
    "synchronous automatic backup",
    flags=re.S,
)

backup = sub_once(
    backup,
    r'    def start\(self\) -> None:.*?(?=\n\n\n_manager:)',
    '''    def start(self) -> None:
        # v7.0.2: samostatný backup scheduler je záměrně vypnutý.
        # Automatický backup vlastní stejný trigger jako Persistent OWUT scheduler.
        return
''',
    "disable separate backup scheduler",
    flags=re.S,
)

BACKUP.write_text(backup, encoding="utf-8")


# ----------------------------------------------------------- report/version --
ops = OPS.read_text(encoding="utf-8")
ops = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', ops, count=1)
ops = re.sub(r'START v\d+\.\d+\.\d+:', f'START v{VERSION}:', ops)
ops = re.sub(r'Persistent Operation Manager v\d+\.\d+\.\d+', f'Persistent Operation Manager v{VERSION}', ops)
ops = re.sub(r'OpenWRT MESH CONTROLLER PRO v\d+\.\d+\.\d+', f'OpenWRT MESH CONTROLLER PRO v{VERSION}', ops)
ops = ops.replace(
    "Předautomatická záloha není potvrzená.",
    "Automatická záloha Controlleru/Nextcloudu pro tento termín není potvrzená.",
)
ops = ops.replace(
    "ZÁLOHA CONTROLLERU PŘED AUTOMATICKÝM OWUT",
    "ZÁLOHA CONTROLLERU · AUTOMATICKÝ OWUT",
)
OPS.write_text(ops, encoding="utf-8")

# Verze v souvisejících modulech je pouze metadata; jejich funkční logiku neměníme.
for path in (
    ROOT / "owut_manager.py",
    ROOT / "live_topology_v503.py",
    ROOT / "lan_port_control_v620.py",
    ROOT / "topology_inspector_v631.py",
    ROOT / "lan_port_inspector_v630.py",
    ROOT / "client_ip_resolver_v632.py",
):
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', text, count=1)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------- UI --
html_text = INDEX.read_text(encoding="utf-8")
html_text = re.sub(r'<title>.*?</title>', f'<title>OpenWRT MESH CONTROLLER PRO · v.{VERSION}</title>', html_text, count=1, flags=re.S)
html_text = re.sub(r'<span class="app-version">v\.[^<]+</span>', f'<span class="app-version">v.{VERSION}</span>', html_text, count=1)
html_text = html_text.replace(
    "NEXTCLOUD · AUTOMATICKY 10 MINUT PŘED OWUT",
    "NEXTCLOUD · AUTOMATICKY VE STEJNÝ ČAS JAKO OWUT",
)
html_text = html_text.replace(
    "Den ani čas se zde nenastavuje. Automatika vždy použije den a čas z automatického OWUT a spustí Nextcloud zálohu přesně o 10 minut dříve.",
    "Den ani čas se zde nenastavuje. Automatická záloha se spustí stejným plánovaným triggerem jako OWUT; po úspěšném backupu OWUT pokračuje. Na Nextcloudu se ponechává posledních 10 automatických záloh.",
)
html_text = re.sub(r'(/static/[A-Za-z0-9_.-]+\.(?:css|js)\?v=)[^"\']+', rf'\g<1>{VERSION}', html_text)
INDEX.write_text(html_text, encoding="utf-8")

js = JS.read_text(encoding="utf-8")
js = js.replace(
    "`Další Nextcloud záloha: ${localDateTime(next.backup)} · OWUT: ${localDateTime(next.owut)} (vždy −10 minut)`",
    "`Další automatická záloha + OWUT: ${localDateTime(next.owut)} · stejný plánovaný čas · Nextcloud ponechá posledních 10 záloh`",
)
js = js.replace(
    "'Automatika se řídí výhradně nastavením automatického OWUT (vždy −10 minut).'",
    "'Automatická záloha se řídí výhradně plánem OWUT a spouští se ve stejný čas. Nextcloud ponechá posledních 10 záloh.'",
)
JS.write_text(js, encoding="utf-8")


# ----------------------------------------------------------- build safeguards --
backup_check = BACKUP.read_text(encoding="utf-8")
ops_check = OPS.read_text(encoding="utf-8")
index_check = INDEX.read_text(encoding="utf-8")
js_check = JS.read_text(encoding="utf-8")
checks = {
    "version": f'VERSION = "{VERSION}"' in backup_check and f'v.{VERSION}' in index_check,
    "same OWUT trigger": "return self._auto_backup_once(occurrence)" in backup_check,
    "separate backup scheduler disabled": "samostatný backup scheduler je záměrně vypnutý" in backup_check,
    "no T-10 backend": "timedelta(minutes=10)" not in backup_check,
    "retention 10": "REMOTE_KEEP = 10" in backup_check and "_prune_nextcloud" in backup_check,
    "UI same time": "VE STEJNÝ ČAS JAKO OWUT" in index_check and "stejný plánovaný čas" in js_check,
    "UI no minus 10": "−10 minut" not in js_check and "10 MINUT PŘED OWUT" not in index_check,
    "report updated": "ZÁLOHA CONTROLLERU · AUTOMATICKÝ OWUT" in ops_check,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f"v{VERSION}: build safeguard selhal: {', '.join(failed)}")

print(f"v{VERSION}: automatic Controller/Nextcloud backup now uses the exact OWUT scheduler trigger")
print(f"v{VERSION}: separate T-10 backup scheduler disabled")
print(f"v{VERSION}: Nextcloud retention keeps the newest {10} automatic Controller backups")
print(f"v{VERSION}: no other Controller logic changed")
