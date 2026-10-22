"""Check for a newer release and install it without touching learner data.

The portable package runs from a folder the learner can move anywhere, so an
update has to find the newest release, fetch it, and lay it down beside the
running copy. Two constraints shape the design:

* The running program holds its own files open, so it cannot overwrite them.
  The replacement is therefore done by a separate step that runs **after**
  the service has stopped.
* The learner's data lives in ``.data`` inside the program folder. An update
  must never move, delete or overwrite it.

The release list is read from the ``releases/latest`` redirect rather than the
GitHub API: the redirect needs no token and no API quota, so a user behind a
shared address is not turned away by a rate limit.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

RELEASES_LATEST = "https://github.com/sbljsc/toeic-practice-studio/releases/latest"
RELEASES_DOWNLOAD = "https://github.com/sbljsc/toeic-practice-studio/releases/download"
USER_AGENT = "toeic-practice-studio"
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
TIMEOUT = 60
DATA_DIR = ".data"


def parse_version(text: str):
    """Read a semantic version, with or without the leading v."""
    match = VERSION_RE.match((text or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def version_text(version) -> str:
    return ".".join(str(part) for part in version)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Read the redirect target instead of following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _head(url: str, timeout: int = TIMEOUT):
    """Ask for a URL's headers. Returns the status and the Location."""
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Location", "")
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Location", "")


def latest_release():
    """The newest published release, as a tag and a version."""
    status, location = _head(RELEASES_LATEST)
    if status not in (301, 302, 303, 307, 308) or not location:
        raise OSError(f"无法读取最新发行版（HTTP {status}）")
    tag = location.rstrip("/").rsplit("/", 1)[-1]
    version = parse_version(tag)
    if version is None:
        raise OSError(f"发行标签无法识别：{tag}")
    return tag, version


def release_assets(version) -> dict:
    """The download addresses of one release's assets."""
    text = version_text(version)
    return {
        "archive": (f"{RELEASES_DOWNLOAD}/v{text}/"
                    f"TOEIC-Practice-Studio-{text}-windows-x64.zip"),
        "checksum": (f"{RELEASES_DOWNLOAD}/v{text}/"
                     f"TOEIC-Practice-Studio-{text}-windows-x64.zip.sha256"),
    }


def remote_size(url: str, timeout: int = TIMEOUT) -> int:
    """How large a download is, so the page can show a progress bar."""
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length", "0")
            return int(length) if length.isdigit() else 0
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def download(url: str, target: Path, timeout: int = 900, progress=None) -> None:
    """Fetch a file to a path, following redirects."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        done = 0
        with target.open("wb") as output:
            while True:
                block = response.read(1024 * 256)
                if not block:
                    break
                output.write(block)
                done += len(block)
                if progress:
                    progress(done)
        if progress:
            progress(done)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_checksum(text: str) -> str:
    """The digest out of a sha256sum line."""
    for line in (text or "").splitlines():
        parts = line.split()
        if parts and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return ""


def plan_update(root: Path, current: str) -> dict:
    """Compare the running version with the newest release."""
    result = {
        "current_version": current,
        "latest_version": None,
        "latest_tag": None,
        "update_available": False,
        "checked": False,
        "error": None,
    }
    try:
        tag, version = latest_release()
    except (OSError, urllib.error.URLError, ValueError) as error:
        result["error"] = str(error)
        return result
    result["checked"] = True
    result["latest_version"] = version_text(version)
    result["latest_tag"] = tag
    here = parse_version(current)
    result["update_available"] = bool(here and version > here)
    return result


def stage_update(root: Path, current: str, progress=None) -> dict:
    """Download a newer release and verify it, without installing it yet."""
    root = Path(root).resolve()
    plan = plan_update(root, current)
    if not plan["checked"]:
        raise OSError(plan["error"] or "无法检查更新")
    if not plan["update_available"]:
        return {**plan, "staged": False}
    version = parse_version(plan["latest_version"])
    assets = release_assets(version)
    work = root / DATA_DIR / "update"
    work.mkdir(parents=True, exist_ok=True)
    archive = work / f"TOEIC-Practice-Studio-{plan['latest_version']}-windows-x64.zip"
    checksum_file = work / "checksum.txt"
    if progress:
        progress(f"正在下载 {plan['latest_version']}…")
    download(assets["archive"], archive)
    if progress:
        progress("正在读取校验文件…")
    download(assets["checksum"], checksum_file)
    expected = read_checksum(checksum_file.read_text(encoding="utf-8", errors="replace"))
    if not expected:
        raise OSError("校验文件无法识别")
    if progress:
        progress("正在校验下载内容…")
    actual = file_sha256(archive)
    if actual != expected:
        archive.unlink(missing_ok=True)
        raise OSError("下载内容与校验不符，已删除")
    return {
        **plan,
        "staged": True,
        "archive": str(archive),
        "sha256": actual,
        "bytes": archive.stat().st_size,
    }


def extract_release(archive: Path, destination: Path) -> Path:
    """Unpack a release and return the folder that holds the program."""
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("发行包包含不安全的路径")
        source.extractall(destination)
    roots = [item for item in destination.iterdir()
              if item.is_dir() and (item / "Start.cmd").is_file()]
    if len(roots) != 1:
        raise ValueError("发行包结构无法识别")
    return roots[0]


def install_staged(root: Path, archive: Path) -> dict:
    """Replace the program files with a staged release.

    The learner's data folder stays exactly where it is: it is never part of
    the replacement, and the running program is expected to have stopped.
    """
    root = Path(root).resolve()
    archive = Path(archive).resolve()
    if not (root / "Start.cmd").is_file():
        raise ValueError("这不是便携版目录")
    with tempfile.TemporaryDirectory(prefix="toeic-update-") as temporary:
        staged = extract_release(archive, Path(temporary))
        for name in ("docs", "apps", "content", "runtime",
                     "THIRD-PARTY-NOTICES.txt", "README.md", "LICENSE.md",
                     "CONTENT-NOTICE.md", "Start.cmd", "Setup.cmd",
                     "build-info.json"):
            source = staged / name
            if not source.exists():
                continue
            target = root / name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink(missing_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
    return {"installed": True, "root": str(root)}


def start_after_update(root: Path, port: int = 8765) -> None:
    """Start the program again after the files were replaced."""
    root = Path(root).resolve()
    python = root / "runtime" / "python.exe"
    if not python.is_file():
        python = Path(sys.executable)
    subprocess.Popen(
        [str(python), "-B", "-X", "utf8", "-m", "toeic_practice.launcher",
         "--port", str(port), "--no-browser"],
        cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(root / "apps" / "api" / "src")},
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
