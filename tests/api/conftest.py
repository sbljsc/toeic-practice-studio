"""Shared fixtures: synthetic library + in-memory/temp DB + ManualClock.

No real textbook content is required for backend behavior tests; fixtures
build a minimal valid library under tmp_path. The real-library path is
exercised by the parent's HTTP acceptance harness.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_SRC = Path(__file__).resolve().parents[2] / "apps" / "api" / "src"
sys.path.insert(0, str(API_SRC))

from toeic_practice.app import create_app
from toeic_practice.clock import ManualClock
from toeic_practice.library import Library
from toeic_practice.store import Store


def _question(exam: str, number: int, part: int, group: str, answer: str = "A") -> dict:
    section = "listening" if part <= 4 else "reading"
    n_options = 3 if part == 2 else 4
    return {
        "id": f"{exam}-q{number:03d}",
        "canonical_id": f"fixture:{exam}:q{number:03d}",
        "number": number,
        "part": part,
        "section": section,
        "group_id": group,
        "stem": f"Question {number} stem text with keywordalpha",
        "options": [{"id": chr(65 + i), "text": f"option {i} wordbeta"} for i in range(n_options)],
        "answer": answer,
        "source_pages": [number],
        "explanation": {"text": f"explanation {number}", "source_pages": [400 + number]},
    }


def _group(exam: str, gid: str, part: int, qids: list, review: str = "transcript text") -> dict:
    section = "listening" if part <= 4 else "reading"
    return {
        "id": gid, "part": part, "section": section, "question_ids": qids,
        "materials": [{"kind": "text", "text": f"shared material for {gid} keywordgamma"}],
        "review_text": review, "source_pages": [1],
    }


PART_RANGES = {1: (1, 6), 2: (7, 31), 3: (32, 70), 4: (71, 100),
               5: (101, 130), 6: (131, 146), 7: (147, 200)}


def build_exam(exam_id: str, title: str) -> dict:
    questions, groups = [], []
    for part, (lo, hi) in PART_RANGES.items():
        if part in (3, 4, 6, 7):
            # multi-question shared-material groups (3 per group)
            n = lo
            while n <= hi:
                span = min(3, hi - n + 1)
                gid = f"{exam_id}-p{part}-g{n}"
                qids = [f"{exam_id}-q{m:03d}" for m in range(n, n + span)]
                groups.append(_group(exam_id, gid, part, qids))
                for m in range(n, n + span):
                    questions.append(_question(exam_id, m, part, gid,
                                               answer="ABCD"[(m - lo) % 4]))
                n += span
        else:
            for m in range(lo, hi + 1):
                gid = f"{exam_id}-p{part}-q{m}"
                groups.append(_group(exam_id, gid, part, [f"{exam_id}-q{m:03d}"]))
                questions.append(_question(exam_id, m, part, gid,
                                           answer="ABCD"[(m - lo) % 4]))
    return {
        "schema_version": 1, "id": exam_id, "title": title,
        "version": "test-lib-v1", "questions": questions, "groups": groups,
        "audio": {"asset_id": "audio-test-01", "path": "media/test-01.mp3",
                  "duration_seconds": 120.0, "parts": []},
    }


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    (root / "exams").mkdir(parents=True)
    (root / "media").mkdir(parents=True)
    (root / "assets").mkdir(parents=True)
    (root / "sources").mkdir(parents=True)
    (root / "media" / "test-01.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 4096)
    (root / "assets" / "img-a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    manifest = {
        "schema_version": 1, "version": "test-lib-v1", "title": "Test Library",
        "exams": [{"id": "test-01", "title": "TEST 01", "version": "test-lib-v1",
                   "path": "exams/test-01.json", "question_count": 200,
                   "validated": True}],
        "assets": [
            {"id": "audio-test-01", "path": "media/test-01.mp3", "media_type": "audio/mpeg"},
            {"id": "img-a", "path": "assets/img-a.png", "media_type": "image/png"},
        ],
        "sources": [],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "exams" / "test-01.json").write_text(
        json.dumps(build_exam("t01", "TEST 01")), encoding="utf-8")
    cues = {
        "schema_version": 1, "version": "audio-v1",
        "exams": {"test-01": {
            "verified": True, "source_duration_seconds": 120.0,
            "full_start_seconds": 0.0, "full_end_seconds": 120.0,
            "parts": [{"part": p, "start_seconds": (p - 1) * 30.0,
                       "end_seconds": p * 30.0, "verified": True}
                      for p in (1, 2, 3, 4)],
            "groups": [],
        }},
    }
    (root / "audio-cues.json").write_text(json.dumps(cues), encoding="utf-8")
    return root


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.sqlite3")


@pytest.fixture
def library(library_root: Path) -> Library:
    return Library(library_root)


@pytest.fixture
def client(library_root: Path, tmp_path: Path, clock: ManualClock):
    store = Store(tmp_path / "client.sqlite3")
    library = Library(library_root)
    app = create_app(clock=clock, store=store, library=library,
                     backup_root=tmp_path / "backups", serve_web=False, allow_test_host=True)
    return TestClient(app)


@pytest.fixture
def app_services(library_root: Path, tmp_path: Path, clock: ManualClock):
    store = Store(tmp_path / "svc.sqlite3")
    library = Library(library_root)
    app = create_app(clock=clock, store=store, library=library,
                     backup_root=tmp_path / "backups", serve_web=False)
    return app.state.services
