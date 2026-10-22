"""The update service: check, stage, and hand the install to a helper."""
from __future__ import annotations

import os
import subprocess
import sys
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
            import json
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

    def status(self) -> dict:
        """What is available, without downloading anything."""
        current = current_version()
        if not is_portable():
            return {
                "current_version": current,
                "latest_version": None,
                "update_available": False,
                "checked": False,
                "portable": False,
                "error": "源码方式运行，请从仓库获取新版本。",
            }
        plan = updater.plan_update(self.root, current)
        return {**plan, "portable": True}

    def stage(self) -> dict:
        """Download and verify the newer release."""
        if not is_portable():
            raise OSError("源码方式运行无法自动更新。")
        current = current_version()
        work = self.root / updater.DATA_DIR / "update"
        work.mkdir(parents=True, exist_ok=True)
        log = work / "progress.txt"
        return updater.stage_update(self.root, current, progress=lambda m: log.write_text(m, encoding="utf-8"))

    def install(self, archive: str) -> dict:
        """Hand the staged release to a helper that runs after we stop."""
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
        return {"scheduled": True, "log": str(log)}
