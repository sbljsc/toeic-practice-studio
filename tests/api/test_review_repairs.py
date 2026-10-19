"""Regression cases from the independent backend review; isolated fixtures only."""
import io
import hashlib
import json
import sqlite3
import threading
import uuid
import zipfile

import pytest

from toeic_practice.attempts import AttemptService
from toeic_practice.clock import ManualClock
from toeic_practice.errors import ApiError


TAB = "review-tab"
HEADERS = {"X-Tab-ID": TAB, "Origin": "http://testserver"}


def create(svc, scope="part", mode="practice", seconds=60, parts=None):
    return svc.attempts.create({"exam_ids": ["test-01"], "scope": scope,
        "mode": mode, "parts": parts or [5], "question_filter": "all",
        "timer": {"kind": "countdown", "duration_seconds": seconds}})


def start(svc, a):
    return svc.attempts.start(a["id"], TAB, True)


def answer(svc, a, q=None, mutation=None, option="B", revision=0):
    q = q or a["questions"][0]
    return svc.attempts.put_answer(a["id"], q["id"], TAB,
        {"option_id": option, "revision": revision,
         "mutation_id": mutation or str(uuid.uuid4())})


@pytest.mark.parametrize("scope,elapsed,offline,expected", [
    ("listening", 10, 20, 90000), ("reading", 10, 20, 4470000),
    ("full", 10, 125, 4485000), ("full", 125, 10, 4485000),
    ("full", 10, 5000, None)])
@pytest.mark.parametrize("new_base", [5.0, 9_000_000.0])
def test_running_restart_reanchors(app_services, clock, scope, elapsed, offline, expected, new_base):
    svc = app_services
    a = create(svc, scope=scope, mode="exam")
    start(svc, a)
    clock.advance(elapsed)
    svc.attempts.get(a["id"])  # durable checkpoint before process exit
    replacement = ManualClock(new_base)
    replacement.wall_now = clock.wall() + offline
    recovered = AttemptService(svc.store, svc.library, replacement)
    state = recovered.get(a["id"])
    assert state["integrity"] == "interrupted"
    assert state["interruptions"][-1]["reason"] == "server_restart"
    if expected is None:
        assert state["status"] == "expired"
        assert recovered.report(a["id"])["attempt"]["integrity"] == "interrupted"
    else:
        assert state["status"] == "running"
        assert state["timing"]["remaining_ms"] == expected
        again = recovered.get(a["id"])
        assert len(again["interruptions"]) == 1


def test_restart_wall_rollback_never_regrants_time(app_services, clock):
    a = create(app_services)
    start(app_services, a)
    clock.advance(10)
    app_services.attempts.get(a["id"])
    replacement = ManualClock(1)
    replacement.wall_now = clock.wall() - 3600
    recovered = AttemptService(app_services.store, app_services.library, replacement)
    state = recovered.get(a["id"])
    assert state["integrity"] == "interrupted"
    assert state["status"] == "expired"  # unknowable offline elapsed: fail closed


@pytest.mark.parametrize("boundary", ["expiry", "listening"])
def test_rejected_save_commits_authoritative_transition(app_services, clock, boundary):
    a = create(app_services, scope="full" if boundary == "listening" else "part",
               mode="exam" if boundary == "listening" else "practice")
    start(app_services, a)
    clock.advance(120 if boundary == "listening" else 60)
    with pytest.raises(ApiError) as error:
        answer(app_services, a)
    assert error.value.status_code == (409 if boundary == "listening" else 410)
    row = app_services.store.query_one("SELECT * FROM attempts WHERE id=?", (a["id"],))
    assert row["phase"] == ("reading" if boundary == "listening" else "finished")
    if boundary == "expiry":
        assert row["status"] == "expired" and row["report"]
    assert not app_services.store.query("SELECT * FROM answers")


def test_conversion_survives_reload_and_cannot_evade_expiry(app_services, clock):
    a = create(app_services, scope="reading", mode="exam")
    start(app_services, a)
    app_services.attempts.interrupt(a["id"], TAB, "audio_failure")
    app_services.attempts.continue_practice(a["id"], TAB)
    state = app_services.attempts.get(a["id"])
    assert (state["mode"], state["original_mode"], state["status"]) == ("practice", "exam", "paused")
    assert state["timing"]["can_pause"] and state["integrity"] == "interrupted"
    b = create(app_services, scope="reading", mode="exam")
    start(app_services, b)
    app_services.attempts.interrupt(b["id"], TAB, "failure")
    clock.advance(4500)
    with pytest.raises(ApiError) as err:
        app_services.attempts.continue_practice(b["id"], TAB)
    assert err.value.status_code == 410
    assert app_services.store.query_one("SELECT status FROM attempts WHERE id=?", (b["id"],))["status"] == "expired"


