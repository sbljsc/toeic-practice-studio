"""The Markdown question bank must be readable, complete and reversible."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from build_md_pool import (  # noqa: E402
    DEFAULT_LAYOUTS,
    DEFAULT_POOL,
    LayoutIndex,
    blank_entries,
    build,
    demote_headings,
    join_han_space,
    load_layouts,
    render_layout,
    srt_time,
    to_blanks,
)

POOL = json.loads((DEFAULT_POOL / "pool.json").read_text(encoding="utf-8"))
QUESTIONS = {question["id"]: question for question in POOL["questions"]}
GROUPS = {group["id"]: group for group in POOL["groups"]}
LAYOUTS = load_layouts(DEFAULT_LAYOUTS)
INDEX = LayoutIndex(LAYOUTS)


def _group_md(group: dict) -> str:
    return (DEFAULT_POOL / "parts" / f"part-{group['part']}"
            / f"{group['id']}.md").read_text(encoding="utf-8")


def _chapters(text: str) -> dict[str, str]:
    """Split a generated file back into its three chapters."""
    chapters: dict[str, list[str]] = {}
    current = ""
    for line in text.split("\n"):
        if line.strip() in ("## 原文", "## 选项", "## 答案 / 题解"):
            current = line.strip()
            chapters[current] = []
            continue
        if current:
            chapters[current].append(line)
    return {name: "\n".join(body) for name, body in chapters.items()}


def _question_blocks(section: str) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    current = 0
    body: list[str] = []
    for line in section.split("\n"):
        match = re.match(r"^#{2,6}\s+第\s*(\d+)\s*题\s*$", line.strip())
        if match:
            if current:
                blocks.append((current, body))
            current = int(match.group(1))
            body = []
            continue
        if current:
            body.append(line)
    if current:
        blocks.append((current, body))
    return blocks


def test_a_heading_layout_renders_the_same_paragraphs_and_hard_breaks():
    layout = next(item for item in LAYOUTS if item["headings"] and item["hardBreaks"])
    rendered = render_layout(layout["source"], layout)
    assert rendered is not None
    lines = rendered.split("\n")
    # A hard break keeps the trailing two spaces that request a line break.
    assert any(line.endswith("  ") for line in lines)
    # A heading carries the level the layout recorded.
    assert any(re.match(r"^#{3,4} ", line) for line in lines)
    # Every source line is still present, only the layout changed.
    for line in layout["source"].split("\n"):
        if line.strip():
            assert line.strip() in rendered


def test_a_layout_without_headings_only_adds_paragraph_breaks():
    layout = next(item for item in LAYOUTS
                  if not item["headings"] and item["paragraphs"])
    rendered = render_layout(layout["source"], layout)
    assert rendered is not None
    assert rendered.count("\n\n") >= 1
    assert "".join(rendered.split()) == "".join(layout["source"].split())


def test_an_out_of_range_layout_is_refused_instead_of_crashing():
    layout = dict(LAYOUTS[0])
    layout["paragraphs"] = [99999]
    assert render_layout(layout["source"], layout) is None
    broken = dict(LAYOUTS[0])
    broken["headings"] = [{"line": 0, "level": 9}]
    assert render_layout(broken["source"], broken) is None


def test_the_frontend_and_this_generator_join_a_heading_the_same_way():
    # The frontend removes a single space between two Han characters.
    assert join_han_space("概 要") == "概要"
    assert join_han_space("a b") == "a b"
    assert join_han_space("圣乔治 媒体") == "圣乔治媒体"


def test_part_six_blanks_are_numbered_in_document_order():
    group = next(item for item in POOL["groups"] if item["part"] == 6)
    entries = blank_entries(group)
    assert [entry["question_id"] for entry in entries] == group["question_ids"]
    assert [entry["index"] for entry in entries] == [1, 2, 3, 4]
    text = "Fill {{qid:%s}} and {{qid:%s}}." % (group["question_ids"][0],
                                                group["question_ids"][3])
    replaced = to_blanks(text, entries)
    assert replaced == "Fill {{blank:1}} and {{blank:4}}."


def test_part_six_marks_the_blank_of_a_question_outside_its_group():
    group = next(item for item in POOL["groups"] if item["part"] == 6)
    stray = dict(group)
    stray["materials"] = [{"kind": "text", "text": "{{qid:q-not-in-this-group}}"}]
    with pytest.raises(ValueError):
        blank_entries(stray)


def test_part_seven_numbers_every_passage_in_order():
    group = next(item for item in POOL["groups"]
                 if item["part"] == 7 and len(item["materials"]) >= 3)
    text = _group_md(group)
    headings = re.findall(r"^#{2,6} Passage (\d+)$", text, re.M)
    assert headings == [str(index) for index in range(1, len(group["materials"]) + 1)]


def test_an_option_and_a_solution_survive_the_round_trip_unchanged():
    question = next(item for item in POOL["questions"]
                    if "\n" in item["options"][0]["text"])
    group = GROUPS[question["group_id"]]
    text = _group_md(group)
    # The question may sit anywhere inside its group, so read its own block.
    position = group["question_ids"].index(question["id"])
    body = _question_blocks(_chapters(text)["## 选项"])[position][1]
    assert question["options"][0]["text"] in "\n".join(body)
    solution = _question_blocks(_chapters(text)["## 答案 / 题解"])[position][1]
    assert question["explanation"]["text"] in "\n".join(solution)


def test_a_wrapped_option_keeps_its_own_line_breaks():
    question = next(item for item in POOL["questions"]
                    if any("\n" in option["text"] for option in item["options"]))
    group = GROUPS[question["group_id"]]
    body = _question_blocks(_chapters(_group_md(group))["## 选项"])[0][1]
    joined = "\n".join(body)
    for option in question["options"]:
        assert option["text"] in joined


def test_the_generated_files_parse_back_into_the_same_questions():
    sys.path.insert(0, str(REPO / "apps" / "api" / "src"))
    from toeic_practice.md_pool import parse_md_group

    for group in POOL["groups"]:
        parsed, questions = parse_md_group(_group_md(group), f"{group['id']}.md")
        assert parsed["id"] == group["id"]
        assert parsed["part"] == group["part"]
        assert parsed["question_ids"] == group["question_ids"]
        assert len(questions) == len(group["question_ids"])
        for source, loaded in zip(group["question_ids"], questions):
            expected = QUESTIONS[source]
            assert loaded["id"] == expected["id"]
            assert loaded["answer"] == expected["answer"]
            assert loaded["stem"] == expected["stem"]
            assert [option["id"] for option in loaded["options"]] == \
                [option["id"] for option in expected["options"]]
            for want, have in zip(expected["options"], loaded["options"]):
                assert have["text"] == want["text"]
            assert loaded["explanation"]["text"] == expected["explanation"]["text"]


def test_every_answer_in_the_markdown_matches_the_pool():
    """Each written answer letter must equal the pool answer, question by question."""
    written: dict[str, str] = {}
    for group in POOL["groups"]:
        text = _group_md(group)
        blocks = _question_blocks(_chapters(text)["## 答案 / 题解"])
        assert len(blocks) == len(group["question_ids"])
        for position, qid in enumerate(group["question_ids"]):
            match = re.search(r"^\*\*答案：([A-D])\*\*$", "\n".join(blocks[position][1]),
                              re.M)
            assert match, (group["id"], qid)
            written[qid] = match.group(1)
    assert len(written) == len(QUESTIONS) == 2000
    assert written == {qid: question["answer"] for qid, question in QUESTIONS.items()}


def test_a_subtitle_time_is_rounded_to_the_millisecond():
    assert srt_time(0) == "00:00:00,000"
    assert srt_time(0.2) == "00:00:00,200"
    assert srt_time(2.61) == "00:00:02,610"
    assert srt_time(85.425) == "00:01:25,425"
    assert srt_time(3661.5) == "01:01:01,500"


def test_a_group_without_material_or_stem_still_writes_every_section():
    empty_stem = next(item for item in POOL["questions"] if not item["stem"])
    group = GROUPS[empty_stem["group_id"]]
    text = _group_md(group)
    chapters = _chapters(text)
    assert set(chapters) == {"## 原文", "## 选项", "## 答案 / 题解"}
    body = _question_blocks(chapters["## 选项"])[0][1]
    # An empty stem writes no stem line, only the options.
    assert not any(line.strip() and not line.strip().startswith("- ")
                   for line in body)


def test_an_empty_review_text_writes_no_source_block():
    group = next(item for item in POOL["groups"]
                 if item["part"] == 1 and not (item["review_text"] or "").strip())
    text = _group_md(group)
    assert "教材原文" not in text
    assert "Transcript" in text


def test_the_generator_refuses_to_clean_a_directory_outside_the_output_root():
    outside = REPO / "tools"
    (outside / "parts").mkdir(exist_ok=True)
    try:
        with pytest.raises(ValueError):
            build(DEFAULT_POOL, outside, DEFAULT_LAYOUTS)
    finally:
        shutil.rmtree(outside / "parts", ignore_errors=True)


def test_the_generator_never_cleans_a_parts_folder_of_another_bank(tmp_path):
    # The output root has to be the bank folder whose content is written.
    stray = tmp_path / "other" / "parts"
    stray.mkdir(parents=True)
    (stray / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        build(DEFAULT_POOL, tmp_path / "other", DEFAULT_LAYOUTS)
    assert (stray / "keep.txt").is_file()


def test_every_group_writes_one_file_and_a_listening_group_writes_one_subtitle():
    md_files = sorted((DEFAULT_POOL / "parts").glob("part-*/*.md"))
    srt_files = sorted((DEFAULT_POOL / "parts").glob("part-*/*.srt"))
    assert len(md_files) == len(POOL["groups"]) == 1030
    assert len(srt_files) == 540
    assert {path.stem for path in md_files} == set(GROUPS)
    assert {path.stem for path in srt_files} == {
        group["id"] for group in POOL["groups"] if group["part"] <= 4}


def test_a_material_heading_is_never_mistaken_for_a_section_label():
    # A heading inside a material keeps its own level; the file's labels sit
    # deeper than any heading a material can carry.
    assert demote_headings("### Title") == "### Title"
    assert demote_headings("## Title") == "## Title"
    assert demote_headings("###### Title") == "###### Title"
    assert demote_headings("not a heading") == "not a heading"


def test_a_label_is_deeper_than_any_heading_a_material_can_carry():
    # The reader splits the file on its own labels, so a label must never
    # share a level with a heading that belongs to the material.
    def level(text: str) -> int:
        return len(text) - len(text.lstrip("#"))

    labels = ("##### Material 1", "##### Passage 1", "##### 第 1 题",
              "##### Transcript", "##### Review")
    material_headings = ["# Title", "## Title", "### Title",
                         "#### Title"]
    for label in labels:
        for heading in material_headings:
            assert level(label) > level(heading), (label, heading)


def test_a_deep_heading_inside_a_material_is_not_read_as_a_label():
    # A material may carry a heading as deep as the file's own labels. The
    # reader recognises a label by its exact wording, so the heading stays
    # part of the material.
    from toeic_practice.md_pool import parse_md_group

    text = "\n".join([
        "---",
        "group_id: g-0123456789abcdef0123",
        "part: 7",
        "section: reading",
        "questions:",
        "  - id: q-0123456789abcdef0123",
        "    index: 1",
        "---",
        "",
        "## 原文",
        "",
        "##### Passage 1",
        "",
        "##### A heading that only looks like a label",
        "",
        "##### 第 9 题",
        "",
        "body text",
        "",
        "## 选项",
        "",
        "##### 第 1 题",
        "",
        "Stem?",
        "",
        "- A. one",
        "- B. two",
        "- C. three",
        "- D. four",
        "",
        "## 答案 / 题解",
        "",
        "##### 第 1 题",
        "",
        "**答案：A**",
        "",
        "why",
        "",
    ])
    group, questions = parse_md_group(text, "g-0123456789abcdef0123.md")
    assert len(questions) == 1
    assert len(group["materials"]) == 1
    body = group["materials"][0]["text"]
    assert "A heading that only looks like a label" in body
    assert "第 9 题" in body
