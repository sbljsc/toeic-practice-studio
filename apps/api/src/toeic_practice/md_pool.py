"""Load the plain-Markdown question bank into the pool shapes.

The Markdown tree holds one file per question group. This loader rebuilds the
exact group and question structures that ``pool.json`` used to provide, so
every consumer (attempts, random assembly, browsing, vocabulary) keeps
working unchanged. Validation is at least as strict as the JSON loader: a
single invalid group makes the whole bank unavailable.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .pool_library import positive_number
from .subtitle_cues import valid_sentences

QUESTION_HEADING = re.compile(r"^###\s+第\s*(\d+)\s*题\s*$")
OPTION_LINE = re.compile(r"^\s*-\s*([A-D])\.\s*(.*)$")
OPTION_PAREN = re.compile(r"^\s*[（(]\s*([A-D])\s*[）)]\s*(.*)$")
OPTION_BLOCK = re.compile(r"^\s*[（(]\s*$")
OPTION_BLOCK_CLOSE = re.compile(r"^\s*[）)]\s*$")
OPTION_BLOCK_LABEL = re.compile(r"^\s*([A-D])\s*$")
ANSWER_LINE = re.compile(r"^\*\*答案：([A-D])\*\*\s*$")
BLANK_TOKEN = re.compile(r"\{\{blank:(\d+)\}\}")
SRT_TIME = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")
MATERIAL_HEADING = re.compile(r"^###\s+(?:Material|Passage)\s+(\d+)\s*$")
# The generator and older files name the same blocks differently; both are read.
SCRIPT_EN = ("### Transcript", "### 听力原文")
SCRIPT_ZH = ("### Transcript (zh)", "### 中文原文")
SOURCE_HEADING = ("### 教材原文", "### Review")
NO_MATERIAL = "（本题无附加材料）"


def _scalar(text: str):
    if text == "null":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def parse_frontmatter(text: str) -> dict:
    """Parse the small YAML subset used by the question files."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("缺少 frontmatter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("frontmatter 未闭合")
    values: dict = {}
    key = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.lstrip().startswith("- ") and raw.startswith("  "):
            if key is None:
                raise ValueError("frontmatter 列表项缺少所属键")
            if not isinstance(values.get(key), list):
                raise ValueError("frontmatter 键类型冲突")
            item = raw.strip()[2:].strip()
            if ":" in item:
                name, _, rest = item.partition(":")
                values[key].append({name.strip(): _scalar(rest.strip())})
            else:
                values[key].append(_scalar(item))
            continue
        if raw.startswith("    ") and isinstance(values.get(key), list) and values[key] \
                and isinstance(values[key][-1], dict):
            name, _, rest = raw.strip().partition(":")
            if not rest.strip():
                raise ValueError("frontmatter 行格式无效")
            values[key][-1][name.strip()] = _scalar(rest.strip())
            continue
        if ":" not in raw:
            raise ValueError("frontmatter 行格式无效")
        name, _, rest = raw.partition(":")
        key = name.strip()
        rest = rest.strip()
        values[key] = [] if rest == "" else _scalar(rest)
    return values


def _chapters(text: str) -> dict[str, str]:
    """Split the body into the three fixed chapters."""
    lines = text.split("\n")
    start = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if start is None:
        raise ValueError("frontmatter 未闭合")
    headings = ("## 原文", "## 选项", "## 答案 / 题解")
    found: dict[str, list[str]] = {}
    current = None
    for line in lines[start + 1:]:
        if line.strip() in headings:
            current = line.strip()
            found[current] = []
            continue
        if current is not None:
            found[current].append(line)
    # A group without shared material may omit the original chapter.
    missing = [h for h in headings if h not in found and h != "## 原文"]
    if missing:
        raise ValueError(f"缺少章节：{'、'.join(missing)}")
    found.setdefault("## 原文", [])
    return {h: "\n".join(body) for h, body in found.items()}