def test_mutation_identity_includes_attempt_and_payload(app_services):
    a, b = create(app_services), create(app_services)
    start(app_services, a)
    start(app_services, b)
    mutation = str(uuid.uuid4())
    answer(app_services, a, mutation=mutation)
    assert answer(app_services, a, mutation=mutation)["answers"][a["questions"][0]["id"]]["revision"] == 1
    for target, option in [(b, "B"), (a, "C")]:
        with pytest.raises(ApiError) as err:
            answer(app_services, target, mutation=mutation, option=option)
        assert err.value.code == "mutation_conflict"
    assert app_services.attempts.get(b["id"])["answers"] == {}


@pytest.mark.parametrize("part", [1, 2])
def test_private_snapshot_and_phase_scope(app_services, part):
    a = create(app_services, parts=[part])
    assert a["parts"] == [part]
    assert a["timing"]["phase_question_ids"] == [q["id"] for q in a["questions"]]
    assert a["questions"][0]["stem"] == ""
    assert all(o["text"] == "" for o in a["questions"][0]["options"])
    start(app_services, a)
    report = app_services.attempts.submit(a["id"], TAB)
    assert report["questions"][0]["stem"]
    assert report["questions"][0]["options"][0]["text"]
    full = create(app_services, scope="full", mode="exam")
    assert full["parts"] == list(range(1, 8))
    assert len(full["timing"]["phase_question_ids"]) == 100


def test_start_rechecks_actual_media_and_cues(app_services):
    a = create(app_services, parts=[1])
    path, _ = app_services.library.asset_path(a["audio_queue"][0]["asset_id"])
    path.unlink()
    with pytest.raises(ApiError) as err:
        start(app_services, a)
    assert err.value.code == "content_not_ready"
    assert app_services.attempts.get(a["id"])["status"] == "ready"


def test_same_origin_compares_scheme_and_normalized_port(client):
    wrong = client.patch("/api/settings", json={"vocabulary_threshold": 4},
                         headers={"Origin": "https://testserver"})
    assert wrong.status_code == 403
    valid = client.patch("/api/settings", json={"vocabulary_threshold": 4},
                         headers={"Origin": "http://testserver:80"})
    assert valid.status_code == 200


def test_runtime_rejects_test_host_and_origin_zero_port(client):
    client.app.state.allow_test_host = False
    result = client.patch("/api/settings", json={"vocabulary_threshold": 4},
                          headers={"Origin": "http://testserver"})
    assert result.status_code == 403
    client.app.state.allow_test_host = True
    result = client.patch("/api/settings", json={"vocabulary_threshold": 4},
                          headers={"Origin": "http://testserver:0"})
    assert result.status_code == 403


def test_same_origin_normalizes_ipv6(client):
    result = client.patch("/api/settings", json={"vocabulary_threshold": 4},
        headers={"Host": "[0:0:0:0:0:0:0:1]:80", "Origin": "http://[::1]"})
    assert result.status_code == 200


def test_statistics_separates_valid_exams_and_practice(client):
    svc = client.app.state.services
    for mode, interrupted in [("exam", False), ("exam", True), ("practice", False)]:
        a = create(svc, scope="reading", mode=mode)
        start(svc, a)
        if interrupted:
            svc.attempts.interrupt(a["id"], TAB, "failure")
        svc.attempts.submit(a["id"], TAB)
    stats = client.get("/api/statistics").json()
    assert sum(p["total"] for p in stats["by_part"]) == 100
    assert stats["valid_exam_completed_count"] == 1
    assert stats["practice_completed_count"] == 1
    assert stats["interrupted_completed_count"] == 1
    assert all("integrity" in r for r in stats["first"] + stats["recent"])


