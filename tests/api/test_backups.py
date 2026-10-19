"""Backup/restore roundtrip, active-guard, and rejection-path tests."""
import json
import sqlite3
import uuid

import pytest

TAB = "tab-backup"


def hdr():
    return {"X-Tab-ID": TAB, "Origin": "http://testserver"}


def _closed_attempt(client):
    attempt = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "part", "parts": [5],
        "mode": "practice", "timer": {"kind": "none"}, "question_filter": "all"},
        headers=hdr()).json()
    client.post(f"/api/attempts/{attempt['id']}/claim",
                json={"takeover": False}, headers=hdr())
    client.post(f"/api/attempts/{attempt['id']}/start",
                json={"media_ready": True}, headers=hdr())
    qid = attempt["questions"][0]["id"]
    client.put(f"/api/attempts/{attempt['id']}/answers/{qid}",
               json={"option_id": "A", "revision": 0, "mutation_id": str(uuid.uuid4())},
               headers=hdr())
    client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr())
    return attempt


def test_backup_roundtrip_restores_state(client):
    attempt = _closed_attempt(client)
    client.patch("/api/settings", json={"vocabulary_threshold": 7}, headers=hdr())
    backup = client.post("/api/backups", json={"include_library": False},
                         headers=hdr()).json()
    # mutate state after backup
    client.patch("/api/settings", json={"vocabulary_threshold": 2}, headers=hdr())
    assert client.get("/api/settings").json()["vocabulary_threshold"] == 2
    restore = client.post(f"/api/backups/{backup['id']}/restore",
                          json={"confirm": True}, headers=hdr())
    assert restore.status_code == 200, restore.text
    assert restore.json()["rollback_backup_id"]
    # store reconnected and serving restored data without restart
    assert client.get("/api/settings").json()["vocabulary_threshold"] == 7
    report = client.get(f"/api/attempts/{attempt['id']}/report")
    assert report.status_code == 200
    assert report.json()["summary"]["correct"] == 1


def test_restore_rejected_with_active_timer(client):
    attempt = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "part", "parts": [5],
        "mode": "practice", "timer": {"kind": "countdown", "duration_seconds": 600},
        "question_filter": "all"}, headers=hdr()).json()
    client.post(f"/api/attempts/{attempt['id']}/claim",
                json={"takeover": False}, headers=hdr())
    client.post(f"/api/attempts/{attempt['id']}/start",
                json={"media_ready": True}, headers=hdr())
    backup = client.post("/api/backups", json={"include_library": False},
                         headers=hdr()).json()
    blocked = client.post(f"/api/backups/{backup['id']}/restore",
                          json={"confirm": True}, headers=hdr())
    assert blocked.status_code == 409
    client.post(f"/api/attempts/{attempt['id']}/submit", json={}, headers=hdr())
    ok = client.post(f"/api/backups/{backup['id']}/restore",
                     json={"confirm": True}, headers=hdr())
    assert ok.status_code == 200


def test_restore_requires_confirm(client):
    backup = client.post("/api/backups", json={"include_library": False},
                         headers=hdr()).json()
    resp = client.post(f"/api/backups/{backup['id']}/restore",
                       json={"confirm": False}, headers=hdr())
    assert resp.status_code == 400


def test_restore_rejects_checksum_mismatch(client, tmp_path):
    backup = client.post("/api/backups", json={"include_library": False},
                         headers=hdr()).json()
    db_file = tmp_path / "backups" / f"{backup['id']}.sqlite3"
    blob = bytearray(db_file.read_bytes())
    blob[-100] ^= 0xFF  # corrupt one byte without touching the descriptor
    db_file.write_bytes(bytes(blob))
    resp = client.post(f"/api/backups/{backup['id']}/restore",
                       json={"confirm": True}, headers=hdr())
    assert resp.status_code == 409
    assert "checksum" in resp.json().get("code", "")


def test_restore_rejects_schema_mismatch(client, tmp_path):
    backup = client.post("/api/backups", json={"include_library": False},
                         headers=hdr()).json()
    import hashlib
    db_file = tmp_path / "backups" / f"{backup['id']}.sqlite3"
    conn = sqlite3.connect(str(db_file))
    conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    meta_file = tmp_path / "backups" / f"{backup['id']}.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta["schema_version"] = 99
    meta["sha256"] = hashlib.sha256(db_file.read_bytes()).hexdigest()
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    resp = client.post(f"/api/backups/{backup['id']}/restore",
                       json={"confirm": True}, headers=hdr())
    assert resp.status_code == 409
    assert "schema" in resp.json().get("code", "")


def test_backup_download_and_listing(client):
    backup = client.post("/api/backups", json={"include_library": False},
                         headers=hdr()).json()
    listing = client.get("/api/backups").json()
    assert any(b["id"] == backup["id"] for b in listing["backups"])
    download = client.get(f"/api/backups/{backup['id']}/download")
    assert download.status_code == 200
    assert download.content[:16].startswith(b"SQLite format 3")


def test_backup_while_active_attempt_is_consistent(client):
    attempt = client.post("/api/attempts", json={
        "exam_ids": ["test-01"], "scope": "part", "parts": [5],
        "mode": "practice", "timer": {"kind": "countdown", "duration_seconds": 600},
        "question_filter": "all"}, headers=hdr()).json()
    client.post(f"/api/attempts/{attempt['id']}/claim",
                json={"takeover": False}, headers=hdr())
    client.post(f"/api/attempts/{attempt['id']}/start",
                json={"media_ready": True}, headers=hdr())
    backup = client.post("/api/backups", json={"include_library": False},
                         headers=hdr()).json()
    assert backup["id"]
    assert backup["size_bytes"] > 0


def test_include_library_archives_bytes(client, tmp_path):
    backup = client.post("/api/backups", json={"include_library": True},
                         headers=hdr()).json()
    archive = tmp_path / "backups" / f"{backup['id']}.library.zip"
    assert archive.is_file()
    import zipfile
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert "manifest.json" in names
    assert "media/test-01.mp3" in names