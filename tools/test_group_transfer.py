"""An exported question group must survive a round trip through the bank."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "apps/api/src"))

from group_transfer import (  # noqa: E402
    export_groups,
    import_group,
    new_group_id,
    new_question_id,
)
from toeic_practice.library import Library  # noqa: E402

BANK = REPO / "content/question-pool"


@pytest.fixture(scope="module")
def working_bank(tmp_path_factory):
    """A throwaway copy of the bank that a test may modify."""
    root = tmp_path_factory.mktemp("bank")
    shutil.copy2(BANK / "manifest.json", root / "manifest.json")
    shutil.copy2(BANK / "pool.json", root / "pool.json")
    for folder in ("parts", "assets", "audio"):
        shutil.copytree(BANK / folder, root / folder)
    return root


def _bank_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_a_group_round_trips_through_export_and_import(working_bank, tmp_path):
    """The imported group must read back exactly like the exported one."""
    source_group = "g-0086057bb8aaf636b0d8"  # Part 5, one question
    before = _bank_files(working_bank)
    export = tmp_path / "export"
    export_groups(BANK, [source_group], export)

    result = import_group(export / source_group, working_bank)
    assert result["questions"] == 1

    original = (BANK / "parts/part-5" / f"{source_group}.md").read_text(encoding="utf-8")
    imported = (working_bank / "parts/part-5" / f"{result['group_id']}.md").read_text(
        encoding="utf-8")
    # Only the identifiers may differ; the readable text must not.
    assert imported.replace(result["group_id"], source_group) == original.replace(
        "q-c86162dab78bd00499f1",
        new_question_id("q-c86162dab78bd00499f1", result["group_id"]))

    after = _bank_files(working_bank)
    assert after - before == {f"parts/part-5/{result['group_id']}.md"}


def test_an_imported_group_is_readable_by_the_running_bank(working_bank, tmp_path):
    """The bank must load the imported group, with its answers intact."""
    source_group = "g-04cef8991f3d486e23c2"  # Part 7, four questions
    export = tmp_path / "export"
    export_groups(BANK, [source_group], export)
    result = import_group(export / source_group, working_bank)

    library = Library(working_bank)
    library.load()
    assert library.available, library.load_error
    exam = library.exams["pool"]
    imported = next(g for g in exam.groups if g["id"] == result["group_id"])
    assert imported["part"] == 7
    assert imported["passage_type"] == "single"
    assert len(imported["question_ids"]) == 4
    questions = [q for q in exam.questions if q["group_id"] == imported["id"]]
    assert len(questions) == 4
    for question in questions:
        assert question["answer"] in ["A", "B", "C", "D"]
        assert [o["id"] for o in question["options"]] == ["A", "B", "C", "D"]
        assert question["explanation"]["text"].strip()


def test_a_listening_group_keeps_its_recording_and_subtitles(working_bank, tmp_path):
    """The recording must follow the group to its new name."""
    source_group = "g-04e92fcdf5be1747d409"  # Part 1, one question, one picture
    export = tmp_path / "export"
    export_groups(BANK, [source_group], export)
    result = import_group(export / source_group, working_bank)

    library = Library(working_bank)
    library.load()
    assert library.available, library.load_error
    exam = library.exams["pool"]
    imported = next(g for g in exam.groups if g["id"] == result["group_id"])
    assert imported["audio"]["asset_id"] in library.assets
    assert imported["listening_script"]["sentences"]
    assert (working_bank / "parts/part-1" / f"{result['group_id']}.srt").is_file()
    # The picture keeps its own asset and stays registered.
    images = [m for m in imported["materials"] if m.get("kind") == "image"]
    assert images
    for material in images:
        assert material["asset_id"] in library.assets


def test_an_import_never_reuses_an_identifier(working_bank, tmp_path):
    """Importing one bundle twice must not create a second group."""
    source_group = "g-0086057bb8aaf636b0d8"
    export = tmp_path / "export"
    export_groups(BANK, [source_group], export)
    first = import_group(export / source_group, working_bank)
    second = import_group(export / source_group, working_bank)
    assert first["group_id"] == second["group_id"]
    assert second["status"] == "already-imported"
    assert new_group_id(source_group, "different") != new_group_id(source_group, "other")


def test_a_different_group_never_reuses_an_identifier(working_bank, tmp_path):
    """Two different bundles must never land on the same group id."""
    export = tmp_path / "export"
    export_groups(BANK, ["g-0086057bb8aaf636b0d8", "g-04cef8991f3d486e23c2"], export)
    first = import_group(export / "g-0086057bb8aaf636b0d8", working_bank)
    second = import_group(export / "g-04cef8991f3d486e23c2", working_bank)
    assert first["group_id"] != second["group_id"]
    assert new_question_id("q-c86162dab78bd00499f1", first["group_id"]) != \
        new_question_id("q-c86162dab78bd00499f1", second["group_id"])


def test_a_bundle_the_bank_cannot_read_is_refused(working_bank, tmp_path):
    """A broken group must be rejected before anything is written."""
    export = tmp_path / "export"
    export_groups(BANK, ["g-0086057bb8aaf636b0d8"], export)
    bundle = export / "g-0086057bb8aaf636b0d8"
    broken = bundle / "g-0086057bb8aaf636b0d8.md"
    text = broken.read_text(encoding="utf-8").replace("## 答案 / 题解", "## 答案")
    broken.write_text(text, encoding="utf-8")
    before = _bank_files(working_bank)
    with pytest.raises(SystemExit):
        import_group(bundle, working_bank)
    assert _bank_files(working_bank) == before


def test_the_imported_group_keeps_the_manifest_in_step(working_bank, tmp_path):
    """Every asset the imported group uses must be registered and present."""
    source_group = "g-04e92fcdf5be1747d409"
    export = tmp_path / "export"
    export_groups(BANK, [source_group], export)
    result = import_group(export / source_group, working_bank)
    manifest = json.loads((working_bank / "manifest.json").read_text(encoding="utf-8"))
    registered = {entry["id"]: entry for entry in manifest["assets"]}

    library = Library(working_bank)
    library.load()
    assert library.available, library.load_error
    imported = next(g for g in library.exams["pool"].groups
                    if g["id"] == result["group_id"])
    needed = {imported["audio"]["asset_id"]}
    needed |= {m["asset_id"] for m in imported["materials"] if m.get("asset_id")}
    for asset_id in needed:
        assert asset_id in registered
        entry = registered[asset_id]
        assert (working_bank / entry["path"]).is_file()
        payload = (working_bank / entry["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
    for entry in manifest["assets"]:
        assert (working_bank / entry["path"]).is_file()

