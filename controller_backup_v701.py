from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import ssl
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from flask import after_this_request, jsonify, request, send_file

VERSION = "7.0.1"
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SETTINGS_FILE = DATA_DIR / "controller_backup_settings.json"
STATUS_FILE = DATA_DIR / "controller_backup_status.json"
OWUT_SETTINGS_FILE = DATA_DIR / "owut_settings.json"
RESTORE_STAGE = DATA_DIR / ".controller_restore_stage"
RESTORE_MARKER = DATA_DIR / ".controller_restore_pending.json"
MAX_IMPORT_BYTES = 128 * 1024 * 1024
AUTO_RETRY_SECONDS = 120

EXCLUDED_TOP_LEVEL = {"backups", ".controller_restore_stage"}
EXCLUDED_FILES = {
    "mesh_operation.json",
    "mesh_scheduler_v500.json",
    "owut_pending_mail.json",
    "controller_backup_status.json",
    ".controller_restore_pending.json",
    "controller_restore_result.json",
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "server": "",
    "username": "",
    "password": "",
    "remote_dir": "/OpenWRT-MESH-CONTROLLER",
}

try:
    LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "Europe/Prague"))
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _now_text() -> str:
    return _now().isoformat(timespec="seconds")


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else dict(default)
    except Exception:
        return dict(default)


def _atomic_json_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _safe_relative(value: str) -> Path:
    rel = Path(str(value or "").replace("\\", "/"))
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"Neplatná cesta v záloze: {value}")
    if rel.parts[0] in EXCLUDED_TOP_LEVEL or rel.name in EXCLUDED_FILES:
        raise ValueError(f"Zakázaná cesta v záloze: {value}")
    return rel


def apply_pending_restore() -> None:
    """Aplikuje připravený import ještě před načtením ostatních /data stavů."""
    if not RESTORE_MARKER.exists():
        return
    marker = _read_json(RESTORE_MARKER, {})
    files = marker.get("files")
    if not isinstance(files, list) or not RESTORE_STAGE.is_dir():
        RESTORE_MARKER.unlink(missing_ok=True)
        shutil.rmtree(RESTORE_STAGE, ignore_errors=True)
        return

    restored = 0
    for item in files:
        rel = _safe_relative(str(item))
        src = RESTORE_STAGE / rel
        if not src.is_file() or src.is_symlink():
            continue
        dst = DATA_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".restoretmp")
        shutil.copy2(src, tmp)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, dst)
        restored += 1

    # Rozpracovaná operace, fronta e-mailu a scheduler runtime nejsou součástí
    # disaster-recovery nastavení a po importu se nesmí obnovit ze starého stavu.
    for name in ("mesh_operation.json", "mesh_scheduler_v500.json", "owut_pending_mail.json", "controller_backup_status.json"):
        try:
            (DATA_DIR / name).unlink()
        except FileNotFoundError:
            pass

    shutil.rmtree(RESTORE_STAGE, ignore_errors=True)
    RESTORE_MARKER.unlink(missing_ok=True)
    _atomic_json_write(DATA_DIR / "controller_restore_result.json", {
        "ok": True,
        "restored_files": restored,
        "restored_at": _now_text(),
        "controller_version": VERSION,
    })