def test_key_correction_only_invalidates_affected_question(client, library_root):
    svc = client.app.state.services
    a = create(svc)
    start(svc, a)
    for q in a["questions"][:2]:
        answer(svc, a, q=q, option="D")
    svc.attempts.submit(a["id"], TAB)
    for q in a["questions"][:2]:
        svc.attempts.put_review(a["id"], q["id"], {"causes": ["meaning"],
            "words": [{"term": "repairword", "causal": True}]})
    before = svc.library.library_version()
    path = library_root / "exams/test-01.json"
    exam = json.loads(path.read_text())
    exam["questions"][100]["answer"] = "D"
    path.write_text(json.dumps(exam), encoding="utf-8")
    svc.library.load()
    assert before != svc.library.library_version()
    entry = client.get("/api/vocabulary").json()["entries"][0]
    assert entry["question_count"] == 1 and entry["lifetime_question_count"] == 2
    patched = client.patch("/api/vocabulary/repairword%7C%7Cmeaning",
        json={"manual_required": True}, headers=HEADERS)
    assert patched.status_code == 200
    assert patched.json()["entries"][0]["question_count"] == 1
    wrong = svc.attempts.create({"exam_ids": ["test-01"], "scope": "part", "parts": [5],
        "mode": "practice", "question_filter": "wrong", "timer": {"kind": "none"}})
    assert [q["number"] for q in wrong["questions"]] == [102]
    assert svc.attempts.report(a["id"])["summary"]["wrong"] == 2
    # A manifest-only revision must retain the still-valid evidence.
    manifest = library_root / "manifest.json"
    data = json.loads(manifest.read_text()); data["version"] = "new-label"
    manifest.write_text(json.dumps(data)); svc.library.load()
    assert client.get("/api/vocabulary").json()["entries"][0]["question_count"] == 1


def test_complete_backup_download_restore_and_reload(client, library_root):
    svc = client.app.state.services
    a = create(svc); start(svc, a); answer(svc, a)
    svc.attempts.submit(a["id"], TAB)
    svc.attempts.put_review(a["id"], a["questions"][0]["id"],
        {"causes": ["meaning"], "words": [{"term": "bundleword", "causal": True}]})
    backup = svc.backups.create(True)
    downloaded = client.get(backup["download_url"])
    assert zipfile.is_zipfile(io.BytesIO(downloaded.content))
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as z:
        assert {"backup.json", "state.sqlite3", "library.zip"} <= set(z.namelist())
    media = library_root / "media/test-01.mp3"
    original = media.read_bytes(); media.write_bytes(b"changed")
    exam_path = library_root / "exams/test-01.json"
    exam = json.loads(exam_path.read_text()); exam["questions"][100]["answer"] = "D"
    exam_path.write_text(json.dumps(exam)); svc.library.load()
    svc.backups.restore(backup["id"], True)
    assert media.read_bytes() == original
    assert svc.library is svc.attempts.library is svc.backups.library
    assert svc.library.exams["test-01"].questions[100]["answer"] == "A"
    assert svc.attempts.report(a["id"])["summary"]["wrong"] == 1
    assert client.get("/api/vocabulary").json()["entries"][0]["question_count"] == 1


@pytest.mark.parametrize("kind", ["archive", "version"])
def test_restore_validates_archive_and_version_before_writes(app_services, kind):
    svc = app_services
    backup = svc.backups.create(True)
    if kind == "archive":
        svc.backups._archive_path(backup["id"]).write_bytes(b"not zip")
    else:
        p = svc.backups._descriptor_path(backup["id"])
        meta = json.loads(p.read_text()); meta["library_version"] = "incompatible"
        p.write_text(json.dumps(meta))
    with pytest.raises(ApiError):
        svc.backups.restore(backup["id"], True)


def test_restore_exclusive_guard_precedes_rollback_snapshot(app_services, monkeypatch):
    svc = app_services
    backup = svc.backups.create(False)
    a = create(svc)
    entered, finished = threading.Event(), threading.Event()
    original_create = svc.backups.create
    worker = None

    def create_rollback(*args, **kwargs):
        nonlocal worker
        def concurrent_start():
            entered.set()
            try:
                start(svc, a)
            except ApiError:
                pass  # restored database legitimately has no such attempt
            finally:
                finished.set()
        worker = threading.Thread(target=concurrent_start)
        worker.start()
        assert entered.wait(2)
        assert not finished.wait(.1), "writer interleaved before rollback/restore"
        return original_create(*args, **kwargs)

    monkeypatch.setattr(svc.backups, "create", create_rollback)
    try:
        result = svc.backups.restore(backup["id"], True)
    finally:
        if worker:
            worker.join(3)
    assert finished.is_set()
    rb = sqlite3.connect(svc.backups._file_path(result["rollback_backup_id"]))
    try:
        assert rb.execute("SELECT status FROM attempts WHERE id=?", (a["id"],)).fetchone()[0] == "ready"
    finally:
        rb.close()


