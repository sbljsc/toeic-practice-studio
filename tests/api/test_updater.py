"""The update finds a release, verifies it and installs it without touching
the learner's data."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from toeic_practice import updater
from toeic_practice.update_apply import port_is_free, wait_for_port


def test_a_version_is_read_with_or_without_the_v():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.2") is None
    assert updater.parse_version("") is None
    assert updater.version_text((0, 4, 0)) == "0.4.0"


def test_a_checksum_line_is_read():
    digest = "a" * 64
    assert updater.read_checksum(f"{digest}  file.zip\n") == digest
    assert updater.read_checksum("not a checksum") == ""


def test_the_asset_addresses_follow_the_release_tag():
    assets = updater.release_assets((0, 4, 0))
    assert assets["archive"].endswith(
        "/releases/download/v0.4.0/"
        "TOEIC-Practice-Studio-0.4.0-windows-x64.zip")
    assert assets["checksum"].endswith(".zip.sha256")


def _make_release(directory: Path, version: str) -> Path:
    """A small stand-in for a release ZIP."""
    root = directory / "TOEIC-Practice-Studio"
    (root / "apps" / "web" / "dist").mkdir(parents=True)
    (root / "content").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "apps" / "web" / "dist" / "index.html").write_text("<html>", encoding="utf-8")
    (root / "content" / "bank.txt").write_text("new bank", encoding="utf-8")
    (root / "docs" / "guide.md").write_text("new guide", encoding="utf-8")
    (root / "Start.cmd").write_text("@echo off", encoding="utf-8")
    (root / "build-info.json").write_text(
        json.dumps({"version": version}), encoding="utf-8")
    archive = directory / "release.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(directory))
    return archive


def test_a_staged_release_is_installed_over_the_old_files(tmp_path):
    """The program files are replaced, the learner's data is not."""
    program = tmp_path / "program"
    program.mkdir()
    (program / "Start.cmd").write_text("@echo off\nrem old", encoding="utf-8")
    (program / "content").mkdir()
    (program / "content" / "bank.txt").write_text("old bank", encoding="utf-8")
    (program / "apps").mkdir()
    (program / "apps" / "old.txt").write_text("old", encoding="utf-8")
    data = program / ".data"
    data.mkdir()
    (data / "practice.sqlite3").write_bytes(b"learner data")

    archive = _make_release(tmp_path, "0.4.0")
    updater.install_staged(program, archive)

    # The new files are in place.
    assert (program / "content" / "bank.txt").read_text(encoding="utf-8") == "new bank"
    assert (program / "apps" / "web" / "dist" / "index.html").is_file()
    assert (program / "build-info.json").is_file()
    # A file the new release does not carry is gone.
    assert not (program / "apps" / "old.txt").exists()
    # The learner's data is untouched.
    assert (data / "practice.sqlite3").read_bytes() == b"learner data"


def test_a_release_with_an_unsafe_path_is_refused(tmp_path):
    """A ZIP that tries to escape the folder is not unpacked."""
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../escaped.txt", "no")
    with pytest.raises(ValueError):
        updater.extract_release(archive, tmp_path / "out")


def test_a_release_without_a_start_file_is_refused(tmp_path):
    """A ZIP that is not the program is not installed."""
    archive = tmp_path / "other.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("something/readme.txt", "no")
    with pytest.raises(ValueError):
        updater.extract_release(archive, tmp_path / "out")


def test_a_downloaded_file_is_checked_by_its_digest(tmp_path):
    """The digest of a file is the one the release published."""
    target = tmp_path / "file.bin"
    target.write_bytes(b"hello")
    assert updater.file_sha256(target) == hashlib.sha256(b"hello").hexdigest()


def test_the_plan_says_when_the_running_version_is_the_newest():
    """A release that is not newer does not offer an update."""
    plan = updater.plan_update(Path("."), "99.0.0")
    assert plan["update_available"] is False


def test_a_free_port_is_recognised():
    """The helper waits for the old service to let go of the port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert port_is_free(port) is False
    assert port_is_free(port) is True
    assert wait_for_port(port, timeout=2.0) is True


def test_the_update_status_endpoint_answers(client):
    """The status endpoint reports what it can, even without a network."""
    response = client.get("/api/update/status")
    assert response.status_code == 200
    body = response.json()
    assert "current_version" in body
    assert "update_available" in body
    assert "portable" in body
    # A source checkout cannot replace itself, and says so.
    assert body["portable"] is False


def test_staging_an_update_needs_a_portable_install(client):
    """A source checkout refuses to download a release for itself."""
    response = client.post("/api/update/stage", json={}, headers={
        "X-Tab-ID": "tab-update", "Origin": "http://testserver"})
    assert response.status_code == 503
    assert response.json()["code"] == "update_stage_failed"


def test_installing_without_an_archive_is_refused(client):
    """A request without a downloaded package is rejected."""
    response = client.post("/api/update/install", json={"archive": "  "}, headers={
        "X-Tab-ID": "tab-update", "Origin": "http://testserver"})
    assert response.status_code == 400
    assert response.json()["code"] == "missing_archive"


def test_installing_a_package_that_is_not_there_is_refused(client):
    """A package that was never downloaded is refused, not ignored."""
    response = client.post("/api/update/install", json={"archive": "nowhere.zip"}, headers={
        "X-Tab-ID": "tab-update", "Origin": "http://testserver"})
    assert response.status_code == 503
    assert response.json()["code"] == "update_install_failed"
