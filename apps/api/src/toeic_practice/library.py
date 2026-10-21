"""Fixed built-in library loader.

Reads the dataset-owner manifest/exam JSON, merges the primary's
audio-cues.json (matched by question-number range, never group-id spelling),
and computes per-part/exam readiness. Missing files or unvalidated exams stay
visible with reasons instead of failing the whole catalog.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

PART_RANGES = {1: (1, 6), 2: (7, 31), 3: (32, 70), 4: (71, 100), 5: (101, 130), 6: (131, 146), 7: (147, 200)}
LISTENING_PARTS = (1, 2, 3, 4)
READING_PARTS = (5, 6, 7)


@dataclass
class GroupCue:
    part: int
    first_question: int
    last_question: int
    start_seconds: float
    end_seconds: float
    verified: bool


@dataclass
class Exam:
    id: str
    title: str
    version: str
    question_count: int
    validated: bool
    questions: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    audio: dict | None = None
    part_cues: list = field(default_factory=list)
    group_cues: list = field(default_factory=list)
    full_start_seconds: float = 0.0
    full_end_seconds: float = 0.0
    cues_verified: bool = False
    blockers: list = field(default_factory=list)

    @property
    def listening_seconds(self) -> float:
        return max(0.0, self.full_end_seconds - self.full_start_seconds)


class Library:
    """Loads and serves the fixed library; read-only with respect to disk."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.exams: dict = {}
        self.assets: dict = {}
        self.sources: dict = {}
        self.subtitle_cues: dict = {}
        self.manifest_version = ""
        self.manifest: dict = {}
        self._loaded = False
        self.load_error: str | None = None
        self.pool_mode = False

    @property
    def available(self) -> bool:
        return self._loaded and self.load_error is None

    @staticmethod
    def _fingerprint(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        except OSError:
            return "unreadable"

    def load(self) -> None:
        # Build separately, then publish one complete state. All services retain
        # this Library identity, including after restore; no stale service cache.
        fresh = Library(self.root)
        fresh._load_from_disk()
        self.__dict__ = fresh.__dict__

    def _load_from_disk(self) -> None:
        self._loaded = True
        manifest_path = self.root / "manifest.json"
        if not manifest_path.is_file():
            self.load_error = "内置题库尚未就绪：缺少 manifest.json"
            return
        try:
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.load_error = "内置题库 manifest.json 无法解析"
            return
        if self.manifest.get("schema_version") == 2:
            self.manifest_version = str(self.manifest.get("version", ""))
            from .pool_library import load_pool
            load_pool(self)
            return
        if self.manifest.get("schema_version") == 3:
            self.manifest_version = str(self.manifest.get("version", ""))
            from .md_pool import load_md_pool
            load_md_pool(self, self.root)
            return
        if self.manifest.get("schema_version") != 1:
            self.load_error = "内置题库 schema_version 不受支持"
            return
        self.manifest_version = str(self.manifest.get("version", ""))
        self.assets = {a["id"]: a for a in self.manifest.get("assets", [])}
        self.sources = {s["id"]: s for s in self.manifest.get("sources", [])}
        cues = self._load_cues()
        for entry in self.manifest.get("exams", []):
            exam = self._load_exam(entry, cues.get(entry["id"]))
            self.exams[exam.id] = exam
        from .subtitle_cues import load_subtitle_cues
        self.subtitle_cues = load_subtitle_cues(self)

    def _load_cues(self) -> dict:
        cues_path = self.root / "audio-cues.json"
        if not cues_path.is_file():
            return {}
        try:
            data = json.loads(cues_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if data.get("schema_version") != 1:
            return {}
        return data.get("exams", {}) or {}

    def _load_exam(self, entry: dict, cues: dict | None) -> Exam:
        exam = Exam(
            id=entry["id"],
            title=entry.get("title", entry["id"]),
            version=entry.get("version", ""),
            question_count=int(entry.get("question_count", 0)),
            validated=bool(entry.get("validated", False)),
        )
        root = self.root.resolve()
        path = (root / entry.get("path", f"exams/{exam.id}.json")).resolve()
        if not path.is_relative_to(root):
            exam.blockers.append("试卷文件路径超出受控题库")
            return exam
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            exam.blockers.append(f"试卷文件 {entry.get('path')} 缺失或无法解析")
            return exam
        exam.questions = raw.get("questions", [])
        exam.groups = raw.get("groups", [])
        exam.audio = raw.get("audio")
        exam.question_count = len(exam.questions)
        self._merge_cues(exam, cues)
        exam.blockers.extend(self._exam_blockers(exam))
        return exam

    def _merge_cues(self, exam: Exam, cues: dict | None) -> None:
        if not cues:
            return
        exam.cues_verified = bool(cues.get("verified"))
        declared = float((exam.audio or {}).get("duration_seconds") or 0.0)
        if "exam_window" in cues and not self._valid_exam_window(cues, declared):
            exam.cues_verified = False
            exam.full_start_seconds = 0.0
            exam.full_end_seconds = declared if math.isfinite(declared) and declared > 0 else 0.0
            exam.blockers.append("已校准的考试音频起止点无效或尚未核验")
            return
        exam.full_start_seconds = float(cues.get("full_start_seconds", 0.0) or 0.0)
        exam.full_end_seconds = float(cues.get("full_end_seconds", 0.0) or 0.0)
        # Legacy cues retain the whole file. A separately verified exam window
        # excludes only packaging, after its closing marker and all registered
        # material ranges have been checked. Source media is never rewritten.
        if "exam_window" not in cues and declared > exam.full_end_seconds:
            exam.full_end_seconds = declared
        exam.part_cues = [p for p in cues.get("parts", []) if p.get("verified")]
        exam.group_cues = [
            GroupCue(
                part=int(g["part"]),
                first_question=int(g["first_question"]),
                last_question=int(g["last_question"]),
                start_seconds=float(g["start_seconds"]),
                end_seconds=float(g["end_seconds"]),
                verified=bool(g.get("verified")),
            )
            for g in cues.get("groups", [])
            if g.get("verified")
        ]

    @staticmethod
    def _valid_exam_window(cues: dict, declared: float) -> bool:
        window = cues.get("exam_window")
        if not isinstance(window, dict) or window.get("verified") is not True:
            return False
        try:
            start, end = float(cues["full_start_seconds"]), float(cues["full_end_seconds"])
            window_start, window_end = float(window["start_seconds"]), float(window["end_seconds"])
            opening = float(window["opening_start_seconds"])
            closing = float(window["closing_start_seconds"])
            closing_end = float(window["closing_end_seconds"])
            values = (declared, start, end, window_start, window_end, opening, closing, closing_end)
            if not all(math.isfinite(value) for value in values):
                return False
            if not (0 <= start <= opening < closing < closing_end <= end <= declared):
                return False
            if abs(start - window_start) > 1e-6 or abs(end - window_end) > 1e-6:
                return False
            for cue in [*cues.get("parts", []), *cues.get("groups", [])]:
                if not cue.get("verified"):
                    continue
                lo, hi = float(cue["start_seconds"]), float(cue["end_seconds"])
                if not (math.isfinite(lo) and math.isfinite(hi) and start <= lo < hi <= end):
                    return False
            return True
        except (KeyError, TypeError, ValueError, OverflowError):
            return False

    def _exam_blockers(self, exam: Exam) -> list:
        blockers: list = []
        if not exam.validated:
            blockers.append("题库结构/来源校验尚未通过（validated=false）")
        expected = sum(hi - lo + 1 for lo, hi in PART_RANGES.values())
        if exam.question_count != expected:
            blockers.append(f"题量 {exam.question_count} 与预期 {expected} 不一致")
        numbers = {q.get("number") for q in exam.questions}
        missing = [n for n in range(1, 201) if n not in numbers]
        if missing:
            blockers.append(f"缺少题号 {missing[:5]}{'…' if len(missing) > 5 else ''}")
        for q in exam.questions:
            if q.get("part") not in PART_RANGES:
                blockers.append(f"题目 {q.get('id')} 的 Part 无效")
                break
            legal = 3 if q["part"] == 2 else 4
            if len(q.get("options", [])) != legal:
                blockers.append(f"题目 {q.get('id')} 选项数不符合 Part {q['part']} 规则")
                break
            if not q.get("answer"):
                blockers.append(f"题目 {q.get('id')} 缺少答案")
                break
        if not exam.audio or not exam.audio.get("asset_id"):
            blockers.append("缺少音频资产登记")
        elif exam.audio["asset_id"] not in self.assets:
            blockers.append("音频资产未在 manifest 登记")
        elif exam.full_end_seconds <= exam.full_start_seconds:
            blockers.append("听力音频时间轴（audio-cues.json）尚未就绪")
        elif not exam.cues_verified:
            blockers.append("听力音频时间轴尚未核验（verified=false）")
        else:
            verified_parts = {int(p["part"]) for p in exam.part_cues}
            missing_parts = [p for p in LISTENING_PARTS if p not in verified_parts]
            if missing_parts:
                blockers.append(f"Part {missing_parts} 的音频时间轴尚未核验")
        for asset in self.assets.values():
            if not (self.root / asset["path"]).is_file():
                blockers.append(f"资产文件缺失：{asset['path']}")
                break
        return blockers

    def exam_ready_reason(self, exam: Exam) -> str | None:
        return exam.blockers[0] if exam.blockers else None

    def group_cue_for(self, exam: Exam, group: dict) -> GroupCue | None:
        """Match a merged group cue by question-number range, not group-id."""
        ids = set(group.get("question_ids", []))
        numbers = sorted(q["number"] for q in exam.questions if q.get("id") in ids)
        if not numbers:
            return None
        first, last = numbers[0], numbers[-1]
        for cue in exam.group_cues:
            if cue.part == group.get("part") and cue.first_question == first and cue.last_question == last:
                return cue
        return None

    def asset_path(self, asset_id: str) -> tuple:
        asset = self.assets.get(asset_id)
        if not asset:
            raise KeyError(asset_id)
        root = self.root.resolve()
        target = (root / asset["path"]).resolve()
        if root not in target.parents and target != root:
            raise KeyError(asset_id)
        if not target.is_file():
            raise FileNotFoundError(asset_id)
        return target, asset.get("media_type", "application/octet-stream")

    def library_version(self) -> str:
        """A version that follows the identity of the content, not its shape.

        Learner progress is keyed by this value, so a change in how the text
        is written down must not orphan it. The digest therefore covers the
        question identities, their answers, the group membership and the
        registered assets, and leaves the wording of a passage out.
        """
        manifest = {key: value for key, value in self.manifest.items()
                    if key not in ("schema_version", "pool")}
        content = json.dumps({"manifest": manifest,
            "assets": sorted((asset.get("id"), asset.get("sha256"))
                             for asset in self.assets.values()),
            "exams": {key: {"questions": [
                {"canonical_id": q.get("canonical_id"), "id": q.get("id"),
                 "answer": q.get("answer"), "part": q.get("part"),
                 "group_id": q.get("group_id"),
                 "options": [o.get("id") for o in q.get("options", [])]}
                for q in e.questions],
                "groups": [{"id": g.get("id"), "part": g.get("part"),
                    "question_ids": list(g.get("question_ids", [])),
                    "passage_type": g.get("passage_type"),
                    "audio": (g.get("audio") or {}).get("asset_id")}
                    for g in e.groups],
                "audio": e.audio} for key, e in self.exams.items()},
            "cues": self._load_cues()}, sort_keys=True, ensure_ascii=False)
        parts = [self.manifest_version, hashlib.sha256(content.encode()).hexdigest()[:16]]
        return ".".join(p for p in parts if p) or "unavailable"

    def current_keys(self) -> dict:
        return {q["canonical_id"]: q.get("answer")
                for exam in self.exams.values() for q in exam.questions}

    def validate_selected(self, questions, groups, audio_queue, *, frozen=False) -> None:
        """Re-read selected registrations/files before the clock starts."""
        from .errors import conflict
        fresh = Library(self.root)
        fresh.load()
        if not fresh.available:
            raise conflict("内置题库无法读取。", "content_not_ready")
        if fresh.pool_mode:
            from .pool_library import validate_pool_selected
            validate_pool_selected(fresh,questions,groups,audio_queue,frozen=frozen)
            return
        selected_sources = set()
        for q in questions:
            exam = fresh.exams.get(q["exam_id"])
            current = next((item for item in exam.questions if item["id"] == q["id"]), None) if exam else None
            if (not exam or not exam.validated or not current or not current.get("answer") or
                    len(current.get("options", [])) != (3 if q["part"] == 2 else 4)):
                raise conflict("所选题目文件或答案尚未就绪。", "content_not_ready")
            if current.get("source_id"):
                selected_sources.add(current["source_id"])
        for source_id in selected_sources:
            source = fresh.sources.get(source_id)
            path = (fresh.root / source["path"]).resolve() if source else None
            if path is None or not path.is_relative_to(fresh.root.resolve()) or not path.is_file():
                raise conflict("所选题目来源文件缺失。", "content_not_ready")
        asset_ids = {m["asset_id"] for g in groups for m in g.get("materials", [])
                     if m.get("asset_id")}
        asset_ids.update(a["asset_id"] for a in audio_queue)
        for asset_id in asset_ids:
            try:
                path, _ = fresh.asset_path(asset_id)
                with path.open("rb") as stream:
                    if not stream.read(1):
                        raise OSError("empty asset")
            except (OSError, KeyError):
                raise conflict(f"所选素材缺失或无法读取：{asset_id}", "content_not_ready")
        covered = set()
        for item in audio_queue:
            exam = fresh.exams.get(item["exam_id"])
            start, end = item["start_seconds"], item["end_seconds"]
            duration = float((exam.audio or {}).get("duration_seconds", 0)) if exam else 0
            if (not exam or not exam.cues_verified or
                    not all(math.isfinite(v) for v in (start, end, duration)) or
                    not 0 <= start < end <= duration or
                    item["asset_id"] != (exam.audio or {}).get("asset_id")):
                raise conflict("所选音频片段时间轴无效。", "content_not_ready")
            allowed = [(exam.full_start_seconds, exam.full_end_seconds)]
            allowed += [(float(c["start_seconds"]), float(c["end_seconds"])) for c in exam.part_cues]
            allowed += [(c.start_seconds, c.end_seconds) for c in exam.group_cues]
            if (start, end) not in allowed:
                raise conflict("所选音频片段不再属于已登记时间轴。", "content_not_ready")
            covered.update(item["question_ids"])
        needed = {q["id"] for q in questions if q["part"] in LISTENING_PARTS}
        if not needed <= covered:
            raise conflict("部分听力题缺少已登记音频片段。", "content_not_ready")

    def private_fields(self, exam_id: str) -> dict:
        """Private answer/explanation per question id for report building."""
        exam = self.exams.get(exam_id)
        if not exam:
            return {}
        return {
            q["id"]: {"answer": q.get("answer"), "explanation": q.get("explanation")}
            for q in exam.questions
        }
