"""The bank version must follow content identity, not the way it is written."""
import json
import shutil
import sys
from pathlib import Path

import pytest

API_SRC = Path(__file__).resolve().parents[2] / "apps" / "api" / "src"
sys.path.insert(0, str(API_SRC))

from toeic_practice.library import Library

ROOT = Path(__file__).resolve().parents[2]
REAL_BANK = ROOT / "content" / "question-pool"


def _version(library: Library) -> str:
    return library.library_version()


def test_the_version_is_stable_for_the_same_content(tmp_path):
    library = Library(REAL_BANK)
    library.load()
    assert library.available, library.load_error
    first = _version(library)
    again = Library(REAL_BANK)
    again.load()
    assert _version(again) == first


def test_rewording_a_passage_keeps_the_version(tmp_path):
    """A learner must not lose progress because the text was written out."""
    bank = tmp_path / "bank"
    shutil.copytree(REAL_BANK, bank)
    original = Library(bank)
    original.load()
    assert original.available, original.load_error
    before = _version(original)

    target = next(bank.glob("parts/part-7/*.md"))
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace("Harold Rimes", "H. Rimes", 1), encoding="utf-8")

    changed = Library(bank)
    changed.load()
    assert changed.available, changed.load_error
    assert _version(changed) == before


def test_changing_an_answer_changes_the_version(tmp_path):
    """A real change to the bank must still be noticed."""
    bank = tmp_path / "bank"
    shutil.copytree(REAL_BANK, bank)
    original = Library(bank)
    original.load()
    assert original.available, original.load_error
    before = _version(original)

    pool = json.loads((bank / "pool.json").read_text(encoding="utf-8"))
    question = pool["questions"][0]
    target = next(bank.glob(f"parts/part-{question['part']}/{question['group_id']}.md"))
    text = target.read_text(encoding="utf-8")
    old = f"**答案：{question['answer']}**"
    new = "**答案：" + ("A" if question["answer"] != "A" else "B") + "**"
    assert old in text
    target.write_text(text.replace(old, new, 1), encoding="utf-8")

    changed = Library(bank)
    changed.load()
    assert changed.available, changed.load_error
    assert _version(changed) != before


def test_the_version_does_not_depend_on_the_order_of_a_hash(tmp_path):
    library = Library(REAL_BANK)
    library.load()
    assert library.available, library.load_error
    version = _version(library)
    head, _, digest = version.rpartition(".")
    assert head == library.manifest_version
    assert len(digest) == 16
    assert all(character in "0123456789abcdef" for character in digest)
