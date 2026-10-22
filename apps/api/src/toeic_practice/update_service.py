"""The update service: check, download in the background, then install.

The download is large, so it runs in the background and the page polls for
its progress. The state is kept in memory because the program is one
process; when the program stops, the state goes with it, which is what
we want: a download that was interrupted is simply started again.

The learner's data is never part of an update.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import updater


def program_root() -> Path:
    """The folder the program runs from."""
    return Path(__file__).resolve().parents[4]


def current_version() -> str:
    """The version this build reports."""
    info = program_root() / "build-info.json"
    if info.is_file():
        try:
            return str(json.loads(info.read_text(encoding="utf-8")).get("version", ""))
        except (OSError, ValueError):
            pass
    return ""


def is_portable() -> bool:
    """Only a portable package can replace itself."""
    root = program_root()
    return (root / "Start.cmd").is_file() and (root / "runtime" / "python.exe").is_file()


class UpdateService:
    """Offer a newer release and install it once the service stops."""

    def __init__(self) -> None:
        self.root = program_root()
        self._lock = threading.Lock()
        self._state: dict = {
            "current_version": current_version(),
            "latest_version": None,
            "latest_tag": None,
            "update_available": False,
            "checked": False,
            "portable": is_portable(),
            "error": None,
            "phase": "idle",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "archive": None,
            "sha256": None,
        }
        self._worker: threading.Thread | None = None

    # ---------- state ----------

    def snapshot(self) -> dict:
        """What the page needs to show, without touching the network."""
        with self._lock:
            return dict(self._state)

    def _set(self, **changes) -> None:
        with self._lock:
            self._state.update(changes)

    # ---------- checking ----------

    def check(self) -> dict:
        """Look for a newer release."""
        if not is_portable():
            self._set(phase="unsupported", checked=True,
                      error="源码方式运行，请从仓库获取新版本。")
            return self.snapshot()
        self._set(phase="checking", error=None)
        try:
            plan = updater.plan_update(self.root, current_version())
        except OSError as error:
            self._set(phase="error", checked=True, error=str(error))
            return self.snapshot()
        if not plan.get("checked"):
            self._set(phase="error", checked=True,
                      error=plan.get("error") or "无法检查更新")
            return self.snapshot()
        self._set(**{**plan, "phase": "available" if plan["update_available"] else "current"})
        # A package that was already downloaded is still good, even after the
        # page was reloaded and the in-memory state was lost.
        if plan["update_available"]:
            staged = self._staged_archive(plan["latest_version"])
            if staged is not None:
                self._set(phase="ready", archive=str(staged))
        return self.snapshot()

    def _staged_archive(self, version: str) -> Path | None:
        """The downloaded package for a version, when it is still there."""
        if not version:
            return None
        archive = (self.root / updater.DATA_DIR / "update" /
                   f"TOEIC-Practice-Studio-{version}-windows-x64.zip")
        return archive if archive.is_file() else None

    # ---------- downloading ----------

    def start_download(self) -> dict:
        """Begin the download in the background."""
        with self._lock:
            if self._state["phase"] in ("downloading", "ready"):
                return dict(self._state)
        if not is_portable():
            self._set(phase="unsupported", error="源码方式运行无法自动更新。")
            return self.snapshot()
        with self._lock:
            if self._worker and self._worker.is_alive():
                return dict(self._state)
            self._worker = threading.Thread(target=self._download, daemon=True)
            self._worker.start()
        # Give the worker a moment so the page sees a phase right away.
        for _ in range(20):
            if self.snapshot()["phase"] != "idle":
                break
            time.sleep(0.05)
        return self.snapshot()

    def _download(self) -> None:
        """Do the download and the check, in the background."""
        self._set(phase="checking", error=None, downloaded_bytes=0, total_bytes=0)
        try:
            plan = updater.plan_update(self.root, current_version())
        except OSError as error:
            self._set(phase="error", checked=True, error=str(error))
            return
        if not plan.get("checked"):
            self._set(phase="error", checked=True,
                      error=plan.get("error") or "无法检查更新")
            return
        if not plan.get("update_available"):
            self._set(**{**plan, "phase": "current"})
            return
        version = updater.parse_version(plan["latest_version"])
        assets = updater.release_assets(version)
        work = self.root / updater.DATA_DIR / "update"
        work.mkdir(parents=True, exist_ok=True)
        archive = work / f"TOEIC-Practice-Studio-{plan['latest_version']}-windows-x64.zip"
        checksum = work / "checksum.txt"
        if archive.is_file():
            # A package from an earlier session is reused once it checks out.
            try:
                updater.download(assets["checksum"], checksum)
                expected = updater.read_checksum(
                    checksum.read_text(encoding="utf-8", errors="replace"))
                if expected and updater.file_sha256(archive) == expected:
                    self._set(**plan, phase="ready", archive=str(archive),
                              sha256=expected,
                              downloaded_bytes=archive.stat().st_size,
                              total_bytes=archive.stat().st_size)
                    return
            except OSError:
                pass
            archive.unlink(missing_ok=True)
        try:
            total = updater.remote_size(assets["archive"])
            self._set(**plan, phase="downloading", total_bytes=total,
                      downloaded_bytes=0, archive=None)
            updater.download(assets["archive"], archive,
                             progress=lambda done: self._set(downloaded_bytes=done))
            updater.download(assets["checksum"], checksum)
            expected = updater.read_checksum(
                checksum.read_text(encoding="utf-8", errors="replace"))
            if not expected:
                raise OSError("校验文件无法识别")
            actual = updater.file_sha256(archive)
            if actual != expected:
                archive.unlink(missing_ok=True)
                raise OSError("下载内容与校验不符，已删除")
        except OSError as error:
            self._set(phase="error", error=str(error))
            return
        self._set(**plan, phase="ready", archive=str(archive), sha256=actual,
                  downloaded_bytes=archive.stat().st_size,
                  total_bytes=archive.stat().st_size)

    # ---------- installing ----------

    def install(self, archive: str) -> dict:
        """Hand the downloaded release to a helper that runs after we stop."""
        path = Path(archive)
        if not path.is_file():
            raise OSError("更新包不存在，请重新下载。")
        work = self.root / updater.DATA_DIR / "update"
        log = work / "progress.txt"
        python = self.root / "runtime" / "python.exe"
        if not python.is_file():
            python = Path(sys.executable)
        environment = {**os.environ,
                       "PYTHONPATH": str(self.root / "apps" / "api" / "src")}
        subprocess.Popen(
            [str(python), "-B", "-X", "utf8", "-m", "toeic_practice.update_apply",
             "--root", str(self.root), "--archive", str(path),
             "--port", str(os.environ.get("TOEIC_PORT", "8765")),
             "--pid", str(os.getpid()),
             "--log", str(log)],
            cwd=str(self.root),
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        self._set(phase="installing")
        return {"scheduled": True, "log": str(log)}