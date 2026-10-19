"""Fail-closed, presentation-only source-absolute subtitle sidecar.

Never repairs source wording or mutates an attempt. Audio bytes are identified
once when the library is loaded; legacy lookups must also match frozen bounds.
"""
import hashlib
import json
import math
import re
from copy import deepcopy


def sentence_units(english: str, part: int) -> list[str]:
    """Keep source wording/labels; protect abbreviations, decimals and domains."""
    if part in (1, 2):
        pieces = re.split(r"(?m)(?=^\([ABCD]\) )", english)
        result = []
        for piece in pieces:
            if not piece.strip():
                continue
            if re.match(r"^\([ABCD]\) ", piece):
                result.append(piece.strip())
            else:
                result.extend(sentence_units(piece.strip(), 4))
        return result
    # A speaker turn is always a new sentence unit, even without punctuation.
    turns = re.split(r"\s+(?=[MW][12]?:\s)", english.strip())
    result = []
    for turn in turns:
        start = 0
        for match in re.finditer(r"[.!?]+[\"'”’)]*(?=\s+|$)", turn):
            punctuation = match[0]
            before = turn[:match.end()]
            if punctuation.startswith("."):
                if ".." in punctuation:
                    continue
                if re.search(r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|Jr|Sr|vs|etc|Ph)\.$", before, re.I):
                    continue
                if re.search(r"\b(?:[ap]\.m|[A-Z])\.$", before):
                    continue
                if re.search(r"\b[ap]\.$", before, re.I) and re.match(r"\s*m\.", turn[match.end():], re.I):
                    continue
                if re.search(r"\b[ap]\.\s+m\.$", before, re.I):
                    continue
            value = turn[start:match.end()].strip()
            if value:
                result.append(value)
            start = match.end()
        tail = turn[start:].strip()
        if tail:
            result.append(tail)
    return result


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_sentences(sentences, script, group, audio):
    """Validate complete exact source segmentation and finite disjoint ranges."""
    if not isinstance(sentences, list) or not sentences or not script or not audio:
        return False
    expected = sentence_units(script["english"], group["part"])
    if len(expected) != len(sentences):
        return False
    previous = audio.get("start_seconds")
    end = audio.get("end_seconds")
    if not (_number(previous) and _number(end) and 0 <= previous < end):
        return False
    for index, (row, text) in enumerate(zip(sentences, expected), 1):
        if not isinstance(row, dict) or row.get("text") != text:
            return False
        if row.get("id") != f"{group['id']}-s{index:03d}":
            return False
        lo, hi = row.get("start_seconds"), row.get("end_seconds")
        if not (_number(lo) and _number(hi) and previous <= lo < hi <= end):
            return False
        previous = hi
    return True


def _matches(entry, group, script, audio):
    return (isinstance(script, dict) and isinstance(audio, dict)
        and entry.get("exam_id") == group.get("exam_id")
        and entry.get("group_id") == group.get("id")
        and entry.get("part") == group.get("part")
        and entry.get("question_ids") == group.get("question_ids")
        and entry.get("english_sha256") == _digest(script.get("english", ""))
        and entry.get("source_pages") == script.get("source_pages")
        and entry.get("asset_id") == audio.get("asset_id")
        and audio.get("url") == f"/api/assets/{entry.get('asset_id')}"
        and entry.get("start_seconds") == audio.get("start_seconds")
        and entry.get("end_seconds") == audio.get("end_seconds"))


def load_subtitle_cues(library):
    """Only publish entries bound to the loaded exact script/cue/audio content."""
    from .listening_review import extract_listening_script
    try:
        data = json.loads((library.root / "subtitle-cues.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1 or not isinstance(data.get("groups"), list)):
        return {}
    result, hashes, duplicates = {}, {}, set()
    for entry in data["groups"]:
        if not isinstance(entry, dict):
            continue
        key = (entry.get("exam_id"), entry.get("group_id"))
        if not all(isinstance(v, str) for v in key):
            continue
        if key in duplicates:
            result.pop(key, None)
            continue
        duplicates.add(key)
        if (type(entry.get("part")) is not int
            or not all(_number(entry.get(k)) for k in ("start_seconds", "end_seconds", "source_duration_seconds"))
            or not isinstance(entry.get("source_pages"), list)
            or not entry["source_pages"] or any(type(p) is not int or p < 1 for p in entry["source_pages"])):
            continue
        exam = library.exams.get(key[0])
        group = next((g for g in exam.groups if g.get("id") == key[1]), None) if exam else None
        provenance = entry.get("provenance")
        if (not group or entry.get("verified") is not True or not exam.validated
            or not exam.cues_verified or not isinstance(provenance, dict)
            or provenance.get("method") != "source-word-alignment-v1"
            or type(provenance.get("acoustic_version")) is not int or provenance["acoustic_version"] != 1
            or not isinstance(provenance.get("evidence"), str) or not provenance["evidence"]):
            continue
        cue = library.group_cue_for(exam, group)
        if not cue or not cue.verified or not exam.audio:
            continue
        script = extract_listening_script(group, exam.questions)
        audio = {"asset_id": exam.audio["asset_id"], "url": f"/api/assets/{exam.audio['asset_id']}",
                 "start_seconds": cue.start_seconds, "end_seconds": cue.end_seconds}
        duration = entry.get("source_duration_seconds")
        if (not _number(duration) or duration != exam.audio.get("duration_seconds")
            or not (0 <= exam.full_start_seconds <= cue.start_seconds < cue.end_seconds <= exam.full_end_seconds <= duration)
            or not _matches(entry, {**group, "exam_id": exam.id}, script, audio)
            or not valid_sentences(entry.get("sentences"), script, group, audio)):
            continue
        asset_id = audio["asset_id"]
        if asset_id not in hashes:
            try:
                path, _ = library.asset_path(asset_id)
                with path.open("rb") as stream:
                    hashes[asset_id] = hashlib.file_digest(stream, "sha256").hexdigest()
            except (KeyError, OSError):
                hashes[asset_id] = None
        if not hashes[asset_id] or entry.get("asset_sha256") != hashes[asset_id]:
            continue
        result[key] = deepcopy(entry)
    return result


def enrich_script(library, group, script, audio, *, frozen=False, quality_verified=False):
    """Snapshot or derive timing only. An invalid complete set is omitted."""
    if not script:
        return None
    value = deepcopy(script)
    sentences = value.pop("sentences", None)
    if sentences is not None and quality_verified:
        if valid_sentences(sentences, value, group, audio):
            value["sentences"] = sentences
        return value
    if frozen:
        return value
    entry = library.subtitle_cues.get((group.get("exam_id"), group.get("id")))
    if entry and _matches(entry, group, script, audio):
        value["sentences"] = deepcopy(entry["sentences"])
    return value
