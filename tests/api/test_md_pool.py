"""The Markdown question bank must load into the same shapes as pool.json."""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

API_SRC = Path(__file__).resolve().parents[2] / "apps" / "api" / "src"
sys.path.insert(0, str(API_SRC))

from toeic_practice.md_pool import (  # noqa: E402
    load_md_pool,
    parse_md_group,
    parse_srt,
    parse_frontmatter,
)

REPO = Path(__file__).resolve().parents[2]
MD_ROOT = REPO / "content" / "question-pool"


def _words(text: str) -> list[str]:
    """Compare text ignoring the soft line breaks a PDF extract leaves."""
    # A layout adds or removes heading markers, joins soft line breaks and
    # closes the space between two Han characters; only the wording is compared.
    stripped = re.sub(r"(?m)^#{1,6}\s*", "", text)
    return re.sub(r"\s+", "", stripped)


SAMPLE = """---
group_id: g-0123456789abcdef0123
part: 7
section: reading
passage_type: single
audio: null
subtitles: null
questions:
  - id: q-11111111111111111111
    index: 1
  - id: q-22222222222222222222
    index: 2
---

## 原文

### Passage 1

Harold Rimes [10:11 A.M.]
Great news, everyone.

## 选项

### 第 1 题

What are the writers mainly discussing?

- A. The success of their coffee shop
- B. The comments by an inspector
- C. The contract they need to sign
- D. The plans for a new business

### 第 2 题

Why now?

- A. Because of rain
- B. Because of snow
- C. Because of wind
- D. Because of heat

## 答案 / 题解

### 第 1 题

**答案：A**

```
What are the writers mainly discussing?
（
A
）
The success of their coffee shop
```

### 第 2 题

**答案：B**

```
Because of snow.
```
"""


def test_frontmatter_parses_scalars_lists_and_null():
    values = parse_frontmatter(SAMPLE)
    assert values["group_id"] == "g-0123456789abcdef0123"
    assert values["part"] == 7
    assert values["section"] == "reading"
    assert values["passage_type"] == "single"
    assert values["audio"] is None
    assert values["subtitles"] is None
    assert values["questions"] == [
        {"id": "q-11111111111111111111", "index": 1},
        {"id": "q-22222222222222222222", "index": 2},
    ]


def test_a_group_file_yields_its_questions_and_material():
    group, questions = parse_md_group(SAMPLE, "g-0123456789abcdef0123.md")
    assert group["id"] == "g-0123456789abcdef0123"
    assert group["part"] == 7
    assert group["section"] == "reading"
    assert group["passage_type"] == "single"
    assert group["question_ids"] == ["q-11111111111111111111", "q-22222222222222222222"]
    assert group["materials"] == [
        {"kind": "text", "text": "Harold Rimes [10:11 A.M.]\nGreat news, everyone."}
    ]
    assert [q["stem"] for q in questions] == ["What are the writers mainly discussing?", "Why now?"]
    assert questions[0]["options"] == [
        {"id": "A", "text": "The success of their coffee shop"},
        {"id": "B", "text": "The comments by an inspector"},
        {"id": "C", "text": "The contract they need to sign"},
        {"id": "D", "text": "The plans for a new business"},
    ]
    assert questions[0]["answer"] == "A"
    assert questions[1]["answer"] == "B"


def test_the_solution_body_is_kept_verbatim():
    group, questions = parse_md_group(SAMPLE, "g-0123456789abcdef0123.md")
    assert questions[0]["explanation"]["text"] == (
        "What are the writers mainly discussing?\n（\nA\n）\nThe success of their coffee shop"
    )
    assert questions[1]["explanation"]["text"] == "Because of snow."


def test_options_are_read_in_every_supported_form():
    body = """---
group_id: g-1
part: 2
section: listening
questions:
  - id: q-1
    index: 1
---

## 选项

### 第 1 题

Pick one.

（
A
）
First choice

(B) Second choice

- C. Third choice

## 答案 / 题解

### 第 1 题

**答案：A**

done
"""
    _, questions = parse_md_group(body, "g-1.md")
    assert questions[0]["options"] == [
        {"id": "A", "text": "First choice"},
        {"id": "B", "text": "Second choice"},
        {"id": "C", "text": "Third choice"},
    ]