class ControllerBackupManager:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self._last_auto_attempt_mono = 0.0

    # ------------------------------------------------------------ settings --
    def _settings_raw(self) -> Dict[str, Any]:
        raw = _read_json(SETTINGS_FILE, DEFAULT_SETTINGS)
        out = dict(DEFAULT_SETTINGS)
        out.update({k: raw.get(k, out[k]) for k in out})
        return out

    def settings_public(self) -> Dict[str, Any]:
        cfg = self._settings_raw()
        return {
            "server": str(cfg.get("server") or ""),
            "username": str(cfg.get("username") or ""),
            "remote_dir": str(cfg.get("remote_dir") or DEFAULT_SETTINGS["remote_dir"]),
            "password_set": bool(str(cfg.get("password") or "")),
            "configured": self._configured(cfg),
        }

    @staticmethod
    def _normalize_remote_dir(value: Any) -> str:
        raw = str(value or DEFAULT_SETTINGS["remote_dir"]).strip().replace("\\", "/")
        if not raw.startswith("/"):
            raw = "/" + raw
        parts = [p for p in raw.split("/") if p]
        if any(p in {".", ".."} for p in parts):
            raise ValueError("Cílový adresář obsahuje neplatnou cestu.")
        return "/" + "/".join(parts) if parts else "/"

    def save_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = self._settings_raw()
        server = str(payload.get("server") or "").strip().rstrip("/")
        username = str(payload.get("username") or "").strip()
        remote_dir = self._normalize_remote_dir(payload.get("remote_dir"))
        password = str(payload.get("password") or "")
        if not password:
            password = str(current.get("password") or "")
        cfg = {"server": server, "username": username, "password": password, "remote_dir": remote_dir}
        _atomic_json_write(SETTINGS_FILE, cfg)
        return self.settings_public()

    @staticmethod
    def _configured(cfg: Dict[str, Any]) -> bool:
        return bool(str(cfg.get("server") or "").strip() and str(cfg.get("username") or "").strip() and str(cfg.get("password") or ""))

    # --------------------------------------------------------------- backup --
    def _flush_wan(self) -> None:
        try:
            collector = self.app.extensions.get("wan_usage") if hasattr(self.app, "extensions") else None
            if collector is not None and hasattr(collector, "flush"):
                collector.flush()
        except Exception:
            pass

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _backup_files(self) -> List[Tuple[Path, Path]]:
        rows: List[Tuple[Path, Path]] = []
        if not DATA_DIR.exists():
            return rows
        for path in sorted(DATA_DIR.rglob("*")):
            try:
                rel = path.relative_to(DATA_DIR)
            except ValueError:
                continue
            if not rel.parts or rel.parts[0] in EXCLUDED_TOP_LEVEL:
                continue
            if rel.name in EXCLUDED_FILES:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            rows.append((path, rel))
        return rows

    def create_archive(self) -> Tuple[Path, Dict[str, Any]]:
        self._flush_wan()
        files = self._backup_files()
        manifest_files: List[Dict[str, Any]] = []
        for source, rel in files:
            manifest_files.append({
                "path": rel.as_posix(),
                "size": source.stat().st_size,
                "sha256": self._sha256(source),
            })

        created = _now()
        filename = f"mesh-controller-backup_v{VERSION}_{created.strftime('%Y%m%d-%H%M%S')}.tar.gz"
        fd, tmp_name = tempfile.mkstemp(prefix="mesh-controller-", suffix=".tar.gz")
        os.close(fd)
        archive = Path(tmp_name)
        manifest = {
            "format": "mesh-controller-backup",
            "schema": 1,
            "controller_version": VERSION,
            "created_at": created.isoformat(timespec="seconds"),
            "filename": filename,
            "excluded": sorted(EXCLUDED_TOP_LEVEL | EXCLUDED_FILES),
            "files": manifest_files,
        }

        with tarfile.open(archive, "w:gz") as tar:
            raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(raw)
            info.mode = 0o600
            info.mtime = int(created.timestamp())
            tar.addfile(info, io.BytesIO(raw))
            for source, rel in files:
                tar.add(source, arcname=f"data/{rel.as_posix()}", recursive=False)

        self.validate_archive(archive)
        return archive, manifest

    def validate_archive(self, archive: Path) -> Dict[str, Any]:
        total = 0
        with tarfile.open(archive, "r:gz") as tar:
            try:
                manifest_member = tar.getmember("manifest.json")
            except KeyError as exc:
                raise ValueError("Archiv neobsahuje manifest.json.") from exc
            if not manifest_member.isfile() or manifest_member.size > 2 * 1024 * 1024:
                raise ValueError("Neplatný manifest zálohy.")
            stream = tar.extractfile(manifest_member)
            if stream is None:
                raise ValueError("Manifest nelze načíst.")
            manifest = json.loads(stream.read().decode("utf-8"))
            if manifest.get("format") != "mesh-controller-backup" or int(manifest.get("schema") or 0) != 1:
                raise ValueError("Soubor není platná záloha MESH Controlleru.")
            listed = manifest.get("files")
            if not isinstance(listed, list) or len(listed) > 10000:
                raise ValueError("Neplatný seznam souborů v záloze.")

            members = {m.name: m for m in tar.getmembers()}
            verified = 0
            for row in listed:
                if not isinstance(row, dict):
                    raise ValueError("Neplatný záznam souboru v manifestu.")
                rel = _safe_relative(str(row.get("path") or ""))
                name = f"data/{rel.as_posix()}"
                member = members.get(name)
                if member is None or not member.isfile() or member.issym() or member.islnk():
                    raise ValueError(f"V archivu chybí bezpečný soubor {rel.as_posix()}.")
                total += int(member.size or 0)
                if total > MAX_IMPORT_BYTES:
                    raise ValueError("Záloha je příliš velká.")
                handle = tar.extractfile(member)
                if handle is None:
                    raise ValueError(f"Soubor {rel.as_posix()} nelze načíst.")
                digest = hashlib.sha256()
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                if digest.hexdigest() != str(row.get("sha256") or ""):
                    raise ValueError(f"Kontrolní součet nesouhlasí: {rel.as_posix()}.")
                verified += 1
            manifest["verified_files"] = verified
            return manifest

    def prepare_restore(self, archive: Path) -> Dict[str, Any]:
        manifest = self.validate_archive(archive)
        shutil.rmtree(RESTORE_STAGE, ignore_errors=True)
        RESTORE_STAGE.mkdir(parents=True, exist_ok=True)
        restored_files: List[str] = []
        with tarfile.open(archive, "r:gz") as tar:
            for row in manifest.get("files", []):
                rel = _safe_relative(str(row.get("path") or ""))
                member = tar.getmember(f"data/{rel.as_posix()}")
                src = tar.extractfile(member)
                if src is None:
                    raise ValueError(f"Soubor {rel.as_posix()} nelze připravit k obnově.")
                dst = RESTORE_STAGE / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                with dst.open("wb") as out:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
                try:
                    os.chmod(dst, 0o600)
                except OSError:
                    pass
                restored_files.append(rel.as_posix())
        _atomic_json_write(RESTORE_MARKER, {
            "format": "mesh-controller-restore",
            "prepared_at": _now_text(),
            "source_version": manifest.get("controller_version", ""),
            "files": restored_files,
        })
        return {"files": len(restored_files), "source_version": manifest.get("controller_version", "")}

    # ------------------------------------------------------------- Nextcloud --
    @staticmethod
    def _server_base(server: str) -> str:
        raw = str(server or "").strip()
        if not raw:
            raise ValueError("Nextcloud server není nastaven.")
        if "://" not in raw:
            raw = "https://" + raw
        parts = urlsplit(raw)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("Neplatná adresa Nextcloud serveru.")
        path = parts.path.rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))

    @staticmethod
    def _auth_header(username: str, password: str) -> str:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def _dav_request(self, method: str, url: str, cfg: Dict[str, Any], data: Optional[bytes] = None,
                     extra_headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], bytes]:
        headers = {
            "Authorization": self._auth_header(str(cfg.get("username") or ""), str(cfg.get("password") or "")),
            "User-Agent": f"OpenWRT-MESH-CONTROLLER-PRO/{VERSION}",
        }
        if extra_headers:
            headers.update(extra_headers)
        req = Request(url, data=data, headers=headers, method=method)
        context = ssl.create_default_context()
        try:
            with urlopen(req, timeout=30, context=context) as response:
                return int(response.status), dict(response.headers.items()), response.read(1024 * 1024)
        except HTTPError as exc:
            body = exc.read(4096) if exc.fp else b""
            raise RuntimeError(f"Nextcloud HTTP {exc.code}: {body.decode('utf-8', errors='replace')[:300]}") from exc

    def _dav_root(self, cfg: Dict[str, Any]) -> str:
        base = self._server_base(str(cfg.get("server") or ""))
        username = str(cfg.get("username") or "").strip()
        if not username:
            raise ValueError("Nextcloud uživatel není nastaven.")
        return f"{base}/remote.php/dav/files/{quote(username, safe='')}"

    def _ensure_remote_dir(self, cfg: Dict[str, Any]) -> str:
        root = self._dav_root(cfg)
        remote_dir = self._normalize_remote_dir(cfg.get("remote_dir"))
        current = root
        # Ověření přihlášení / WebDAV rootu.
        self._dav_request("PROPFIND", current + "/", cfg, data=b"", extra_headers={"Depth": "0"})
        for part in [p for p in remote_dir.split("/") if p]:
            current += "/" + quote(part, safe="")
            try:
                self._dav_request("PROPFIND", current + "/", cfg, data=b"", extra_headers={"Depth": "0"})
            except RuntimeError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                try:
                    self._dav_request("MKCOL", current + "/", cfg, data=b"")
                except RuntimeError as mk_exc:
                    if "HTTP 405" not in str(mk_exc):
                        raise
        return current + "/"

    def test_nextcloud(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = self._settings_raw()
        if payload:
            for key in ("server", "username", "remote_dir"):
                if key in payload:
                    cfg[key] = payload.get(key)
            password = str(payload.get("password") or "")
            if password:
                cfg["password"] = password
        if not self._configured(cfg):
            raise ValueError("Nextcloud není kompletně nastavený.")
        remote = self._ensure_remote_dir(cfg)
        return {"ok": True, "remote": remote}

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
        return {"ok": True, "url": target, "size": len(data)}

    # -------------------------------------------------------------- schedule --
    @staticmethod
    def _schedule_cfg() -> Optional[Tuple[str, int, int, int]]:
        settings = _read_json(OWUT_SETTINGS_FILE, {})
        if not bool(settings.get("auto_enabled")):
            return None
        mode = str(settings.get("schedule_mode") or "weekly").lower()
        try:
            weekday = int(settings.get("weekday", 6))
        except Exception:
            weekday = 6
        raw_time = str(settings.get("time") or "03:00")
        try:
            hh_s, mm_s = raw_time.split(":", 1)
            hh, mm = int(hh_s), int(mm_s)
        except Exception:
            return None
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return mode, weekday, hh, mm

    @staticmethod
    def _day_matches(candidate: datetime, mode: str, weekday: int) -> bool:
        return mode == "daily" or weekday == -1 or candidate.weekday() == weekday

    def _due_backup_occurrence(self, now: datetime) -> Optional[datetime]:
        schedule = self._schedule_cfg()
        if schedule is None:
            return None
        mode, weekday, hh, mm = schedule
        for offset in (0, 1):
            day = (now + timedelta(days=offset)).date()
            candidate = datetime(day.year, day.month, day.day, hh, mm, tzinfo=LOCAL_TZ)
            if not self._day_matches(candidate, mode, weekday):
                continue
            backup_at = candidate - timedelta(minutes=10)
            if backup_at <= now < candidate:
                return candidate
        return None

    def _current_owut_occurrence(self, now: Optional[datetime] = None) -> Optional[datetime]:
        now = now or _now()
        schedule = self._schedule_cfg()
        if schedule is None:
            return None
        mode, weekday, hh, mm = schedule
        day = now.date()
        candidate = datetime(day.year, day.month, day.day, hh, mm, tzinfo=LOCAL_TZ)
        if self._day_matches(candidate, mode, weekday) and candidate <= now < candidate + timedelta(minutes=5):
            return candidate
        return None

    def next_backup(self, now: Optional[datetime] = None) -> Dict[str, str]:
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
            backup_at = candidate - timedelta(minutes=10)
            if backup_at > now:
                return {"owut": candidate.isoformat(timespec="minutes"), "backup": backup_at.isoformat(timespec="minutes")}
        return {"owut": "", "backup": ""}

    def _auto_backup_once(self, scheduled_for: datetime) -> Dict[str, Any]:
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
            "detail": "",
        }
        archive: Optional[Path] = None
        try:
            archive, manifest = self.create_archive()
            filename = str(manifest.get("filename") or archive.name)
            status["filename"] = filename
            status["local_backup_ok"] = True
            status["sha256"] = self._sha256(archive)
            self.upload_nextcloud(archive, filename)
            status["nextcloud_ok"] = True
            status["ok"] = True
            status["detail"] = "Záloha Controlleru byla ověřena a uložena na Nextcloud."
        except Exception as exc:
            status["detail"] = str(exc)
        finally:
            if archive is not None:
                archive.unlink(missing_ok=True)
        _atomic_json_write(STATUS_FILE, status)
        return status

    def automatic_result_for_now(self) -> Dict[str, Any]:
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
        if status.get("schedule_key") != key:
            return {
                "ok": False,
                "local_backup_ok": False,
                "nextcloud_ok": False,
                "filename": "",
                "scheduled_for": key,
                "detail": "Předautomatická Nextcloud záloha pro tento termín není potvrzená.",
            }
        return status

    def status_public(self) -> Dict[str, Any]:
        status = _read_json(STATUS_FILE, {})
        return {
            "version": VERSION,
            "settings": self.settings_public(),
            "last_backup": status,
            "next": self.next_backup(),
        }

    def _loop(self) -> None:
        # Ostatní runtime moduly necháme po startu načíst /data a ustálit se.
        self.stop_event.wait(12)
        while not self.stop_event.wait(20):
            try:
                now = _now()
                occurrence = self._due_backup_occurrence(now)
                if occurrence is None:
                    continue
                key = occurrence.isoformat(timespec="minutes")
                status = _read_json(STATUS_FILE, {})
                if status.get("schedule_key") == key and bool(status.get("ok")):
                    continue
                now_mono = time.monotonic()
                if self._last_auto_attempt_mono and now_mono - self._last_auto_attempt_mono < AUTO_RETRY_SECONDS:
                    continue
                self._last_auto_attempt_mono = now_mono
                self._auto_backup_once(occurrence)
            except Exception:
                pass

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, daemon=True, name="controller-backup-v701")
            self.thread.start()


