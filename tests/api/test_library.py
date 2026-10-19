"""Library loader readiness, cue merge and missing-library behavior."""
import json
from pathlib import Path

import pytest

from toeic_practice.library import Library


def _write_minimal(root: Path, *, validated=True, cues=True, media=True) -> Path:
    (root / "exams").mkdir(parents=True, exist_ok=True)
    (root / "media").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    if media:
        (root / "media" / "m.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)
    manifest = {
        "schema_version": 1, "version": "v9",
        "exams": [{"id": "e1", "title": "E1", "version": "v9",
                   "path": "exams/e1.json", "question_count": 200,
                   "validated": validated}],
        "assets": [{"id": "audio-e1", "path": "media/m.mp3",
                    "media_type": "audio/mpeg"}],
        "sources": [],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    questions, groups = [], []
    ranges = {1: (1, 6), 2: (7, 31), 3: (32, 70), 4: (71, 100),
              5: (101, 130), 6: (131, 146), 7: (147, 200)}
    for part, (lo, hi) in ranges.items():
        for n in range(lo, hi + 1):
            gid = f"g{n}"
            n_opt = 3 if part == 2 else 4
            questions.append({
                "id": f"q{n}", "canonical_id": f"c{n}", "number": n,
                "part": part, "section": "listening" if part <= 4 else "reading",
                "group_id": gid, "stem": "s",
                "options": [{"id": chr(65 + i), "text": "t"} for i in range(n_opt)],
                "answer": "A", "source_pages": [n],
                "explanation": {"text": "e", "source_pages": [n]},
            })
            groups.append({"id": gid, "part": part,
                           "section": "listening" if part <= 4 else "reading",
                           "question_ids": [f"q{n}"], "materials": [],
                           "source_pages": [n]})
    (root / "exams" / "e1.json").write_text(json.dumps({
        "schema_version": 1, "id": "e1", "title": "E1", "version": "v9",
        "questions": questions, "groups": groups,
        "audio": {"asset_id": "audio-e1", "path": "media/m.mp3",
                  "duration_seconds": 120.0, "parts": []},
    }), encoding="utf-8")
    if cues:
        (root / "audio-cues.json").write_text(json.dumps({
            "schema_version": 1,
            "exams": {"e1": {"verified": True, "source_duration_seconds": 120.0,
                             "full_start_seconds": 0.0, "full_end_seconds": 120.0,
                             "parts": [{"part": p, "start_seconds": 0.0,
                                        "end_seconds": 30.0, "verified": True}
                                       for p in (1, 2, 3, 4)],
                             "groups": []}},
        }), encoding="utf-8")
    return root


def test_missing_library_is_explicitly_unavailable(tmp_path):
    lib = Library(tmp_path / "nope")
    lib.load()
    assert not lib.available
    assert lib.load_error


def test_ready_exam(tmp_path):
    root = _write_minimal(tmp_path / "lib")
    lib = Library(root)
    lib.load()
    assert lib.available
    assert lib.exam_ready_reason(lib.exams["e1"]) is None


def test_unvalidated_exam_visible_with_reason(tmp_path):
    root = _write_minimal(tmp_path / "lib", validated=False)
    lib = Library(root)
    lib.load()
    exam = lib.exams["e1"]
    assert lib.exam_ready_reason(exam) is not None


def test_missing_cues_block_readiness(tmp_path):
    root = _write_minimal(tmp_path / "lib", cues=False)
    lib = Library(root)
    lib.load()
    assert lib.exam_ready_reason(lib.exams["e1"]) is not None


def test_cue_end_clamped_to_real_duration(tmp_path):
    root = _write_minimal(tmp_path / "lib")
    cues = json.loads((root / "audio-cues.json").read_text(encoding="utf-8"))
    cues["exams"]["e1"]["full_end_seconds"] = 100.0  # shorter than the 120s file
    (root / "audio-cues.json").write_text(json.dumps(cues), encoding="utf-8")
    lib = Library(root)
    lib.load()
    assert lib.exams["e1"].full_end_seconds == 120.0


def _set_exam_window(root, *, end=110.0, closing_end=109.8, verified=True):
    path = root / "audio-cues.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cue = data["exams"]["e1"]
    cue.update(full_start_seconds=10.0, full_end_seconds=end)
    cue["parts"] = [
        {"part": p, "start_seconds": max(10.0, (p - 1) * 30.0),
         "end_seconds": min(end, p * 30.0), "verified": True}
        for p in (1, 2, 3, 4)
    ]
    cue["exam_window"] = {
        "verified": verified, "start_seconds": 10.0, "end_seconds": end,
        "opening_start_seconds": 10.1,
        "closing_start_seconds": 108.0, "closing_end_seconds": closing_end,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_verified_exam_window_excludes_packaging_without_changing_source(tmp_path):
    root = _write_minimal(tmp_path / "lib")
    original = (root / "media/m.mp3").read_bytes()
    _set_exam_window(root)
    lib = Library(root)
    lib.load()
    exam = lib.exams["e1"]
    assert lib.exam_ready_reason(exam) is None
    assert exam.full_start_seconds == 10.0
    assert exam.full_end_seconds == 110.0
    assert exam.listening_seconds == 100.0
    assert (root / "media/m.mp3").read_bytes() == original


@pytest.mark.parametrize("changes", [
    {"end": 100.0},  # would clip the spoken closing marker
    {"end": 125.0},  # outside original media
    {"end": float("nan")},
    {"verified": False},
])
def test_invalid_exam_window_is_unready_instead_of_silently_cutting_audio(tmp_path, changes):
    root = _write_minimal(tmp_path / "lib")
    _set_exam_window(root, **changes)
    lib = Library(root)
    lib.load()
    assert lib.exam_ready_reason(lib.exams["e1"]) is not None
    assert 0 <= lib.exams["e1"].listening_seconds <= 120


def test_exam_window_cannot_cut_registered_material(tmp_path):
    root = _write_minimal(tmp_path / "lib")
    _set_exam_window(root)
    path = root / "audio-cues.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["exams"]["e1"]["groups"] = [{
        "part": 4, "first_question": 100, "last_question": 100,
        "start_seconds": 105, "end_seconds": 115, "verified": True,
    }]
    path.write_text(json.dumps(data), encoding="utf-8")
    lib = Library(root)
    lib.load()
    assert lib.exam_ready_reason(lib.exams["e1"]) is not None


def test_window_is_used_for_phase_budget_while_reading_stays_75_minutes(tmp_path):
    from toeic_practice.attempts import AttemptService
    from toeic_practice.clock import ManualClock
    from toeic_practice.store import Store

    root = _write_minimal(tmp_path / "lib")
    _set_exam_window(root)
    library = Library(root)
    library.load()
    clock = ManualClock()
    svc = AttemptService(Store(tmp_path / "window.sqlite3"), library, clock)
    attempt = svc.create({"exam_ids": ["e1"], "scope": "full", "mode": "exam",
                          "timer": {"kind": "none"}, "question_filter": "all"})
    queue = attempt["audio_queue"]
    assert [(row["start_seconds"], row["end_seconds"]) for row in queue] == [(10, 110)]
    svc.claim(attempt["id"], "window-tab", False)
    svc.start(attempt["id"], "window-tab", True)
    assert svc.clock_state(attempt["id"])["timing"]["remaining_ms"] == 100000
    clock.advance(100)
    state = svc.clock_state(attempt["id"])
    assert state["timing"]["phase"] == "reading"
    assert state["timing"]["remaining_ms"] == 4500000


def test_catalog_distinguishes_effective_exam_duration_from_original_file(tmp_path):
    from fastapi.testclient import TestClient
    from toeic_practice.app import create_app
    from toeic_practice.store import Store

    root = _write_minimal(tmp_path / "lib")
    _set_exam_window(root)
    app = create_app(library=Library(root), store=Store(tmp_path / "catalog.sqlite3"),
                     backup_root=tmp_path / "backups", serve_web=False, allow_test_host=True)
    response = TestClient(app).get("/api/exams")
    assert response.status_code == 200
    exam = response.json()["exams"][0]
    assert exam["audio_duration_seconds"] == 120
    assert exam["exam_audio_duration_seconds"] == 100


def test_asset_path_traversal_rejected(tmp_path):
    root = _write_minimal(tmp_path / "lib")
    lib = Library(root)
    lib.load()
    with pytest.raises(KeyError):
        lib.asset_path("../manifest")
    with pytest.raises(KeyError):
        lib.asset_path("not-registered")
    path, media = lib.asset_path("audio-e1")
    assert media == "audio/mpeg"
    assert path.is_file()