def _materials(section: str) -> tuple[list[dict], dict]:
    """Rebuild the shared material and the embedded script of a group."""
    blocks = _split_materials(section)
    parts: list[dict] = []
    script = {"english": "", "chinese": "", "review": ""}
    for kind, body in blocks:
        if kind == "script-en":
            script["english"] = body
        elif kind == "script-zh":
            script["chinese"] = body
        elif kind == "review":
            script["review"] = body
        elif kind == "material":
            text, image = _material_body(body)
            if image is not None:
                parts.append(image)
            elif text:
                parts.append({"kind": "text", "text": text})
    return parts, script


def _split_materials(section: str) -> list[tuple[str, str]]:
    """Split the original section into its script, review and materials."""
    blocks: list[tuple[str, str]] = []
    kind = ""
    body: list[str] = []
    for line in section.split("\n"):
        stripped = line.strip()
        if stripped in SCRIPT_EN:
            if kind:
                blocks.append((kind, "\n".join(body).strip("\n")))
            kind, body = "script-en", []
            continue
        if stripped in SCRIPT_ZH:
            if kind:
                blocks.append((kind, "\n".join(body).strip("\n")))
            kind, body = "script-zh", []
            continue
        if stripped in SOURCE_HEADING:
            if kind:
                blocks.append((kind, "\n".join(body).strip("\n")))
            kind, body = "review", []
            continue
        if MATERIAL_HEADING.match(stripped):
            if kind:
                blocks.append((kind, "\n".join(body).strip("\n")))
            kind, body = "material", []
            continue
        if stripped == NO_MATERIAL:
            continue
        if kind:
            body.append(line)
    if kind:
        blocks.append((kind, "\n".join(body).strip("\n")))
    return blocks


def _material_body(body: str) -> tuple[str, dict | None]:
    """Read one material block as text or as a picture reference."""
    lines = body.split("\n")
    images = [line.strip() for line in lines if line.strip().startswith("![")]
    if images and len(images) == len([line for line in lines if line.strip()]):
        match = re.fullmatch(r"!\[(.*?)\]\(([^)]+)\)", images[0])
        if not match:
            raise ValueError("图片引用格式无效")
        url = match.group(2)
        if not re.fullmatch(r"/api/assets/[A-Za-z0-9_-]+", url):
            raise ValueError("图片引用地址无效")
        return "", {"kind": "image", "asset_id": url.rsplit("/", 1)[-1], "alt": match.group(1)}
    text = "\n".join(lines).strip("\n")
    # A heading inside a material is stored one level deeper than it reads.
    text = re.sub(r"(?m)^####(#{0,5})(?=\s)", r"###\1", text)
    return text, None


def _question_blocks(section: str) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    current: int | None = None
    body: list[str] = []
    for line in section.split("\n"):
        match = QUESTION_HEADING.match(line.strip())
        if match:
            if current is not None:
                blocks.append((current, body))
            current = int(match.group(1))
            body = []
            continue
        if current is not None:
            body.append(line)
    if current is not None:
        blocks.append((current, body))
    return blocks


def _parse_options(body: list[str]) -> tuple[str, list[dict]]:
    """Read the stem and the options of one question."""
    stem_lines: list[str] = []
    # Every option is a labelled line; the lines that follow it belong to it
    # until the next label, so a wrapped option keeps its own line breaks.
    options: list[dict] = []
    at = 0
    while at < len(body):
        line = body[at]
        match = OPTION_LINE.match(line)
        paren = OPTION_PAREN.match(line)
        block = OPTION_BLOCK.match(line)
        if not match and not paren and not block:
            stem_lines.append(line)
            at += 1
            continue
        if block:
            label, text_lines, at = _read_block_option(body, at)
        elif match:
            label, text_lines = match.group(1), [match.group(2)]
            at += 1
            while at < len(body) and not OPTION_LINE.match(body[at]) \
                    and not OPTION_PAREN.match(body[at]) and not OPTION_BLOCK.match(body[at]):
                text_lines.append(body[at])
                at += 1
        else:
            label, text_lines = paren.group(1), [paren.group(2)]
            at += 1
            while at < len(body) and not OPTION_LINE.match(body[at]) \
                    and not OPTION_PAREN.match(body[at]) and not OPTION_BLOCK.match(body[at]):
                text_lines.append(body[at])
                at += 1
        while text_lines and not text_lines[-1].strip():
            text_lines.pop()
        options.append({"id": label, "text": "\n".join(text_lines)})
    stem = "\n".join(stem_lines).strip("\n").strip()
    return stem, options