def test_part_six_blanks_map_back_to_question_tokens():
    body = """---
group_id: g-6
part: 6
section: reading
questions:
  - id: q-a
    index: 1
  - id: q-b
    index: 2
blanks:
  - index: 1
    question_id: q-a
  - index: 2
    question_id: q-b
---

## 原文

### Material 1

Fill {{blank:1}} here and {{blank:2}} there.

## 选项

### 第 1 题

- A. one
- B. two

### 第 2 题

- A. three
- B. four

## 答案 / 题解

### 第 1 题

**答案：A**

x

### 第 2 题

**答案：B**

y
"""
    group, questions = parse_md_group(body, "g-6.md")
    assert group["materials"][0]["text"] == "Fill {{qid:q-a}} here and {{qid:q-b}} there."
    assert len(questions) == 2


def test_srt_is_parsed_with_its_timings():
    text = (
        "1\n00:00:00,200 --> 00:00:02,610\nM: Do you know why Ms. Sato called a meeting?\n\n"
        "2\n00:00:02,610 --> 00:00:05,100\nW: She was, but she delayed her trip.\n"
    )
    rows = parse_srt(text, "g-1")
    assert [row["id"] for row in rows] == ["g-1-s001", "g-1-s002"]
    assert rows[0]["text"] == "M: Do you know why Ms. Sato called a meeting?"
    assert rows[0]["start_seconds"] == pytest.approx(0.2)
    assert rows[0]["end_seconds"] == pytest.approx(2.61)
    assert rows[1]["start_seconds"] == pytest.approx(2.61)


def _write_pool_md(root: Path) -> None:
    parts = root / "parts" / "part-7"
    parts.mkdir(parents=True)
    (parts / "g-0123456789abcdef0123.md").write_text(SAMPLE, encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 3, "version": "md-test-v1", "validated": True,
        "assets": [], "pool": {"format": "md", "path": "parts"},
    }), encoding="utf-8")


def test_the_loader_publishes_a_pool_exam(tmp_path):
    from toeic_practice.library import Library
    root = tmp_path / "pool"
    root.mkdir()
    _write_pool_md(root)
    library = Library(root)
    library.load()
    assert library.available, library.load_error
    assert library.pool_mode is True
    exam = library.exams["pool"]
    assert exam.question_count == 2
    assert len(exam.groups) == 1
    assert exam.questions[0]["canonical_id"] == "bank:q-11111111111111111111"


def test_the_loader_rejects_a_group_whose_answer_is_not_an_option(tmp_path):
    from toeic_practice.library import Library
    root = tmp_path / "pool"
    root.mkdir()
    broken = SAMPLE.replace("**答案：A**", "**答案：Z**")
    parts = root / "parts" / "part-7"
    parts.mkdir(parents=True)
    (parts / "g-0123456789abcdef0123.md").write_text(broken, encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 3, "version": "md-test-v1", "validated": True,
        "assets": [], "pool": {"format": "md", "path": "parts"},
    }), encoding="utf-8")
    library = Library(root)
    library.load()
    assert not library.available
    assert "答案" in library.load_error or "无效" in library.load_error


