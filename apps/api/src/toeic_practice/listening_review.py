"""Private review extraction for the fixed built-in textbook layout.

Only copy source text; no translations, audio inference or external services.
An unrecognized layout returns None (the original explanation remains usable).
This is structural extraction, not an assertion of independent audio verification.
Both source records and frozen attempt records can be used without a Library.
"""
import re
from copy import deepcopy
from math import isfinite


_HAN = re.compile(r"[\u3400-\u9fff]")
_OPTION = re.compile(r"[（(]\s*([ABCD])\s*[）)]")
_SPEAKER = re.compile(r"(?m)^\s*([MW][12]?)\s*[:：]\s*")
_ANNOTATION = re.compile(r"[（(]\s*(?:Q\s*)?(\d+(?:\s*[,，、]\s*(?:Q\s*)?\d+)*)\s*[）)]")
_EN_END = re.compile(r"[.!?](?!\d)[\"'”’)]*")
_ZH_END = re.compile(r"[。！？][”’）」]*")


def _text(value: str, chinese: bool = False) -> str:
    # Keep turns on separate lines while repairing PDF line wraps within a turn.
    if chinese:
        # One prepared source prints a standalone W without its colon. Keep the
        # printed speaker identity; only normalize the turn's display separator.
        value = re.sub(r"(?m)^([MW][12]?)[ \t]*\n\s*(?=[\u3400-\u9fff])", r"\1: ", value)
    turns = _SPEAKER.sub(lambda m: "\n" + m[1] + ": ", value).strip()
    lines = []
    for turn in re.split(r"\n(?=[MW][12]?: )", turns):
        turn = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "-", turn)
        turn = re.sub(r"\s+", " ", turn).strip()
        if chinese:
            # Chinese PDF line wraps include numbers/Latin names on their own lines.
            turn = re.sub(r"(?<=[\u3400-\u9fff。！？、，：；（）“”]) +| +(?=[\u3400-\u9fff。！？、，：；（）“”])", "", turn)
            turn = re.sub(r"^([MW][12]?):\s*", r"\1: ", turn)
        if turn:
            lines.append(turn)
    return "\n".join(lines)


def _split_languages(value: str) -> tuple[str, str] | None:
    first = _HAN.search(value)
    if not first:
        return None
    # Chinese can start with an English name/acronym, so use the last complete
    # English utterance rather than throwing away everything before the first Han.
    ends = list(_EN_END.finditer(value[:first.start()]))
    if not ends:
        return None
    end = ends[-1].end()
    return value[:end].strip(), value[end:].strip()


def _short_script(part: int, raw: str) -> tuple[str, str] | None:
    labels = "ABCD" if part == 1 else "ABC"
    matches = list(_OPTION.finditer(raw))
    if "".join(m[1] for m in matches) != labels * 2:
        return None
    blocks = [raw[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(raw)].strip()
              for i, m in enumerate(matches)]
    count = len(labels)
    english_question = raw[:matches[0].start()].strip()
    if part == 1:
        if english_question:
            return None
        chinese_question = ""
        blocks[-1] = re.split(r"[·•]", blocks[-1], maxsplit=1)[0].strip()
    else:
        split = _split_languages(blocks[count - 1])
        if not split:
            return None
        blocks[count - 1], chinese_question = split
        if not english_question or not _HAN.search(chinese_question):
            return None
        blocks[-1] = re.split(r"(?m)^\s*Q\s+", blocks[-1], maxsplit=1)[0].strip()
    if any(not b or _HAN.search(b) for b in blocks[:count]) or _HAN.search(english_question):
        return None
    if any(not _HAN.search(b) for b in blocks[count:]):
        return None
    # Foreign sentences after the final translated option are enrichment, never
    # spoken core. Refuse unknown suffixes rather than guessing where they end.
    if re.search(r"[A-Za-z]{3,}", blocks[-1]):
        return None
    en = ([english_question] if english_question else []) + [f"({label}) {_text(b)}" for label, b in zip(labels, blocks[:count])]
    zh = ([_text(chinese_question, True)] if chinese_question else []) + [f"({label}) {_text(b, True)}" for label, b in zip(labels, blocks[count:])]
    return "\n".join(en), "\n".join(zh)


def listening_heading(raw: str):
    # One prepared source omits the full stop after the standalone heading
    # "talk". Its explicit line boundary must not consume the first utterance.
    return re.match(r"\s*Questions\s+(\d+)\s+through\s+(\d+)\s+refer to the following\s+"
                    r"(talk[ \t]*(?=\r?\n)|[^.]+)\.?\s*", raw)