_manager: Optional[ControllerBackupManager] = None


def get_controller_backup_manager() -> Optional[ControllerBackupManager]:
    return _manager


def automatic_backup_result_for_now() -> Dict[str, Any]:
    if _manager is None:
        return {"ok": False, "detail": "Controller Backup Manager není inicializovaný."}
    return _manager.automatic_result_for_now()


def init_controller_backup_v701(app: Any) -> ControllerBackupManager:
    global _manager
    existing = app.extensions.get("controller_backup_v701") if hasattr(app, "extensions") else None
    if existing is not None:
        return existing
    if _manager is None:
        _manager = ControllerBackupManager(app)
    manager = _manager
    manager.app = app
    app.extensions["controller_backup_v701"] = manager

    if "v701_controller_backup_state" not in app.view_functions:
        @app.get("/api/v701/controller-backup", endpoint="v701_controller_backup_state")
        def _state():
            return jsonify({"ok": True, **manager.status_public()})

    if "v701_controller_backup_settings" not in app.view_functions:
        @app.post("/api/v701/controller-backup/settings", endpoint="v701_controller_backup_settings")
        def _settings():
            try:
                saved = manager.save_settings(request.get_json(silent=True) or {})
                return jsonify({"ok": True, "settings": saved})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

    if "v701_controller_backup_test" not in app.view_functions:
        @app.post("/api/v701/controller-backup/test", endpoint="v701_controller_backup_test")
        def _test():
            try:
                result = manager.test_nextcloud(request.get_json(silent=True) or {})
                return jsonify(result)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 502

    if "v701_controller_backup_export" not in app.view_functions:
        @app.get("/api/v701/controller-backup/export", endpoint="v701_controller_backup_export")
        def _export():
            try:
                archive, manifest = manager.create_archive()
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500
            filename = str(manifest.get("filename") or archive.name)

            @after_this_request
            def _cleanup(response):
                try:
                    archive.unlink(missing_ok=True)
                except Exception:
                    pass
                return response

            return send_file(archive, as_attachment=True, download_name=filename, mimetype="application/gzip")

    if "v701_controller_backup_import" not in app.view_functions:
        @app.post("/api/v701/controller-backup/import", endpoint="v701_controller_backup_import")
        def _import():
            upload = request.files.get("file")
            if upload is None or not upload.filename:
                return jsonify({"ok": False, "error": "Nebyl vybrán soubor zálohy."}), 400
            fd, tmp_name = tempfile.mkstemp(prefix="controller-import-", suffix=".tar.gz")
            os.close(fd)
            tmp = Path(tmp_name)
            total = 0
            try:
                with tmp.open("wb") as out:
                    while True:
                        chunk = upload.stream.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_IMPORT_BYTES:
                            raise ValueError("Importovaný soubor je příliš velký.")
                        out.write(chunk)
                result = manager.prepare_restore(tmp)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
            finally:
                tmp.unlink(missing_ok=True)

            def _restart_worker() -> None:
                time.sleep(2.0)
                os._exit(0)

            threading.Thread(target=_restart_worker, daemon=True, name="controller-restore-restart").start()
            return jsonify({
                "ok": True,
                "message": "Záloha je ověřena. Controller se restartuje a obnoví data.",
                "restored_files": result.get("files", 0),
                "source_version": result.get("source_version", ""),
            })

    manager.start()
    return manager
