"""Consistent SQLite backups and bounded, checksummed built-in library bundles."""
import hashlib
import json
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .errors import ApiError, bad_request, conflict, not_found
from .library import Library
from .store import SCHEMA_VERSION

MAX_LIBRARY_BYTES = 2 * 1024**3
MAX_LIBRARY_FILES = 20000


def checksum(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class BackupService:
    def __init__(self, store, library, clock, backup_root: Path) -> None:
        self.store, self.library, self.clock = store, library, clock
        self.root = Path(backup_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _descriptor_path(self, backup_id):
        if not re.fullmatch(r"bak-[a-f0-9]{12}", backup_id):
            raise not_found("备份不存在。", "backup_not_found")
        return self.root / f"{backup_id}.json"

    def _file_path(self, backup_id):
        self._descriptor_path(backup_id)
        return self.root / f"{backup_id}.sqlite3"

    def _archive_path(self, backup_id):
        self._descriptor_path(backup_id)
        return self.root / f"{backup_id}.library.zip"

    def _bundle_path(self, backup_id):
        self._descriptor_path(backup_id)
        return self.root / f"{backup_id}.zip"

    def list_backups(self):
        backups = []
        for path in sorted(self.root.glob("bak-*.json")):
            try:
                meta = self.descriptor(path.stem)
                backups.append({k: meta[k] for k in
                    ("id", "created_at", "size_bytes", "includes_library")})
            except (ApiError, KeyError):
                continue
        return {"backups": backups}

    def create(self, include_library=False):
        if self.store.memory:
            raise conflict("内存数据库不支持文件备份。", "memory_store")
        with self.store.exclusive():
            backup_id = "bak-" + uuid.uuid4().hex[:12]
            target = self._file_path(backup_id)
            with closing(sqlite3.connect(target)) as dest:
                self.store._conn.backup(dest)
            meta = {"id": backup_id, "format_version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "includes_library": bool(include_library),
                "schema_version": SCHEMA_VERSION,
                "library_version": self.library.library_version(),
                "sha256": checksum(target)}
            if include_library:
                root = self.library.root.resolve()
                if not root.is_dir() or self.library.root.is_symlink() or self.library.root.is_junction():
                    raise conflict("受控题库路径无效。", "library_path_invalid")
                files = {}
                total = 0
                with zipfile.ZipFile(self._archive_path(backup_id), "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(root.rglob("*")):
                        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
                            raise conflict("题库不能包含外部链接。", "library_path_invalid")
                        if path.is_file():
                            total += path.stat().st_size
                            if total > MAX_LIBRARY_BYTES or len(files) >= MAX_LIBRARY_FILES:
                                raise conflict("题库超出备份大小限制。", "library_too_large")
                            name = path.relative_to(root).as_posix()
                            files[name] = checksum(path)
                            archive.write(path, name)
                meta["library_sha256"] = checksum(self._archive_path(backup_id))
                meta["library_files"] = files
                # Download is a complete portable bundle, not a DB-only link.
                with zipfile.ZipFile(self._bundle_path(backup_id), "w", zipfile.ZIP_STORED) as bundle:
                    bundle.write(target, "state.sqlite3")
                    bundle.write(self._archive_path(backup_id), "library.zip")
                    bundle.writestr("backup.json", json.dumps(meta, ensure_ascii=False))
                meta["bundle_sha256"] = checksum(self._bundle_path(backup_id))
                meta["size_bytes"] = self._bundle_path(backup_id).stat().st_size
            else:
                meta["size_bytes"] = target.stat().st_size
            self._descriptor_path(backup_id).write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return {**meta, "download_url": f"/api/backups/{backup_id}/download"}

    def descriptor(self, backup_id):
        path = self._descriptor_path(backup_id)
        if not path.is_file():
            raise not_found("备份不存在。", "backup_not_found")
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            if meta["id"] != backup_id:
                raise ValueError("id mismatch")
            return meta
        except (ValueError, KeyError, OSError):
            raise conflict("备份描述文件无效。", "backup_invalid")

    def file_for_download(self, backup_id):
        meta = self.descriptor(backup_id)
        path = self._bundle_path(backup_id) if meta["includes_library"] else self._file_path(backup_id)
        if not path.is_file():
            raise not_found("备份文件缺失。", "backup_file_missing")
        return path

    def _validate_database(self, path, meta):
        if not path.is_file() or checksum(path) != meta.get("sha256"):
            raise conflict("备份校验和不匹配。", "checksum_mismatch")
        if meta.get("schema_version") != SCHEMA_VERSION:
            raise conflict("备份 schema 版本不兼容。", "schema_mismatch")
        try:
            with closing(sqlite3.connect(path)) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("integrity")
                row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if not row or int(row[0]) != SCHEMA_VERSION:
                    raise conflict("备份 schema 标记不兼容。", "schema_mismatch")
                required = {"attempts", "answers", "mutations", "reviews", "vocab_evidence", "vocab_state", "settings", "question_latest"}
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not required <= tables:
                    raise ValueError("tables")
                for table in required:
                    expected = {r[1] for r in self.store.query(f"PRAGMA table_info({table})")}
                    expected.discard("request_json")  # additive v1 migration
                    present = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                    if not expected <= present:
                        raise ValueError("columns")
        except (sqlite3.Error, ValueError):
            raise conflict("备份数据库完整性验证失败。", "integrity_failed")

    def _extract_library(self, backup_id, meta, target, archive_path=None):
        archive_path = archive_path or self._archive_path(backup_id)
        if not archive_path.is_file() or checksum(archive_path) != meta.get("library_sha256"):
            raise conflict("题库归档校验失败。", "library_checksum_mismatch")
        files = meta.get("library_files")
        if not isinstance(files, dict) or not files:
            raise conflict("题库文件清单缺失。", "library_archive_invalid")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_LIBRARY_FILES or sum(i.file_size for i in infos) > MAX_LIBRARY_BYTES:
                    raise ValueError("size limit")
                seen = set()
                for info in infos:
                    name = info.filename
                    parts = PurePosixPath(name).parts
                    if (not parts or name != PurePosixPath(name).as_posix() or "\\" in name or name.startswith("/") or
                        any(p in (".", "..") or ":" in p or p.rstrip(". ") != p or
                            re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
                            for p in parts) or
                        name.casefold() in seen or info.is_dir() or
                        stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK or name not in files):
                        raise ValueError("unsafe member")
                    seen.add(name.casefold())
                    dest = target.joinpath(*parts)
                    if not dest.resolve().is_relative_to(target.resolve()):
                        raise ValueError("path outside root")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, dest.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    if checksum(dest) != files[name]:
                        raise ValueError("member checksum")
                if {i.filename for i in infos} != set(files):
                    raise ValueError("incomplete archive")
            candidate = Library(target)
            candidate.load()
            if (not candidate.available or candidate.library_version() != meta.get("library_version") or
                    any(e.blockers for e in candidate.exams.values())):
                raise ValueError("incompatible library")
            # All registered paths must stay inside this managed root.
            for asset_id in candidate.assets:
                candidate.asset_path(asset_id)
            for source in candidate.sources.values():
                path = (target / source["path"]).resolve()
                if not path.is_relative_to(target.resolve()) or not path.is_file():
                    raise ValueError("source path")
            return candidate
        except (OSError, ValueError, TypeError, AttributeError, KeyError, zipfile.BadZipFile, RuntimeError):
            raise conflict("题库归档无效或版本不兼容。", "library_archive_invalid")

    def _copy_database(self, source_path):
        with closing(sqlite3.connect(source_path)) as source, closing(sqlite3.connect(self.store.path)) as target:
            source.backup(target)

    def restore(self, backup_id, confirm):
        if not confirm:
            raise bad_request("还原需要 confirm=true。", "confirm_required")
        if self.store.memory:
            raise conflict("内存数据库不支持还原。", "memory_store")
        meta = self.descriptor(backup_id)
        if meta.get("format_version", 1) != 1:
            raise conflict("备份包版本不兼容。", "backup_version_mismatch")
        root = self.library.root.resolve()
        if self.library.root.is_symlink() or self.library.root.is_junction():
            raise conflict("题库路径不能是链接。", "library_path_invalid")
        root.parent.mkdir(parents=True, exist_ok=True)
        # Staging/cleanup is restricted to this newly-created private directory.
        with tempfile.TemporaryDirectory(prefix=".toeic-restore-", dir=root.parent) as workdir:
            work = Path(workdir)
            staged_db = work / "state.sqlite3"
            try:
                shutil.copyfile(self._file_path(backup_id), staged_db)
            except OSError:
                raise not_found("备份文件缺失。", "backup_file_missing")
            self._validate_database(staged_db, meta)
            staged = work / "library"
            if meta.get("includes_library"):
                staged.mkdir()
                bundle = self._bundle_path(backup_id)
                if not bundle.is_file() or checksum(bundle) != meta.get("bundle_sha256"):
                    raise conflict("完整备份包校验失败。", "bundle_checksum_mismatch")
                staged_archive = work / "library.zip"
                try:
                    shutil.copyfile(self._archive_path(backup_id), staged_archive)
                except OSError:
                    raise conflict("题库归档文件缺失。", "library_archive_invalid")
                self._extract_library(backup_id, meta, staged, staged_archive)
            # Hold exclusivity from FINAL guard through rollback and recovery.
            with self.store.exclusive():
                if not meta.get("includes_library") and meta.get("library_version") != self.library.library_version():
                    raise conflict("备份题库版本与当前题库不兼容。", "library_version_mismatch")
                from .attempts import AttemptService
                attempts = AttemptService(self.store, self.library, self.clock)
                for row in self.store.query("SELECT id FROM attempts WHERE status IN ('running','paused')"):
                    attempts.get(row["id"])
                if self.store.query_one("SELECT COUNT(*) AS n FROM attempts WHERE status IN ('running','paused')")["n"]:
                    raise conflict("存在进行中的计时练习，不能还原。", "active_attempts")
                rollback = self.create(include_library=bool(meta.get("includes_library")))
                previous = work / "previous-library"
                try:
                    self.store.checkpoint_and_close()
                    self._copy_database(staged_db)
                    if meta.get("includes_library"):
                        root.rename(previous)
                        staged.rename(root)
                        self.library.load()
                        if not self.library.available:
                            raise RuntimeError("library reload failed")
                    self.store.reconnect()
                except Exception:
                    try:
                        self._copy_database(self._file_path(rollback["id"]))
                        if previous.exists():
                            if root.exists():
                                root.rename(work / "failed-library")
                            previous.rename(root)
                        self.library.load()
                    finally:
                        self.store.reconnect()
                    raise
                return {"restored": backup_id, "rollback_backup_id": rollback["id"],
                        "library_version": meta["library_version"]}