def test_the_loader_rejects_a_missing_recording(tmp_path):
    from toeic_practice.library import Library
    root = tmp_path / "pool"
    root.mkdir()
    parts = root / "parts" / "part-7"
    parts.mkdir(parents=True)
    listening = """---
group_id: g-0123456789abcdef0123
part: 3
section: listening
audio_asset: audio-0123456789abcdef0123
subtitles: g-0123456789abcdef0123.srt
questions:
  - id: q-11111111111111111111
    index: 1
  - id: q-22222222222222222222
    index: 2
  - id: q-33333333333333333333
    index: 3
---

## 原文

### 听力原文

M: Hello there.

### 中文原文

M: 你好。

## 选项

### 第 1 题

First?

- A. one
- B. two
- C. three
- D. four

### 第 2 题

Second?

- A. one
- B. two
- C. three
- D. four

### 第 3 题

Third?

- A. one
- B. two
- C. three
- D. four

## 答案 / 题解

### 第 1 题

**答案：A**

one

### 第 2 题

**答案：B**

two

### 第 3 题

**答案：C**

three
"""
    (parts / "g-0123456789abcdef0123.md").write_text(listening, encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 3, "version": "md-test-v1", "validated": True,
        "assets": [], "pool": {"format": "md", "path": "parts"},
    }), encoding="utf-8")
    library = Library(root)
    library.load()
    assert not library.available


@pytest.mark.skipif(not (MD_ROOT / "parts").exists(),
                    reason="the Markdown bank has not been generated yet")
def test_the_generated_bank_matches_pool_json_field_by_field():
    from toeic_practice.library import Library
    from toeic_practice.pool_library import load_pool

    manifest = json.loads((MD_ROOT / "manifest.json").read_text(encoding="utf-8"))
    json_manifest = dict(manifest)
    json_manifest["schema_version"] = 2
    json_manifest["pool"] = {"path": "pool.json"}
    library = Library(MD_ROOT)
    library.manifest = json_manifest
    library._loaded = True
    load_pool(library)
    assert library.available, library.load_error
    expected = {q["id"]: q for q in library.exams["pool"].questions}
    expected_groups = {g["id"]: g for g in library.exams["pool"].groups}

    md_library = Library(MD_ROOT)
    md_library.manifest = manifest
    md_library._loaded = True
    load_md_pool(md_library, MD_ROOT)
    assert md_library.available, md_library.load_error
    actual = {q["id"]: q for q in md_library.exams["pool"].questions}
    actual_groups = {g["id"]: g for g in md_library.exams["pool"].groups}

    assert set(actual) == set(expected)
    for qid, question in expected.items():
        got = actual[qid]
        # The Markdown bank joins the soft line breaks a PDF extract leaves
        # behind. Only whitespace may differ, never a word.
        assert _words(got["stem"]) == _words(question["stem"]), qid
        assert [o["id"] for o in got["options"]] == [o["id"] for o in question["options"]], qid
        for want, have in zip(question["options"], got["options"]):
            assert _words(have["text"]) == _words(want["text"]), qid
        assert got["answer"] == question["answer"], qid
        assert got["part"] == question["part"], qid
        assert got["section"] == question["section"], qid
        assert got["group_id"] == question["group_id"], qid
        assert got["canonical_id"] == question["canonical_id"], qid

    assert set(actual_groups) == set(expected_groups)
    for gid, group in expected_groups.items():
        got = actual_groups[gid]
        assert got["question_ids"] == group["question_ids"], gid
        assert got["part"] == group["part"], gid
        assert got["section"] == group["section"], gid
        assert got.get("passage_type") == group.get("passage_type"), gid
        assert len(got["materials"]) == len(group["materials"]), gid
        for want, have in zip(group["materials"], got["materials"]):
            assert want["kind"] == have["kind"], gid
            if want["kind"] == "image":
                assert want["asset_id"] == have["asset_id"], gid
            else:
                # The Markdown bank stores the rendered passage, so the layout
                # headings a passage carries appear here.
                assert _words(have["text"]) == _words(want["text"]), gid
        if group["part"] <= 4:
            assert got["audio"]["asset_id"] == group["audio"]["asset_id"], gid
            assert got["audio"]["end_seconds"] == group["audio"]["end_seconds"], gid
            assert got["listening_script"]["english"] == group["listening_script"]["english"], gid
            assert got["listening_script"]["chinese"] == group["listening_script"]["chinese"], gid
            assert got["listening_script"]["sentences"] == group["listening_script"]["sentences"], gid
        # The review copy is the rendered textbook text: it may carry heading
        # markers the raw source did not have, but never loses a word.
        assert _words(got.get("review_text", "")) == _words(group.get("review_text", "")), gid