@pytest.mark.parametrize("failure", ["database", "library_reload"])
def test_restore_failure_recovers_database_library_and_service(app_services, monkeypatch, failure):
    svc = app_services
    backup = svc.backups.create(True)
    a = create(svc); start(svc, a); answer(svc, a)
    svc.attempts.submit(a["id"], TAB)
    media = svc.library.root / "media/test-01.mp3"
    media.write_bytes(b"pre-restore-media")
    if failure == "database":
        original = svc.backups._copy_database
        count = 0
        def injected(path):
            nonlocal count
            original(path)  # simulate failure after an actual destructive write
            count += 1
            if count == 1:
                raise RuntimeError("injected database failure")
        monkeypatch.setattr(svc.backups, "_copy_database", injected)
    else:
        original = svc.library.load
        count = 0
        def injected():
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("injected library reload failure")
            original()
        monkeypatch.setattr(svc.library, "load", injected)
    with pytest.raises(RuntimeError):
        svc.backups.restore(backup["id"], True)
    assert media.read_bytes() == b"pre-restore-media"
    assert svc.attempts.report(a["id"])["summary"]["wrong"] == 1
    assert create(svc)["status"] == "ready"


@pytest.mark.parametrize("member", ["../escape", "/absolute", "C:/escape", "media\\escape", "MEDIA/test-01.mp3", "sources/CON"])
def test_restore_rejects_unsafe_archive_members_before_writes(app_services, member):
    svc = app_services
    backup = svc.backups.create(True)
    archive = svc.backups._archive_path(backup["id"])
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr(member, b"unsafe")
    meta_path = svc.backups._descriptor_path(backup["id"])
    meta = json.loads(meta_path.read_text())
    meta["library_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    meta["library_files"][member] = hashlib.sha256(b"unsafe").hexdigest()
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(ApiError) as err:
        svc.backups.restore(backup["id"], True)
    assert err.value.code == "library_archive_invalid"
    assert not (svc.library.root.parent / "escape").exists()
    assert create(svc)["status"] == "ready"


def test_data_only_restore_rejects_other_library_version(app_services):
    svc = app_services
    backup = svc.backups.create(False)
    svc.library.exams["test-01"].questions[100]["answer"] = "D"
    with pytest.raises(ApiError) as err:
        svc.backups.restore(backup["id"], True)
    assert err.value.code == "library_version_mismatch"


def test_invalid_cue_does_not_start_clock(app_services):
    svc = app_services
    a = create(svc, parts=[1])
    with svc.store.transaction() as conn:
        row = conn.execute("SELECT audio_queue FROM attempts WHERE id=?", (a["id"],)).fetchone()
        queue = json.loads(row["audio_queue"]); queue[0]["end_seconds"] = 9999
        conn.execute("UPDATE attempts SET audio_queue=? WHERE id=?", (json.dumps(queue), a["id"]))
    with pytest.raises(ApiError) as err:
        start(svc, a)
    assert err.value.code == "content_not_ready"
    assert svc.attempts.get(a["id"])["status"] == "ready"


def test_converted_full_practice_resume_keeps_phase_overshoot(app_services, clock):
    svc = app_services
    a = create(svc, scope="full", mode="exam"); start(svc, a)
    clock.advance(30)
    svc.attempts.interrupt(a["id"], TAB, "media_failure")
    svc.attempts.continue_practice(a["id"], TAB)
    clock.advance(1000)  # practice pause excludes this span
    svc.attempts.resume(a["id"], TAB)
    clock.advance(95)  # listening finishes after 90s; reading has spent 5s
    state = svc.attempts.get(a["id"])
    assert state["timing"]["phase"] == "reading"
    assert state["timing"]["remaining_ms"] == 4495000
    assert state["timing"]["elapsed_ms"] == 125000


def test_corrupt_download_bundle_rejected(app_services):
    svc = app_services
    backup = svc.backups.create(True)
    svc.backups._bundle_path(backup["id"]).write_bytes(b"corrupted download")
    with pytest.raises(ApiError) as err:
        svc.backups.restore(backup["id"], True)
    assert err.value.code == "bundle_checksum_mismatch"


def test_missing_selected_question_file_does_not_start(app_services):
    a = create(app_services)
    (app_services.library.root / "exams/test-01.json").unlink()
    with pytest.raises(ApiError) as err:
        start(app_services, a)
    assert err.value.code == "content_not_ready"