def _read_block_option(body: list[str], at: int) -> tuple[str, list[str], int]:
    """Read the ``（\\nA\\n）`` form an older extract uses."""
    label_at = at + 1
    while label_at < len(body) and not body[label_at].strip():
        label_at += 1
    if label_at >= len(body) or not OPTION_BLOCK_LABEL.match(body[label_at]):
        raise ValueError("选项格式无效")
    close = label_at + 1
    while close < len(body) and not body[close].strip():
        close += 1
    if close >= len(body) or not OPTION_BLOCK_CLOSE.match(body[close]):
        raise ValueError("选项格式无效")
    text_lines: list[str] = []
    scan = close + 1
    while scan < len(body) and not OPTION_LINE.match(body[scan]) \
            and not OPTION_PAREN.match(body[scan]) and not OPTION_BLOCK.match(body[scan]):
        text_lines.append(body[scan])
        scan += 1
    return body[label_at].strip(), text_lines, scan


def _parse_solution(body: list[str]) -> tuple[str, str]:
    """Read the answer letter and the verbatim solution text."""
    answer = ""
    rest: list[str] = []
    for line in body:
        match = ANSWER_LINE.match(line.strip())
        if match and not answer:
            answer = match.group(1)
            continue
        rest.append(line)
    text = "\n".join(rest).strip("\n")
    lines = text.split("\n")
    if len(lines) >= 2 and lines[0].strip() == "```" and lines[-1].strip() == "```":
        text = "\n".join(lines[1:-1])
    # The textbook solution is kept verbatim, so only the blank lines the
    # file layout adds around it are removed.
    return answer, text.strip("\n")


def parse_md_group(text: str, filename: str) -> tuple[dict, list[dict]]:
    """Parse one group file into its group and its questions."""
    values = parse_frontmatter(text)
    chapters = _chapters(text)
    group_id = values.get("group_id")
    part = values.get("part")
    if not isinstance(group_id, str) or not group_id:
        raise ValueError("题组编号无效")
    if type(part) is not int or part not in range(1, 8):
        raise ValueError("题组 Part 无效")
    section = values.get("section")
    if section != ("listening" if part <= 4 else "reading"):
        raise ValueError("题组分区无效")
    entries = values.get("questions")
    if not isinstance(entries, list) or not entries:
        raise ValueError("题组缺少题目")

    option_blocks = _question_blocks(chapters["## 选项"])
    solution_blocks = _question_blocks(chapters["## 答案 / 题解"])
    if len(option_blocks) != len(entries) or len(solution_blocks) != len(entries):
        raise ValueError("选项或题解章节的题号数量与 frontmatter 不一致")

    questions: list[dict] = []
    for position, entry in enumerate(entries, 1):
        qid = entry.get("id")
        if not isinstance(qid, str) or not qid:
            raise ValueError("题目编号无效")
        if entry.get("index") != position:
            raise ValueError("题目组内序号无效")
        number, body = option_blocks[position - 1]
        if number != position:
            raise ValueError("选项章节题号与 frontmatter 不一致")
        stem, options = _parse_options(body)
        answer, solution = _parse_solution(solution_blocks[position - 1][1])
        questions.append({
            "id": qid,
            "canonical_id": "bank:" + qid,
            "part": part,
            "section": section,
            "group_id": group_id,
            "stem": stem,
            "options": options,
            "answer": answer,
            "source_pages": [],
            "explanation": {"text": solution, "source_pages": []},
        })

    materials, transcript = _materials(chapters["## 原文"])
    mapping = _blank_map(values)
    for material in materials:
        if material["kind"] == "text":
            material["text"] = _restore_blanks(material["text"], mapping)
    group = {
        "id": group_id,
        "part": part,
        "section": section,
        "question_ids": [q["id"] for q in questions],
        "materials": materials,
        "review_text": "",
        "source_pages": [],
    }
    if part == 7:
        group["passage_type"] = values.get("passage_type")
    group["transcript"] = transcript
    return group, questions


