"""Build the plain-Markdown question bank from the validated pool.

The Markdown tree is the readable source of truth for every question group:
one file per group under ``parts/part-N/``, one sibling subtitle file per
listening group, and the shared picture and recording pools left untouched.

This generator only reorganises presentation. Question wording, options,
answers, group membership, recordings and subtitle timing stay byte-identical
to ``pool.json``; material and review text are stored in the same rendered
form the frontend already displays, so the layout index becomes optional.

The file layout follows ``docs/md-question-store.md`` and the reader in
``apps/api/src/toeic_practice/md_pool.py``:

* ``## 原文`` holds the optional transcript blocks and the shared material.
  ``###`` starts a structural label; a content heading therefore uses ``####``
  or deeper, so a reader never mistakes a label for material.
* ``## 选项`` holds one ``### 第 N 题`` block per question with its stem and
  its options.
* ``## 答案 / 题解`` holds one ``### 第 N 题`` block per question with the
  answer letter and the verbatim solution text in a fenced block.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_POOL = REPO / "content" / "question-pool"
DEFAULT_LAYOUTS = REPO / "apps" / "web" / "src" / "domain" / "textLayouts.ts"

SECTION_ORIGINAL = "## 原文"
SECTION_OPTIONS = "## 选项"
SECTION_SOLUTION = "## 答案 / 题解"
HEADING_SCRIPT_EN = "### Transcript"
HEADING_SCRIPT_ZH = "### Transcript (zh)"
HEADING_SOURCE = "### 教材原文"
NO_MATERIAL = "（本题无附加材料）"
HEADING_SOURCE = "### Review"
FENCE = "```"

HEADING_LINE = re.compile(r"^(#{1,6})(\s)")
OPTION_LINE = re.compile(r"^\s*-\s*([A-D])\.\s*(.*)$")

QID_TOKEN = re.compile(r"\{\{qid:([A-Za-z0-9_-]+)\}\}")
ANSWER_LINE = re.compile(r"^\*\*答案：([A-D])\*\*$")

# Unicode ranges of the Han script. The frontend removes a single space
# between two Han characters when it joins a heading that spans source
# lines; the same rule is applied here so both renderers agree.
HAN_RANGES = (
    (0x2E80, 0x2E99), (0x2E9B, 0x2EF3), (0x2F00, 0x2FD5), (0x3005, 0x3005),
    (0x3007, 0x3007), (0x3021, 0x3029), (0x3038, 0x303B), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0xFE10, 0xFE19), (0xFE30, 0xFE4F),
    (0x20000, 0x2A6DF), (0x2A700, 0x2B739), (0x2B740, 0x2B81D),
    (0x2B820, 0x2CEAF), (0x2CEB0, 0x2EBE0), (0x2EBF0, 0x2EE5D),
    (0x2F800, 0x2FA1D), (0x30000, 0x3134A), (0x31350, 0x323AF),
)


def is_han(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in HAN_RANGES)


def join_han_space(text: str) -> str:
    """Remove a single space between two Han characters.

    This mirrors the frontend's ``(\\p{Script=Han}) (?=\\p{Script=Han})``
    replacement, including its non-overlapping scan order.
    """
    result: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if (is_han(char) and index + 2 < length and text[index + 1] == " "
                and is_han(text[index + 2])):
            # The single space between two Han characters is dropped.
            result.append(char)
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def render_layout(source: str, layout: dict) -> str | None:
    """Render one verified layout, or None when the layout cannot apply.

    The rules mirror ``apps/web/src/domain/textLayout.ts``: an out-of-range
    index, an invalid heading or an overlapping heading rejects the whole
    layout so the untouched source is used instead.
    """
    lines = source.split("\n")

    def valid(at: object) -> bool:
        return type(at) is int and 0 <= at < len(lines)

    paragraphs = layout.get("paragraphs") or []
    hard_breaks = layout.get("hardBreaks") or []
    headings = layout.get("headings") or []
    if not all(valid(at) for at in paragraphs):
        return None
    if not all(valid(at) for at in hard_breaks):
        return None
    for heading in headings:
        line = heading.get("line")
        end = heading.get("endLine", line)
        if not valid(line) or not valid(end) or end < line:
            return None
        if heading.get("level") not in (3, 4):
            return None
        if not lines[line].strip():
            return None
        if line in hard_breaks:
            return None
    occupied: set[int] = set()
    spans: dict[int, tuple[int, int]] = {}
    for heading in headings:
        line = heading["line"]
        end = heading.get("endLine", line)
        for at in range(line, end + 1):
            if at in occupied:
                return None
            occupied.add(at)
        spans[line] = (heading["level"], end)

    paragraph_set = set(paragraphs)
    hard_set = set(hard_breaks)
    output: list[str] = []
    at = 0
    while at < len(lines):
        if at in paragraph_set and output and output[-1].strip():
            output.append("")
        if at in spans:
            level, end = spans[at]
            text = " ".join(line.strip() for line in lines[at:end + 1])
            text = join_han_space(text)
            output.append("#" * level + " " + text)
            at = end + 1
            continue
        output.append(lines[at].rstrip() + ("  " if at in hard_set else ""))
        at += 1
    return "\n".join(output)


def load_layouts(path: Path) -> list[dict]:
    """Read the layout array out of the generated TypeScript module."""
    source = path.read_text(encoding="utf-8")
    match = re.search(r"=\s*\[", source)
    if not match:
        raise ValueError(f"排版索引格式无效：{path}")
    start = source.index("[", match.start())
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "[":
            depth += 1
        elif source[index] == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    else:
        raise ValueError(f"排版索引格式无效：{path}")
    layouts = json.loads(source[start:end])
    if not isinstance(layouts, list):
        raise ValueError(f"排版索引格式无效：{path}")
    return layouts


class LayoutIndex:
    """Exact and template layout lookup, matching the frontend index."""

    def __init__(self, layouts: list[dict]) -> None:
        self.exact: dict[str, list[dict]] = {}
        self.templates: list[tuple[dict, re.Pattern[str], list[str]]] = []
        for layout in layouts:
            source = normalize(layout.get("source", ""))
            self.exact.setdefault(source, []).append(layout)
            if "{{qid:" not in source:
                continue
            tokens: list[str] = []
            pattern: list[str] = []
            for piece in re.split(r"(\{\{qid:[^}]+\}\})", source):
                if piece.startswith("{{qid:"):
                    tokens.append(piece)
                    pattern.append(f"({re.escape(piece)}|\\([1-9][0-9]*\\))")
                else:
                    pattern.append(re.escape(piece))
            self.templates.append(
                (layout, re.compile("^" + "".join(pattern) + "$"), tokens))

    def apply(self, source: str) -> str | None:
        """Return the one verified rendering, or None to keep the source."""
        normalized = normalize(source)
        candidates = list(self.exact.get(normalized, []))
        if not candidates:
            for layout, pattern, tokens in self.templates:
                match = pattern.match(normalized)
                if not match:
                    continue
                values: dict[str, str] = {}
                consistent = True
                for index, token in enumerate(tokens):
                    value = match.group(index + 1)
                    if token in values and values[token] != value:
                        consistent = False
                    values[token] = value
                if consistent:
                    candidates.append(layout)
        results = set()
        for layout in candidates:
            rendered = render_layout(normalized, layout)
            if rendered is not None:
                results.add(rendered)
        return next(iter(results)) if len(results) == 1 else None


def yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if text == "" or re.search(r"[:#\[\]{}&*!|>'\"%@`]|^\s|\s$", text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def frontmatter(group: dict, blanks: list[dict]) -> list[str]:
    lines = ["---"]
    values = {
        "group_id": group["id"],
        "part": group["part"],
        "section": group["section"],
        "passage_type": group.get("passage_type"),
        "audio_asset": group["audio"]["asset_id"] if group.get("audio") else None,
        "subtitles": f"{group['id']}.srt" if group.get("audio") else None,
        "explanation_verbatim": True,
    }
    for key, value in values.items():
        lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("questions:")
    for index, qid in enumerate(group["question_ids"], 1):
        lines.append(f"  - id: {qid}")
        lines.append(f"    index: {index}")
    if blanks:
        lines.append("blanks:")
        for entry in blanks:
            lines.append(f"  - index: {entry['index']}")
            lines.append(f"    question_id: {entry['question_id']}")
    lines.append("---")
    return lines


def srt_time(seconds: float) -> str:
    total = int(round(seconds * 1000))
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def srt_block(group: dict) -> str:
    blocks = []
    for index, row in enumerate(group["listening_script"]["sentences"], 1):
        blocks.append(
            f"{index}\n{srt_time(row['start_seconds'])} --> {srt_time(row['end_seconds'])}\n"
            f"{row['text']}")
    return "\n\n".join(blocks) + "\n"


def blank_entries(group: dict) -> list[dict]:
    """Map Part 6 logical blanks to their question, in document order."""
    if group.get("part") != 6:
        return []
    allowed = set(group["question_ids"])
    seen: list[str] = []
    for material in group.get("materials", []):
        for match in QID_TOKEN.finditer(material.get("text") or ""):
            qid = match.group(1)
            if qid not in allowed:
                raise ValueError(f"{group['id']} 的空位 {qid} 不属于本组")
            if qid not in seen:
                seen.append(qid)
    return [{"index": index, "question_id": qid} for index, qid in enumerate(seen, 1)]


def to_blanks(text: str, entries: list[dict]) -> str:
    mapping = {entry["question_id"]: entry["index"] for entry in entries}
    return QID_TOKEN.sub(lambda match: "{{blank:%d}}" % mapping[match.group(1)], text)


def material_blocks(group: dict, rendered: dict[str, str], blanks: list[dict]) -> list[str]:
    """Render the shared material of a group as Markdown sections.

    Every material owns exactly one heading, so a reader can restore the
    original material order without guessing. The heading kind follows the
    part: Part 7 passages, every other part materials.
    """
    lines: list[str] = []
    label = "Passage" if group["part"] == 7 else "Material"
    for index, material in enumerate(group.get("materials", []), 1):
        lines.append(f"### {label} {index}")
        lines.append("")
        if material.get("kind") == "image":
            alt = material.get("alt") or "题目图片"
            lines.append(f"![{alt}](/api/assets/{material['asset_id']})")
        else:
            text = to_blanks(rendered[material["text"]], blanks)
            # A heading inside the material must not look like a section
            # marker, so it is written one level deeper and read back one
            # level up.
            lines.append(demote_headings(text).rstrip("\n"))
        lines.append("")
    return lines


def demote_headings(text: str) -> str:
    """Push every heading inside a material one level deeper."""
    return re.sub(r"(?m)^(#{1,5})(?=\s)", r"#\1", text)


def question_sections(group: dict, questions: dict[str, dict]) -> list[str]:
    lines: list[str] = [SECTION_OPTIONS, ""]
    for index, qid in enumerate(group["question_ids"], 1):
        question = questions[qid]
        lines.append(f"### 第 {index} 题")
        lines.append("")
        if question.get("stem"):
            lines.append(question["stem"])
            lines.append("")
        for option in question["options"]:
            # The option text is written verbatim: a wrapped option keeps its
            # own line breaks, and the loader reads every line up to the next
            # option label back into the option it belongs to.
            lines.append(f"- {option['id']}. {option['text']}")
        lines.append("")
    return lines


def solution_sections(group: dict, questions: dict[str, dict]) -> list[str]:
    lines: list[str] = [SECTION_SOLUTION, ""]
    for index, qid in enumerate(group["question_ids"], 1):
        question = questions[qid]
        lines.append(f"### 第 {index} 题")
        lines.append("")
        lines.append(f"**答案：{question['answer']}**")
        lines.append("")
        lines.append(question["explanation"]["text"])
        lines.append("")
    return lines


def reserved_markers() -> set[str]:
    markers = {
        SECTION_ORIGINAL, SECTION_OPTIONS, SECTION_SOLUTION,
        HEADING_SCRIPT_EN, HEADING_SCRIPT_ZH, HEADING_SOURCE, NO_MATERIAL,
    }
    markers.update(f"### 第 {index} 题" for index in range(1, 12))
    markers.update(f"### Material {index}" for index in range(1, 12))
    markers.update(f"### Passage {index}" for index in range(1, 12))
    markers.update(f"**答案：{letter}**" for letter in "ABCD")
    return markers


def assert_no_marker_collision(group: dict, texts: list[str]) -> None:
    """A source line must never look like a structural marker of the file."""
    markers = reserved_markers()
    for text in texts:
        for line in (text or "").split("\n"):
            if line.strip() in markers:
                raise ValueError(
                    f"{group['id']} 的原文与文件结构标记冲突：{line.strip()!r}")


def build(pool_root: Path, out_root: Path, layouts_path: Path,
          *, verify_only: bool = False) -> dict:
    pool = json.loads((pool_root / "pool.json").read_text(encoding="utf-8"))
    manifest = json.loads((pool_root / "manifest.json").read_text(encoding="utf-8"))
    assets = {entry["id"]: entry for entry in manifest.get("assets", [])}
    questions = {question["id"]: question for question in pool["questions"]}
    index = LayoutIndex(load_layouts(layouts_path))

    parts = out_root / "parts"
    resolved = parts.resolve()
    # Only the "parts" folder of the chosen output root may be replaced, and
    # the output root has to be the bank folder itself. The check runs even
    # when the folder does not exist yet, so a wrong target can never be
    # created in the first place. A verification run writes into a throwaway
    # folder and never touches the real bank.
    if resolved.parent != out_root.resolve() or resolved.name != "parts":
        raise ValueError(f"拒绝清理项目外目录：{resolved}")
    if not verify_only and out_root.resolve() != pool_root.resolve():
        raise ValueError(f"输出目录必须是题库目录本身：{out_root}")
    if parts.exists():
        shutil.rmtree(parts)

    stats = {
        "groups": 0, "questions": 0, "subtitles": 0,
        "layout_hits": 0, "layout_misses": 0, "materials": 0, "assets": 0,
        "parts": {},
    }
    used_assets: set[str] = set()
    for group in pool["groups"]:
        part = group["part"]
        part_dir = parts / f"part-{part}"
        part_dir.mkdir(parents=True, exist_ok=True)
        blanks = blank_entries(group)
        script = group.get("listening_script") or {}
        source_text = group.get("review_text") or ""
        assert_no_marker_collision(group, [source_text, script.get("english", ""),
                                           script.get("chinese", "")])
        for material in group.get("materials", []):
            assert_no_marker_collision(group, [material.get("text") or ""])
            if material.get("kind") == "image":
                used_assets.add(material["asset_id"])

        rendered: dict[str, str] = {}
        for material in group.get("materials", []):
            text = material.get("text") or ""
            if material.get("kind") == "image":
                continue
            result = index.apply(text)
            if result is None:
                stats["layout_misses"] += 1
                result = text
            else:
                stats["layout_hits"] += 1
            rendered[text] = result
            stats["materials"] += 1

        body: list[str] = [SECTION_ORIGINAL, ""]
        if group.get("audio"):
            body += [HEADING_SCRIPT_EN, "", script.get("english", "").rstrip("\n"), ""]
            body += [HEADING_SCRIPT_ZH, "", script.get("chinese", "").rstrip("\n"), ""]
        if source_text.strip():
            body += [HEADING_SOURCE, ""]
            result = index.apply(source_text)
            if result is None:
                stats["layout_misses"] += 1
                result = source_text
            else:
                stats["layout_hits"] += 1
            body += [result.rstrip("\n"), ""]
        if group.get("materials"):
            body += material_blocks(group, rendered, blanks)
        else:
            body += [NO_MATERIAL, ""]
        body += question_sections(group, questions)
        body += solution_sections(group, questions)

        content = "\n".join(frontmatter(group, blanks) + [""] + body).rstrip("\n") + "\n"
        target = part_dir / f"{group['id']}.md"
        target.write_text(content, encoding="utf-8", newline="\n")
        if group.get("audio"):
            (part_dir / f"{group['id']}.srt").write_text(
                srt_block(group), encoding="utf-8", newline="\n")
            stats["subtitles"] += 1
        stats["groups"] += 1
        stats["questions"] += len(group["question_ids"])
        stats["parts"][str(part)] = stats["parts"].get(str(part), 0) + 1

    missing = [asset for asset in used_assets if asset not in assets]
    if missing:
        raise FileNotFoundError(f"图片资产未登记：{sorted(missing)[:5]}")
    for asset in used_assets:
        path = pool_root / assets[asset]["path"]
        if not path.is_file():
            raise FileNotFoundError(f"图片资产缺失：{path}")
    stats["assets"] = len(used_assets)
    return stats


def compare(existing: Path, fresh: Path) -> list[str]:
    """List differences between the written tree and a fresh generation."""
    problems: list[str] = []
    old_files = sorted(p.relative_to(existing).as_posix()
                       for p in existing.rglob("*") if p.is_file())
    new_files = sorted(p.relative_to(fresh).as_posix()
                       for p in fresh.rglob("*") if p.is_file())
    for name in sorted(set(old_files) - set(new_files)):
        problems.append(f"多余文件：{name}")
    for name in sorted(set(new_files) - set(old_files)):
        problems.append(f"缺少文件：{name}")
    for name in sorted(set(old_files) & set(new_files)):
        if (existing / name).read_bytes() != (fresh / name).read_bytes():
            problems.append(f"内容不一致：{name}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_POOL,
                        help="题库目录，含 pool.json 与 manifest.json")
    parser.add_argument("--out", type=Path, default=DEFAULT_POOL,
                        help="输出目录，题组写入 <out>/parts/part-N/")
    parser.add_argument("--layouts", type=Path, default=DEFAULT_LAYOUTS,
                        help="排版索引 textLayouts.ts")
    parser.add_argument("--check", action="store_true",
                        help="只校验已有输出与重新生成的结果是否一致")
    args = parser.parse_args(argv)

    source = args.source.resolve()
    out = args.out.resolve()
    if not (source / "pool.json").is_file():
        raise FileNotFoundError(f"缺少题库：{source / 'pool.json'}")

    if args.check:
        with tempfile.TemporaryDirectory(prefix="md-pool-check-") as tmp:
            fresh = Path(tmp)
            build(source, fresh, args.layouts, verify_only=True)
            problems = compare(out / "parts", fresh / "parts")
        if problems:
            print("题库 Markdown 与源数据不一致：")
            for problem in problems[:20]:
                print("  " + problem)
            return 1
        print("题库 Markdown 与源数据一致。")
        return 0

    stats = build(source, out, args.layouts)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