def _shared_script(part: int, raw: str, numbers: set[int]) -> tuple[str, str] | None:
    heading = listening_heading(raw)
    if not heading or not numbers or (int(heading[1]), int(heading[2])) != (min(numbers), max(numbers)):
        return None
    raw = raw[heading.end():]

    def remove_marker(match):
        found = {int(n) for n in re.findall(r"\d+", match[1])}
        return " " if found <= numbers else match[0]

    raw = _ANNOTATION.sub(remove_marker, raw)
    first = _HAN.search(raw)
    if not first:
        return None
    # The first translated speaker label belongs to Chinese, including when the
    # source places the colon and the first character on different PDF lines.
    before = raw[:first.start()]
    speaker = re.search(r"(?m)^\s*[MW][12]?\s*[:：]\s*\Z", before)
    if part == 3 and not speaker:
        return None
    split = speaker.start() if speaker else first.start()
    english, chinese = raw[:split].strip(), raw[split:].strip()
    en_ends = list(_EN_END.finditer(english))
    zh_ends = list(_ZH_END.finditer(chinese))
    if not en_ends or not zh_ends:
        return None
    en_end, zh_end = en_ends[-1].end(), zh_ends[-1].end()
    en_tail, zh_tail = english[en_end:].strip(), chinese[zh_end:].strip()
    # A leading acronym (CTV) in the translation must survive. Other tail text
    # is an unspoken graphic caption; the source heading explicitly identifies it.
    if en_tail:
        if part == 4 and re.fullmatch(r"[A-Z]{2,8}", en_tail):
            chinese = en_tail + chinese
            zh_end += len(en_tail)
        elif " and " not in re.sub(r"\s+", " ", heading[0]):
            return None
    # In these prepared textbooks the Chinese spoken core ends at its final full
    # sentence; after it are optional graphic captions and bilingual vocabulary
    # fragments. Unknown complete trailing sentences must not be treated as vocab.
    if zh_tail and not (re.search(r"(?m)^\s*[A-Za-z][^\n]*\n", zh_tail) and _HAN.search(zh_tail)):
        return None
    english, chinese = english[:en_end], chinese[:zh_end]
    # This printed advertisement title follows the complete meeting transcript.
    # It has no spoken counterpart in the source audio. Preserve it in the
    # original review text and existing Chinese block, never invent a cue for it.
    caption = "\nSee Jennifer Evans perform live!"
    if (part == 4 and "advertisement" in heading[3]
            and english.endswith(caption)):
        english = english[:-len(caption)].rstrip()
    if _ANNOTATION.search(english) or (part == 3 and not _SPEAKER.match(english)):
        return None
    # The book sometimes prints different M/W labels in the translation. Copy
    # both as printed; never invent corrected speaker identities from the audio.
    return _text(english), _text(chinese, True)


def extract_listening_script(group: dict, questions: list[dict]) -> dict | None:
    """Return the core bilingual source script, or explicit safe missing state.

    A frozen group uses _review_text/_review_source_pages; frozen questions use
    _explanation. Never supplement missing history from the current library.
    """
    part = group.get("part")
    if part not in (1, 2, 3, 4):
        return None
    by_id = {q["id"]: q for q in questions}
    selected = [by_id[qid] for qid in group.get("question_ids", []) if qid in by_id]
    if not selected or len(selected) != len(group.get("question_ids", [])):
        return None
    explanations = [q.get("_explanation", q.get("explanation")) or {} for q in selected]
    if part <= 2:
        if len(selected) != 1:
            return None
        pair = _short_script(part, explanations[0].get("text") or "")
    else:
        pair = _shared_script(part, group.get("_review_text", group.get("review_text")) or "",
                              {q["number"] for q in selected})
    if pair is None:
        return None
    pages = group.get("_review_source_pages", group.get("review_source_pages"))
    if not pages:
        pages = sorted({p for explanation in explanations for p in explanation.get("source_pages", [])})
    if not pages or any(type(p) is not int or p < 1 for p in pages):
        return None
    return {"english": pair[0], "chinese": pair[1], "source_pages": list(pages)}


def frozen_group_audio(group: dict, queue: list[dict]) -> dict | None:
    """Legacy replay is allowed only for an exact group clip in its own queue."""
    for item in queue:
        if (item.get("group_id") == group["id"] and item.get("exam_id") == group.get("exam_id")
                and item.get("part") == group.get("part")
                and item.get("question_ids") == group.get("question_ids")):
            start, end = item.get("start_seconds"), item.get("end_seconds")
            if (isinstance(start, (int, float)) and isinstance(end, (int, float))
                    and isfinite(start) and isfinite(end) and 0 <= start < end):
                return deepcopy(item)
    return None
