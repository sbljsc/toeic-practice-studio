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


def test_a_source_checkout_says_it_cannot_update_itself(client):
    """A source checkout cannot replace itself, and says so."""
    response = client.post("/api/update/check", json={}, headers={
        "X-Tab-ID": "tab-update", "Origin": "http://testserver"})
    assert response.status_code == 200
    body = response.json()
    assert body["portable"] is False
    assert body["phase"] == "unsupported"
    assert body["error"]


def test_a_source_checkout_refuses_to_download_a_release(client):
    """A source checkout does not fetch a release for itself."""
    response = client.post("/api/update/download", json={}, headers={
        "X-Tab-ID": "tab-update", "Origin": "http://testserver"})
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "unsupported"
    assert body["archive"] is None


def test_the_status_carries_the_progress_of_a_running_download(client):
    """The page reads the phase and the byte counts to draw the badge."""
    body = client.get("/api/update/status").json()
    assert body["phase"] in ("idle", "unsupported")
    assert "downloaded_bytes" in body
    assert "total_bytes" in body


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


def test_a_downloaded_package_survives_a_reload(tmp_path, monkeypatch):
    """A package that was already fetched is reused, not fetched again.

    The page can be reloaded at any time, which loses the in-memory state.
    The package on disk must still be recognised, otherwise the learner is
    told to download it a second time.
    """
    from toeic_practice import update_service as service

    reference = service.UpdateService()
    work = tmp_path / ".data" / "update"
    work.mkdir(parents=True)
    archive = work / "TOEIC-Practice-Studio-0.5.0-windows-x64.zip"
    archive.write_bytes(b"already downloaded")

    monkeypatch.setattr(service, "program_root", lambda: tmp_path)
    monkeypatch.setattr(service, "is_portable", lambda: True)
    monkeypatch.setattr(service, "current_version", lambda: "0.4.0")
    monkeypatch.setattr(service.updater, "plan_update", lambda root, current: {
        "current_version": current,
        "latest_version": "0.5.0",
        "latest_tag": "v0.5.0",
        "update_available": True,
        "checked": True,
        "error": None,
    })

    fresh = service.UpdateService()
    state = fresh.check()
    assert state["phase"] == "ready"
    assert state["archive"] == str(archive)


def test_ending_a_process_works_on_windows(client):
    """Windows has no SIGKILL, so a stubborn process is ended another way."""
    from toeic_practice import update_apply

    # The helper must not reach for a signal that the platform lacks.
    assert hasattr(update_apply, "_end_process")
    source = Path(update_apply.__file__).read_text(encoding="utf-8")
    assert "SIGKILL" not in source.split("def _end_process")[1].split("def ")[0].replace(
        "signal.SIGKILL", "") or "os.name == \"nt\"" in source


def test_the_service_can_be_asked_to_stop(client):
    """The shutdown route closes the database and reports that it stopped."""
    response = client.post("/api/update/shutdown", json={}, headers={
        "X-Tab-ID": "tab-update", "Origin": "http://testserver"})
    assert response.status_code == 200
    assert response.json() == {"stopping": True}


def test_the_helper_has_every_module_it_uses():
    """A missing import only shows up when the helper runs, which is late.

    The helper is the one piece that runs while the program is being
    replaced, so a name it forgot would only appear as a failed update.
    """
    import ast
    import builtins
    from pathlib import Path

    from toeic_practice import update_apply

    source = Path(update_apply.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
    # Only module-level names are imported; a local variable is not a
    # missing import.
    assigned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assigned.add(node.id)
    used = {node.value.id for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)}
    missing = sorted(name for name in used - imported - assigned
                     if not hasattr(builtins, name))
    assert not missing, f"update_apply uses names it does not import: {missing}"


def test_the_update_waits_for_the_port_the_server_really_uses():
    """The helper must watch the port the program runs on, not the default.

    A program started on another port would otherwise never release the
    one the helper was watching, and the update would never happen.
    """
    from toeic_practice import launcher
    from toeic_practice import update_service as service

    launcher.RUNNING_PORT = 8799
    try:
        assert service.running_port() == 8799
    finally:
        launcher.RUNNING_PORT = 0


def test_the_api_and_the_launcher_share_the_running_port():
    """The launcher runs as __main__, the API imports it by name.

    Those are two module objects, so anything the launcher records has to
    be kept somewhere both of them can read.
    """
    from toeic_practice import runtime_state
    from toeic_practice import update_service

    runtime_state.set_running(object(), 8799)
    try:
        assert runtime_state.RUNNING_PORT == 8799
        assert update_service.running_port() == 8799
    finally:
        runtime_state.RUNNING_PORT = 0
        runtime_state.RUNNING_SERVER = None


def test_the_old_runtime_is_moved_aside_and_cleaned_later(tmp_path):
    """The helper runs from the runtime folder, so it cannot delete it.

    The old folder is renamed and removed once the program has started
    again, which is what makes an update possible at all on Windows.
    """
    from toeic_practice import updater

    program = tmp_path / "program"
    (program / "runtime").mkdir(parents=True)
    (program / "runtime" / "python.exe").write_bytes(b"interpreter")
    (program / "Start.cmd").write_text("@echo off", encoding="utf-8")
    (program / ".data").mkdir()
    (program / ".data" / "practice.sqlite3").write_bytes(b"LEARNER DATA")

    archive = _make_release(tmp_path, "0.5.0")
    updater.install_staged(program, archive)

    # The new runtime is in place, and the old one is set aside.
    assert (program / "runtime" / "python.exe").is_file()
    assert (program / ".data" / "practice.sqlite3").read_bytes() == b"LEARNER DATA"
    assert (program / "content" / "bank.txt").read_text(encoding="utf-8") == "new bank"

    removed = updater.clean_aside_folders(program)
    assert "runtime.old" in removed
    assert not (program / "runtime.old").exists()