def parse_srt(text: str, group_id: str) -> list[dict]:
    """Parse a subtitle file into the sentence rows the player needs."""
    rows: list[dict] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue
        match = SRT_TIME.search(lines[1])
        if not match:
            raise ValueError("字幕时间格式无效")
        start = _seconds(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _seconds(match.group(5), match.group(6), match.group(7), match.group(8))
        rows.append({
            "id": f"{group_id}-s{len(rows) + 1:03d}",
            "text": "\n".join(lines[2:]),
            "start_seconds": start,
            "end_seconds": end,
        })
    return rows


def _seconds(hours: str, minutes: str, secs: str, millis: str) -> float:
    # Milliseconds are kept exact so a time never drifts by a rounding step.
    total = ((int(hours) * 3600 + int(minutes) * 60 + int(secs)) * 1000
             + int(millis.ljust(3, "0")))
    return total / 1000


def _blank_map(values: dict) -> dict[int, str]:
    entries = values.get("blanks") or []
    mapping: dict[int, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("空位映射无效")
        index, qid = entry.get("index"), entry.get("question_id")
        if type(index) is not int or not isinstance(qid, str) or not qid:
            raise ValueError("空位映射无效")
        mapping[index] = qid
    return mapping


def _restore_blanks(text: str, mapping: dict[int, str]) -> str:
    def replace(match: re.Match) -> str:
        index = int(match.group(1))
        if index not in mapping:
            raise ValueError("材料引用了未登记的空位")
        return "{{qid:" + mapping[index] + "}}"
    return BLANK_TOKEN.sub(replace, text)


def load_md_pool(library, root: Path) -> None:
    """Read the Markdown bank and publish it as the pool exam."""
    from .library import Exam
    try:
        root = Path(root).resolve()
        manifest = library.manifest
        entry = manifest.get("pool") or {}
        if entry.get("format") not in (None, "md"):
            raise ValueError("题库格式不受支持")
        if manifest.get("validated") is not True and manifest.get("schema_version") != 3:
            raise ValueError("题库尚未通过校验")
        registrations = manifest.get("assets", [])
        if not isinstance(registrations, list) or not all(isinstance(a, dict) for a in registrations):
            raise ValueError("资产登记格式无效")
        library.assets = {}
        for asset in registrations:
            if not isinstance(asset.get("id"), str) or asset["id"] in library.assets:
                raise ValueError("资产编号无效或重复")
            library.assets[asset["id"]] = asset
            asset_path, _ = library.asset_path(asset["id"])
            expected = asset.get("sha256")
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError("缺少资产校验和")
            with asset_path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError("资产校验和不一致")

        parts_root = root / "parts"
        if not parts_root.is_dir():
            raise ValueError("题库目录缺失")
        files = sorted(parts_root.glob("part-*/*.md"))
        if not files:
            raise ValueError("题库目录为空")

        questions: list[dict] = []
        groups: list[dict] = []
        qmap: dict[str, dict] = {}
        gmap: dict[str, dict] = {}
        canonical: set[str] = set()

        for path in files:
            source = path.read_text(encoding="utf-8")
            group, group_questions = parse_md_group(source, path.name)
            gid = group["id"]
            if gid in gmap:
                raise ValueError("材料编号重复")
            part = group["part"]
            gmap[gid] = group
            groups.append(group)

            values = parse_frontmatter(source)
            mapping = _blank_map(values)
            if part == 6 and mapping:
                expected = [entry["question_id"] for entry in values["blanks"]]
                if expected != group["question_ids"]:
                    raise ValueError("空位与题目顺序不一致")

            if part <= 4:
                asset_id = values.get("audio_asset") or values.get("audio")
                if not isinstance(asset_id, str) or not asset_id:
                    raise ValueError("听力组缺少录音")
                if asset_id.endswith(".flac"):
                    asset_id = asset_id[:-5]
                if asset_id not in library.assets:
                    raise ValueError("录音资产未登记")
                duration = library.assets[asset_id].get("duration_seconds")
                if not positive_number(duration):
                    raise ValueError("录音时长未登记")
                transcript = group.pop("transcript", {})
                script = _script_from(values, path, gid, part, duration, transcript)
                group["audio"] = {"asset_id": asset_id, "start_seconds": 0,
                                  "end_seconds": duration, "verified": True}
                group["listening_script"] = script
                group["review_text"] = transcript.get("review", "")
            else:
                # A reading group keeps the textbook copy as its review text.
                group["review_text"] = group.pop("transcript", {}).get("review", "")

            for question in group_questions:
                qid = question["id"]
                options = question["options"]
                if (qid in qmap or question["canonical_id"] in canonical
                        or question["group_id"] != gid
                        or [o["id"] for o in options] != list("ABC" if part == 2 else "ABCD")
                        or question["answer"] not in [o["id"] for o in options]
                        or not question["explanation"]["text"].strip()):
                    raise ValueError("题目编号、题型或答案无效")
                question["number"] = len(questions) + 1
                canonical.add(question["canonical_id"])
                qmap[qid] = question
                questions.append(question)

        for group in groups:
            ids = group["question_ids"]
            expected = {1: 1, 2: 1, 3: 3, 4: 3, 5: 1, 6: 4}.get(group["part"])
            if expected and len(ids) != expected:
                raise ValueError("共享材料题量不符合题型")
            if group["part"] == 7 and (group.get("passage_type") not in ("single", "double", "triple")
                    or len(ids) not in ([2, 3, 4] if group["passage_type"] == "single" else [5])):
                raise ValueError("阅读材料类型或题量无效")
            for material in group["materials"]:
                if material.get("kind") == "image" and material["asset_id"] not in library.assets:
                    raise ValueError("图片资产未登记")

        covered = {qid for group in groups for qid in group["question_ids"]}
        if covered != set(qmap):
            raise ValueError("存在无所属材料的题目")

        library.pool_mode = True
        library.exams = {"pool": Exam(id="pool", title="随机题库", version=library.manifest_version,
            question_count=len(questions), validated=True, questions=questions, groups=groups,
            cues_verified=True)}
        library.sources = {}
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        library.exams = {}
        library.load_error = f"独立题库无法加载：{error}"


def _script_from(values: dict, path: Path, gid: str, part: int, duration: float,
                 transcript: dict) -> dict:
    """Rebuild the listening script and its sentence timings."""
    subtitles_name = values.get("subtitles")
    if not isinstance(subtitles_name, str) or not subtitles_name:
        raise ValueError("听力组缺少字幕")
    srt_path = path.parent / subtitles_name
    if not srt_path.is_file():
        raise ValueError("字幕文件缺失")
    sentences = parse_srt(srt_path.read_text(encoding="utf-8"), gid)
    english = transcript.get("english", "")
    if not english.strip():
        raise ValueError("听力组缺少原文")
    script = {"english": english, "chinese": transcript.get("chinese", ""),
              "source_pages": [], "sentences": sentences}
    audio = {"asset_id": "", "start_seconds": 0, "end_seconds": duration}
    if not valid_sentences(sentences, script, group_for(gid, part), audio):
        raise ValueError("逐句字幕与音频边界不一致")
    return script


def group_for(gid: str, part: int) -> dict:
    """A minimal group view used by the sentence validator."""
    return {"id": gid, "part": part}

