"""Attempt domain service: creation snapshots, leases, answers, submit.

Route modules only parse HTTP; all rules live here and in timing/grading.
Every mutation loads the row, advances the clock, applies the change and
persists inside one BEGIN IMMEDIATE transaction.
"""

import uuid
from copy import deepcopy
from math import isfinite

from . import activity, timing
from .clock import now_iso
from .errors import bad_request, conflict, gone, not_found
from .grading import build_report, refresh_history_summary
from .library import LISTENING_PARTS, READING_PARTS, Library
from .listening_review import extract_listening_script, frozen_group_audio
from .subtitle_cues import enrich_script
from .store import Store, dumps, loads


class AttemptService:
    def __init__(self, store: Store, library: Library, clock, reference=None) -> None:
        self.store = store
        self.library = library
        self.clock = clock
        self.reference = reference

    def create(self, request: dict) -> dict:
        with self.store.exclusive():
            return self._create(request)

    def _create(self, request: dict) -> dict:
        if self.library.pool_mode:
            from .pool_attempts import create_pool_attempt
            return create_pool_attempt(self, request)
        scope = request.get("scope", "reading")
        mode = request.get("mode", "practice")
        # One canonical source order drives metadata, snapshots and strict audio.
        # Repeated selection of a source must not duplicate its questions/queue.
        exam_ids = sorted(set(request.get("exam_ids") or []))
        parts = sorted({int(p) for p in (request.get("parts") or [])})
        question_filter = request.get("question_filter", "all")
        group_ids = request.get("group_ids") or []
        timer_req = request.get("timer") or {"kind": "none"}

        if mode == "exam" and scope in ("full", "listening", "reading") and question_filter != "all":
            raise bad_request("完整及分区模拟必须包含全部题目；刷错题、收藏或未做题请使用专项模拟或练习模式。",
                              "exam_requires_all_questions")

        if not self.library.available:
            raise conflict("内置题库尚未就绪，无法创建练习。", "library_unavailable")
        if scope == "full" and len(exam_ids) != 1:
            raise bad_request("完整模拟必须且只能选择一套试卷。", "full_requires_single_exam")
        if not exam_ids:
            raise bad_request("请至少选择一套试卷。", "exam_required")
        exams = []
        for exam_id in exam_ids:
            exam = self.library.exams.get(exam_id)
            if exam is None:
                raise not_found(f"试卷 {exam_id} 不存在。", "exam_not_found")
            reason = self.library.exam_ready_reason(exam)
            if reason:
                raise conflict(f"{exam.title} 未就绪：{reason}", "content_not_ready")
            exams.append(exam)

        questions, groups, audio_queue, phase_durations, phases, first_phase = self._select(
            exams, scope, parts, question_filter, group_ids, timer_req, mode
        )
        if not questions:
            raise conflict("所选范围没有可作答的题目。", "empty_scope")

        timer_kind = timer_req.get("kind", "none")
        if timer_kind not in ("countdown", "countup", "none"):
            raise bad_request("计时类型无效。", "bad_timer")
        # Strict exam scopes carry a fixed authoritative schedule; a stale UI
        # timer preference must never turn a mock exam into an untimed one.
        if mode == "exam" and scope in ("full", "listening", "reading"):
            timer_kind = "countdown"
        duration = timer_req.get("duration_seconds")
        if timer_kind == "countdown" and not phase_durations:
            if not duration or float(duration) <= 0:
                raise bad_request("倒计时必须提供正数时长。", "duration_required")
            phase_durations = {first_phase: float(duration)}

        actual_parts = sorted({q["part"] for q in questions})

        attempt_id = "att-" + uuid.uuid4().hex[:12]
        title = self._title(exams, scope, parts, mode)
        record = {
            "id": attempt_id,
            "title": title,
            "scope": scope,
            "mode": mode,
            "original_mode": mode,
            "status": "ready",
            "phase": first_phase,
            "integrity": "valid",
            "created_at": now_iso(self.clock),
            "closed_at": None,
            "close_reason": None,
            "exam_ids": [e.id for e in exams],
            "parts": actual_parts,
            "question_count": len(questions),
            "current_index": 0,
            "timer": timing.make_timer(timer_kind, duration, phases, phase_durations),
            "questions": questions,
            "groups": groups,
            "audio_queue": audio_queue,
            "media_state": None,
            "owner_tab_id": None,
            "interruptions": [],
            "library_version": self.library.library_version(),
            "phase_question_ids": self._phase_question_ids(questions, first_phase, phases, scope),
        }
        return self._persist_new(record)

    def _persist_new(self, record):
        questions, groups = record['questions'], record['groups']
        question_exam = {q['id']: q['exam_id'] for q in questions}
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO attempts(id,title,scope,mode,original_mode,status,phase,integrity,"
                "created_at,exam_ids,parts,question_count,current_index,timer,questions,groups,"
                "question_exam,audio_queue,media_state,owner_tab_id,interruptions,library_version,activity) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record['id'], record['title'], record['scope'], record['mode'], record['mode'], 'ready', record['phase'], 'valid',
                    record["created_at"], dumps(record["exam_ids"]), dumps(record['parts']),
                    len(questions), 0, dumps(record["timer"]), dumps(questions), dumps(groups),
                    dumps(question_exam), dumps(record['audio_queue']), None, None, "[]",
                    record["library_version"], dumps(activity.new_state()),
                ),
            )
        return self.get(record['id'])

    def _title(self, exams, scope, parts, mode) -> str:
        names = "、".join(e.title for e in exams)
        scope_label = {
            "full": "完整模拟", "listening": "听力模拟", "reading": "阅读模拟",
            "part": f"Part {'/'.join(str(p) for p in parts)}", "custom": "自定义题组",
        }.get(scope, scope)
        mode_label = "模拟考" if mode == "exam" else "练习"
        return f"{names} {scope_label}（{mode_label}）"

    # ---------- selection ----------

    def _select(self, exams, scope, parts, question_filter, group_ids, timer_req, mode):
        """Resolve the question snapshot, audio queue and phase schedule.

        Custom/group filters always expand to whole groups. Returns
        (questions, groups, audio_queue, phase_durations, phases, first_phase).
        """
        selected_questions: list = []
        selected_groups: list = []
        audio_queue: list = []
        phase_durations: dict = {}
        questions_by_part = {p: [] for p in range(1, 8)}

        if scope == "custom":
            requested_group_ids = set(group_ids)
            available_group_ids = {g["id"] for exam in exams for g in exam.groups}
            for gid in group_ids:
                if gid not in available_group_ids:
                    raise not_found(f"题组 {gid} 不存在。", "group_not_found")

        for exam in exams:
            exam_questions = sorted(exam.questions, key=lambda q: q["number"])
            if scope == "full":
                wanted = exam_questions
            elif scope == "listening":
                wanted = [q for q in exam_questions if q["part"] in LISTENING_PARTS]
            elif scope == "reading":
                wanted = [q for q in exam_questions if q["part"] in READING_PARTS]
            elif scope == "part":
                wanted = [q for q in exam_questions if q["part"] in parts]
            elif scope == "custom":
                wanted_groups = [g for g in exam.groups if g["id"] in requested_group_ids]
                wanted_ids = {qid for g in wanted_groups for qid in g["question_ids"]}
                wanted = [q for q in exam_questions if q["id"] in wanted_ids]
            else:
                raise bad_request("练习范围无效。", "bad_scope")

            if question_filter != "all":
                wanted = self._apply_filter(wanted, exam, question_filter)

            if scope == "custom":
                # Whole-group integrity: expand selection back to every group
                # touched by the filter.
                wanted_group_ids = {q["group_id"] for q in wanted}
                expanded = [q for q in exam_questions if q["group_id"] in wanted_group_ids]
                wanted = expanded
            else:
                wanted_group_ids = {q["group_id"] for q in wanted}
                if scope == "part" or question_filter != "all":
                    expanded = [q for q in exam_questions if q["group_id"] in wanted_group_ids]
                    wanted = expanded
                    wanted_group_ids = {q["group_id"] for q in wanted}

            for group in exam.groups:
                if group["id"] in wanted_group_ids:
                    selected_groups.append(self._public_group(exam, group))
            for q in wanted:
                selected_questions.append(self._public_question(exam, q))
                questions_by_part[q["part"]].append(q)

        selected_questions.sort(key=lambda q: (q["exam_id"], q["number"]))
        selected_groups.sort(key=lambda g: (g["exam_id"], g["question_ids"][0]))

        first_phase = "practice"
        phases = ["practice"]
        listening_questions = [q for q in selected_questions if q["part"] in LISTENING_PARTS]

        if scope == "full" and mode == "exam":
            exam = exams[0]
            phases = ["listening", "reading"]
            first_phase = "listening"
            phase_durations = {
                "listening": exam.listening_seconds,
                "reading": timing.READING_EXAM_SECONDS,
            }
            audio_queue.append(self._audio_item(exam, exam.full_start_seconds,
                                                exam.full_end_seconds, 0,
                                                [q["id"] for q in listening_questions]))
        elif scope == "listening" and mode == "exam":
            first_phase = "listening"
            phases = ["listening"]
            phase_durations = {"listening": sum(exam.listening_seconds for exam in exams)}
            for exam in exams:
                audio_queue.append(self._audio_item(exam, exam.full_start_seconds,
                    exam.full_end_seconds, 0,
                    [q["id"] for q in listening_questions if q["exam_id"] == exam.id]))
        elif scope == "reading" and mode == "exam":
            first_phase = "reading"
            phases = ["reading"]
            phase_durations = {"reading": timing.READING_EXAM_SECONDS}
        elif mode == "exam" and scope == "part" and question_filter == "all":
            duration = (timer_req.get("duration_seconds") or 0)
            if any(p in LISTENING_PARTS for p in parts):
                for exam in exams:
                    for cue in exam.part_cues:
                        if int(cue["part"]) in parts:
                            qids = [q["id"] for q in exam.questions
                                    if q["part"] == int(cue["part"]) and q["id"] in
                                    {sq["id"] for sq in selected_questions}]
                            audio_queue.append(self._audio_item(
                                exam, float(cue["start_seconds"]), float(cue["end_seconds"]),
                                int(cue["part"]), qids))
                if not audio_queue and any(p in LISTENING_PARTS for p in parts):
                    raise conflict("所选听力 Part 的音频时间轴尚未就绪。", "cues_not_ready")
            first_phase = "listening" if audio_queue else "practice"
            phases = ["listening"] if audio_queue else ["practice"]
            if timer_req.get("kind") == "countdown" and duration:
                phase_durations = {first_phase: float(duration)}
        else:
            # Filtered Part/custom exams require exact selected group clips.
            # Practice retains its existing optional group/Part audio policy.
            for exam in exams:
                if not any(p in LISTENING_PARTS for p in
                           {q["part"] for q in exam.questions
                            if q["id"] in {sq["id"] for sq in selected_questions}}):
                    continue
                added = False
                for group in exam.groups:
                    if group["id"] not in {g["id"] for g in selected_groups}:
                        continue
                    cue = self.library.group_cue_for(exam, group)
                    if (scope in ("part", "custom") and mode == "exam" and
                            group["part"] in LISTENING_PARTS and cue is None):
                        raise conflict("所选听力题组缺少核验片段，不能以整 Part 音频替代。", "cues_not_ready")
                    if cue is not None:
                        audio_queue.append(self._audio_item(
                            exam, cue.start_seconds, cue.end_seconds, group["part"],
                            list(group["question_ids"]), group_id=group["id"]))
                        added = True
                if not added:
                    listening_parts_here = {q["part"] for q in exam.questions
                                            if q["id"] in {sq["id"] for sq in selected_questions}}
                    for cue in exam.part_cues:
                        if int(cue["part"]) in listening_parts_here:
                            qids = [q["id"] for q in exam.questions
                                    if q["part"] == int(cue["part"]) and q["id"] in
                                    {sq["id"] for sq in selected_questions}]
                            audio_queue.append(self._audio_item(
                                exam, float(cue["start_seconds"]), float(cue["end_seconds"]),
                                int(cue["part"]), qids))
            audio_queue.sort(key=lambda a: (a["exam_id"], a["part"], a["start_seconds"]))

        if scope == "custom" and mode == "exam":
            if listening_questions:
                first_phase, phases = "listening", ["listening"]
                if timer_req.get("kind") == "countdown":
                    duration = float(timer_req.get("duration_seconds") or 0)
                    if not isfinite(duration) or duration <= 0:
                        raise bad_request("倒计时必须提供正数时长。", "duration_required")
                    phase_durations = {"listening": duration}
            else:
                first_phase, phases = "reading", ["reading"]

        if (mode == "exam" and scope in ("part", "custom") and listening_questions
                and any(q["part"] in READING_PARTS for q in selected_questions)):
            # Personal mixed scopes share one phase/budget. Full mocks alone
            # retain their separate Listening -> Reading exam schedule.
            first_phase, phases = "practice", ["practice"]
            if phase_durations:
                phase_durations = {"practice": sum(phase_durations.values())}

        return selected_questions, selected_groups, audio_queue, phase_durations, phases, first_phase

    def _apply_filter(self, questions, exam, question_filter) -> list:
        if question_filter not in ("all", "unanswered", "wrong", "bookmarked"):
            raise bad_request("题目筛选无效。", "bad_filter")
        latest = self._latest_results(exam.id)
        kept = []
        for q in questions:
            state = latest.get(q["canonical_id"], {})
            if question_filter == "unanswered" and state.get("result") is None:
                kept.append(q)
            elif question_filter == "wrong" and state.get("result") == "wrong":
                kept.append(q)
            elif question_filter == "bookmarked" and state.get("bookmarked", False):
                kept.append(q)
        return kept

    def _latest_results(self, exam_id: str) -> dict:
        """Independent last actual answer and mark from valid closed attempts."""
        # Per-question key identity survives unrelated content/version changes.
        # Legacy whole-library rows are reconstructed from immutable snapshots.
        rows = self.store.query(
            "SELECT id, questions FROM attempts WHERE integrity='valid' "
            "AND status IN ('submitted','expired') ORDER BY closed_at ASC, rowid ASC")
        current = {q["canonical_id"]: q.get("answer") for q in self.library.exams[exam_id].questions}
        results: dict = {}
        for row in rows:
            answers = {a["question_id"]: a for a in self.store.query(
                "SELECT question_id, option_id, flagged FROM answers WHERE attempt_id=?", (row["id"],))}
            for q in loads(row["questions"]):
                canonical = q["canonical_id"]
                if canonical not in current or q.get("_answer") != current[canonical]:
                    continue
                a = answers.get(q["id"])
                if a is None:
                    continue  # an untouched question changes neither dimension
                state = results.setdefault(canonical, {"result": None, "bookmarked": False})
                state["bookmarked"] = bool(a["flagged"])
                if a["option_id"] is not None:
                    state["result"] = "correct" if a["option_id"] == q.get("_answer") else "wrong"
        return results

    def _public_question(self, exam, q) -> dict:
        part = q["part"]
        options = [{"id": o["id"], "text": o["text"]} for o in q.get("options", [])]
        stem = q.get("stem", "")
        return {
            "id": q["id"],
            "canonical_id": q["canonical_id"],
            "number": q["number"],
            "part": part,
            "section": q["section"],
            "group_id": q["group_id"],
            "exam_id": exam.id,
            "stem": stem,
            "options": options,
            "source_pages": q.get("source_pages", []),
            "_answer": q.get("answer"),
            "_explanation": q.get("explanation"),
            "_source_erratum": q.get("source_erratum"),
            "_source_review_question_number": q.get("source_review_question_number"),
        }

    def _public_group(self, exam, group) -> dict:
        materials = []
        for m in group.get("materials", []):
            material = {"kind": m.get("kind", "text")}
            if m.get("text"):
                material["text"] = m["text"]
            if m.get("asset_id"):
                material["asset_id"] = m["asset_id"]
                material["url"] = f"/api/assets/{m['asset_id']}"
            if m.get("alt"):
                material["alt"] = m["alt"]
            materials.append(material)
        snapshot = {
            "id": group["id"],
            "part": group["part"],
            "section": group["section"],
            "exam_id": exam.id,
            "question_ids": list(group.get("question_ids", [])),
            "materials": materials,
            "source_pages": group.get("source_pages", []),
            "_review_text": group.get("review_text"),
        }
        if group["part"] in LISTENING_PARTS:
            if self.library.pool_mode:
                from .pool_attempts import pool_audio_item
                snapshot['_review_source_pages'] = []
                snapshot['_listening_script'] = deepcopy(group['listening_script'])
                snapshot['_review_audio'] = pool_audio_item(group)
                asset = self.library.assets[group['audio']['asset_id']]
                snapshot['_audio_asset'] = {k:asset.get(k) for k in ('id','sha256','duration_seconds')}
                snapshot['_subtitle_frozen'] = True
                snapshot['_subtitle_quality_version'] = 2
                return snapshot
            snapshot["_review_source_pages"] = group.get("review_source_pages", [])
            snapshot["_listening_script"] = extract_listening_script(group, exam.questions)
            snapshot["_review_audio"] = None
            cue = self.library.group_cue_for(exam, group)
            duration = float((exam.audio or {}).get("duration_seconds") or 0)
            if (cue and cue.verified and exam.cues_verified and exam.validated
                    and all(isfinite(v) for v in (cue.start_seconds, cue.end_seconds, duration,
                                                  exam.full_start_seconds, exam.full_end_seconds))
                    and 0 <= exam.full_start_seconds <= cue.start_seconds < cue.end_seconds
                    <= exam.full_end_seconds <= duration):
                snapshot["_review_audio"] = self._audio_item(
                    exam, cue.start_seconds, cue.end_seconds, group["part"],
                    list(group["question_ids"]), group_id=group["id"])
            snapshot["_listening_script"] = enrich_script(
                self.library, snapshot, snapshot["_listening_script"], snapshot["_review_audio"])
            snapshot["_subtitle_frozen"] = True
            snapshot["_subtitle_quality_version"] = 2
        return snapshot

    def _audio_item(self, exam, start, end, part, question_ids, group_id=None) -> dict:
        item = {
            "id": f"{exam.id}-p{part}-{int(round(start * 1000))}",
            "asset_id": exam.audio["asset_id"],
            "url": f"/api/assets/{exam.audio['asset_id']}",
            "start_seconds": start,
            "end_seconds": end,
            "part": part,
            "exam_id": exam.id,
            "question_ids": question_ids,
        }
        if group_id:
            item["group_id"] = group_id
        return item

    def _phase_question_ids(self, questions, first_phase, phases, scope) -> dict:
        mapping: dict = {}
        for phase in phases:
            if phase == "listening":
                mapping[phase] = [q["id"] for q in questions if q["part"] in LISTENING_PARTS]
            elif phase == "reading":
                mapping[phase] = [q["id"] for q in questions if q["part"] in READING_PARTS]
            else:
                mapping[phase] = [q["id"] for q in questions]
        return mapping

    # ---------- persistence helpers ----------

    def _load_record(self, conn, attempt_id: str) -> dict:
        row = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if row is None:
            raise not_found("练习记录不存在。", "attempt_not_found")
        record = {
            "id": row["id"], "title": row["title"], "scope": row["scope"],
            "mode": row["mode"], "original_mode": row["original_mode"],
            "status": row["status"], "phase": row["phase"], "integrity": row["integrity"],
            "created_at": row["created_at"], "closed_at": row["closed_at"],
            "close_reason": row["close_reason"],
            "exam_ids": loads(row["exam_ids"]), "parts": loads(row["parts"]),
            "question_count": row["question_count"], "current_index": row["current_index"],
            "timer": loads(row["timer"]), "questions": loads(row["questions"]),
            "groups": loads(row["groups"]), "question_exam": loads(row["question_exam"]),
            "audio_queue": loads(row["audio_queue"]),
            "media_state": loads(row["media_state"]) if row["media_state"] else None,
            "owner_tab_id": row["owner_tab_id"],
            "interruptions": loads(row["interruptions"]),
            "library_version": row["library_version"],
            "report": loads(row["report"]) if row["report"] else None,
            "activity": loads(row["activity"]) if row["activity"] else None,
        }
        rows = conn.execute(
            "SELECT question_id, option_id, flagged, visited, revision FROM answers WHERE attempt_id=?",
            (attempt_id,),
        ).fetchall()
        record["answers"] = {
            r["question_id"]: {
                "option_id": r["option_id"], "flagged": bool(r["flagged"]),
                "visited": bool(r["visited"]), "revision": r["revision"],
            }
            for r in rows
        }
        record["phase_question_ids"] = self._phase_question_ids(
            record["questions"], record["phase"], record["timer"].get("phases", []), record["scope"])
        return record

    def _save_record(self, conn, record: dict) -> None:
        timing.checkpoint(record, self.clock)
        conn.execute(
            "UPDATE attempts SET mode=?, original_mode=?, status=?, phase=?, integrity=?, current_index=?, timer=?, "
            "media_state=?, owner_tab_id=?, interruptions=?, closed_at=?, close_reason=?, report=?, activity=? "
            "WHERE id=?",
            (
                record["mode"], record["original_mode"],
                record["status"], record["phase"], record["integrity"], record["current_index"],
                dumps(record["timer"]),
                dumps(record["media_state"]) if record["media_state"] else None,
                record["owner_tab_id"], dumps(record["interruptions"]),
                record.get("closed_at"), record.get("close_reason"),
                dumps(record["report"]) if record.get("report") else None,
                dumps(record["activity"]) if record.get("activity") is not None else None,
                record["id"],
            ),
        )

    def _close_if_expired(self, conn, record: dict) -> None:
        timing.recover(record, self.clock)
        activity.checkpoint(record, self.clock)
        old_phase = record["phase"]
        transition = timing.advance(record, self.clock)
        if old_phase != record["phase"] or record["status"] != "running":
            activity.stop(record)
        if transition == "expired":
            record["closed_at"] = now_iso(self.clock)
            record["close_reason"] = "expired"
            record["report"] = build_report(record)
            refresh_history_summary(conn, record)
        self._save_record(conn, record)
        self.store.preserve_clock_transition(conn)

    def _require_owner(self, record: dict, tab_id: str | None) -> None:
        if record["owner_tab_id"] is None:
            raise conflict("请先认领该练习（claim）再作答。", "claim_required")
        if tab_id is None or record["owner_tab_id"] != tab_id:
            raise conflict("该练习由其他窗口持有；如需接管请使用 takeover。", "tab_conflict")

    def _remember_owners(self, conn, attempt_id: str, *tab_ids: str | None) -> None:
        """Record only server-verified owners in the existing SQLite registry.

        Called inside a successful claim/start transaction. Including the old
        persisted owner on transfer also captures ownership of legacy rows.
        This history authorizes reliability downgrades only, never live writes.
        """
        key = f"attempt_owners:{attempt_id}"
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        previous = set(loads(row["value"])) if row else set()
        owners = previous | {tab_id for tab_id in tab_ids if tab_id}
        if owners != previous:
            conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, dumps(sorted(owners))))

    def _require_interrupt_owner(self, conn, record: dict, tab_id: str | None) -> None:
        if tab_id is not None and tab_id == record["owner_tab_id"]:
            return
        row = conn.execute("SELECT value FROM meta WHERE key=?",
                           (f"attempt_owners:{record['id']}",)).fetchone()
        if tab_id and row and tab_id in loads(row["value"]):
            return
        self._require_owner(record, tab_id)

    # ---------- read paths ----------

    def get(self, attempt_id: str) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._close_if_expired(conn, record)
            return self._dto(record)

    def list(self) -> list:
        with self.store.transaction() as conn:
            rows = conn.execute("SELECT * FROM attempts ORDER BY created_at DESC").fetchall()
            summaries = []
            for row in rows:
                record = self._load_record(conn, row["id"])
                self._close_if_expired(conn, record)
                answered = sum(1 for a in record["answers"].values() if a["option_id"])
                item = {
                    "id": record["id"], "title": record["title"], "scope": record["scope"],
                    "mode": record["mode"], "status": record["status"],
                    "integrity": record["integrity"], "original_mode": record["original_mode"],
                    "created_at": record["created_at"],
                    "question_count": record["question_count"],
                    "answered_count": answered,
                    "parts": record["parts"], "exam_ids": record["exam_ids"],
                }
                if record.get("report"):
                    item["summary"] = record["report"]["summary"]
                summaries.append(item)
            return summaries

    def clock_state(self, attempt_id: str) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._close_if_expired(conn, record)
            timing_dto = timing.compute_timing(record, self.clock)
            return {
                "timing": timing_dto,
                "audio_elapsed_ms": self._audio_elapsed_ms(record, timing_dto),
                "status": record["status"],
                "owner_tab_id": record["owner_tab_id"],
            }

    def report(self, attempt_id: str) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            if record["status"] not in ("submitted", "expired"):
                self._close_if_expired(conn, record)
            if record["status"] not in ("submitted", "expired"):
                raise conflict("练习尚未结束，报告不可用。", "report_not_ready")
            return self._enrich_report(record)

    def put_review(self, attempt_id: str, qid: str, body: dict) -> dict:
        from .vocabulary import VocabularyService
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._close_if_expired(conn, record)
            VocabularyService(self.store, self.clock, self.library,
                              self.reference).put_review(conn, record, qid, body)
            return self._enrich_report(record)

    def candidates(self, attempt_id: str, qid: str) -> dict:
        from .vocabulary import VocabularyService
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._close_if_expired(conn, record)
            return VocabularyService(self.store, self.clock, self.library,
                                     self.reference).candidates(record, qid)

    # ---------- mutations ----------

    def claim(self, attempt_id: str, tab_id: str, takeover: bool) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._close_if_expired(conn, record)
            owner = record["owner_tab_id"]
            if owner is not None and owner != tab_id and not takeover:
                raise conflict("该练习正由另一个窗口使用。", "tab_held")
            self._remember_owners(conn, record["id"], owner, tab_id)
            record["owner_tab_id"] = tab_id
            activity.claim(record)
            self._save_record(conn, record)
            return self._dto(record)

    def start(self, attempt_id: str, tab_id: str | None, media_ready: bool) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            if record["audio_queue"] and not media_ready:
                raise conflict("音频尚未成功播放，不能开始计时。", "media_not_ready")
            if record["status"] == "ready":
                if self.library.pool_mode and record['timer'].get('retake_snapshot'):
                    self.library.validate_selected(record['questions'],record['groups'],record['audio_queue'],frozen=True)
                else:
                    self.library.validate_selected(record["questions"], record["groups"], record["audio_queue"])
                if record["owner_tab_id"] is None and tab_id:
                    record["owner_tab_id"] = tab_id
                self._require_owner(record, tab_id)
                self._remember_owners(conn, record["id"], record["owner_tab_id"])
                timing.start(record, self.clock)
                self._save_record(conn, record)
            else:
                if record["owner_tab_id"] is not None:
                    self._require_owner(record, tab_id)
                self._close_if_expired(conn, record)
            return self._dto(record)

    def pause(self, attempt_id: str, tab_id: str | None) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._require_owner(record, tab_id)
            self._close_if_expired(conn, record)
            if record["mode"] != "practice":
                raise conflict("模拟考不能暂停。", "pause_not_allowed")
            if record["status"] == "running":
                timing.pause(record, self.clock)
                activity.stop(record)
                self._save_record(conn, record)
            return self._dto(record)

    def resume(self, attempt_id: str, tab_id: str | None) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._require_owner(record, tab_id)
            self._close_if_expired(conn, record)
            if record["status"] == "paused":
                timing.resume(record, self.clock)
                self._save_record(conn, record)
            return self._dto(record)

    def interrupt(self, attempt_id: str, tab_id: str | None, reason: str, *,
                  event_id: str | None = None, occurred_at_ms: int | None = None) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._require_interrupt_owner(conn, record, tab_id)
            if record["status"] not in ("submitted", "expired"):
                self._close_if_expired(conn, record)
            if timing.mark_interrupted(record, self.clock, reason or "interrupted",
                                       event_id=event_id, occurred_at_ms=occurred_at_ms):
                # Keep the closed grade snapshot, answer revisions, clock and
                # closure fields byte-for-byte intact. Reliability is separate.
                conn.execute("UPDATE attempts SET integrity=?, interruptions=? WHERE id=?",
                    (record["integrity"], dumps(record["interruptions"]), record["id"]))
            return self._dto(record)

    def continue_practice(self, attempt_id: str, tab_id: str | None) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._require_owner(record, tab_id)
            self._close_if_expired(conn, record)
            if record["integrity"] != "interrupted":
                raise conflict("仅中断的模拟考可以转为练习。", "not_interrupted")
            if record["status"] in ("submitted", "expired"):
                raise gone("该记录已结束。", "attempt_closed")
            record["mode"] = "practice"
            if record["status"] == "running":
                timing.pause(record, self.clock)
                activity.stop(record)
            self._save_record(conn, record)
            return self._dto(record)

    def set_media_state(self, attempt_id: str, tab_id: str | None, state: dict) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._require_owner(record, tab_id)
            self._close_if_expired(conn, record)
            if record["status"] not in ("running", "paused"):
                raise gone("该记录已结束。", "attempt_closed")
            queue = record["audio_queue"]
            index = int(state.get("queue_index", 0))
            if not 0 <= index < len(queue):
                raise bad_request("音频队列序号无效。", "bad_queue_index")
            item = queue[index]
            position = float(state.get("position_seconds", 0.0))
            if not 0 <= position <= max(0.0, item["end_seconds"] - item["start_seconds"]) + 1.0:
                raise bad_request("音频进度超出所选片段范围。", "bad_position")
            rate = float(state.get("playback_rate", 1.0))
            if not 0.25 <= rate <= 3.0:
                raise bad_request("播放倍速无效。", "bad_rate")
            record["media_state"] = {
                "queue_index": index, "position_seconds": position, "playback_rate": rate,
            }
            self._save_record(conn, record)
            return self._dto(record)

    def set_position(self, attempt_id: str, tab_id: str | None, current_index: int) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._require_owner(record, tab_id)
            self._close_if_expired(conn, record)
            if not 0 <= current_index < record["question_count"]:
                raise bad_request("题号位置无效。", "bad_position")
            record["current_index"] = current_index
            self._save_record(conn, record)
            return self._dto(record)

    def set_activity(self, attempt_id: str, tab_id: str | None, body: dict) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._require_owner(record, tab_id)
            self._close_if_expired(conn, record)
            if record["status"] in ("submitted", "expired"):
                raise gone("本轮已结束，用时记录已冻结。", "attempt_closed")
            state = record.get("activity")
            if state is None or body["session_id"] != state.get("session_id"):
                raise conflict("用时会话已更新，请重新认领本轮。", "activity_session_conflict")
            qid = body.get("question_id")
            question = next((q for q in record["questions"] if q["id"] == qid), None)
            if qid is not None:
                if question is None:
                    raise not_found("该题不在本轮范围内。", "question_not_in_attempt")
                if (record["mode"] == "exam" and record["phase"] in ("reading", "listening")
                        and question["section"] != record["phase"]):
                    raise conflict("当前阶段不开放该题。", "section_locked")
            activity.target(record, self.clock, qid, body["sequence"])
            self._save_record(conn, record)
            return {"activity": activity.summary(record, self.clock)}

    def put_answer(self, attempt_id: str, qid: str, tab_id: str | None, body: dict) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            self._require_owner(record, tab_id)
            self._close_if_expired(conn, record)
            if record["status"] in ("submitted", "expired"):
                raise gone("练习已结束，答案不可再修改。", "attempt_closed")
            if record["status"] == "ready":
                raise conflict("练习尚未开始，不能作答。", "not_started")
            if record["status"] == "paused":
                raise conflict("练习已暂停，恢复后才能作答。", "is_paused")
            question = next((q for q in record["questions"] if q["id"] == qid), None)
            if question is None:
                raise not_found("该题不在本次练习范围内。", "question_not_in_attempt")
            if record["mode"] == "exam" and record["phase"] == "reading" and question["part"] in LISTENING_PARTS:
                raise conflict("听力阶段已结束，听力答案已锁定。", "section_locked")
            if record["mode"] == "exam" and record["phase"] == "listening" and question["part"] in READING_PARTS:
                raise conflict("阅读阶段尚未开始。", "section_locked")
            legal = {o["id"] for o in question["options"]}
            option_id = body.get("option_id")
            if option_id is not None and option_id not in legal:
                raise bad_request("选项无效。", "bad_option")
            existing = record["answers"].get(
                qid, {"option_id": None, "flagged": False, "visited": False, "revision": 0}
            )
            expected = int(body.get("revision", 0))
            mutation_id = body.get("mutation_id")
            if not mutation_id:
                raise bad_request("缺少 mutation_id。", "mutation_id_required")
            request_identity = dumps({key: body[key] for key in sorted(body) if key != "mutation_id"})
            prior = conn.execute(
                "SELECT attempt_id, question_id, request_json FROM mutations WHERE mutation_id=?", (mutation_id,)
            ).fetchone()
            if prior is not None:
                if (prior["attempt_id"] != attempt_id or prior["question_id"] != qid
                        or prior["request_json"] != request_identity):
                    raise conflict("mutation_id 已被其他请求使用。", "mutation_conflict")
                return self._dto(record)
            if existing["revision"] != expected:
                raise conflict("答案版本冲突：请刷新后重试或明确选择保留哪一份。",
                               "revision_conflict")
            conn.execute(
                "INSERT INTO answers(attempt_id, question_id, option_id, flagged, visited, revision) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(attempt_id, question_id) DO UPDATE SET "
                "option_id=excluded.option_id, flagged=excluded.flagged, "
                "visited=excluded.visited, revision=excluded.revision",
                (
                    attempt_id, qid, option_id,
                    int(body.get("flagged", existing["flagged"])),
                    int(body.get("visited", True)),
                    existing["revision"] + 1,
                ),
            )
            conn.execute(
                "INSERT INTO mutations(mutation_id, attempt_id, question_id, applied_at, request_json) "
                "VALUES(?,?,?,?,?)",
                (mutation_id, attempt_id, qid, now_iso(self.clock), request_identity),
            )
            activity.first_answer(record, qid, existing["option_id"], option_id)
            self._save_record(conn, record)
            record = self._load_record(conn, attempt_id)
            return self._dto(record)

    def submit(self, attempt_id: str, tab_id: str | None) -> dict:
        with self.store.transaction() as conn:
            record = self._load_record(conn, attempt_id)
            if record["status"] in ("submitted", "expired"):
                if record["report"] is None:
                    record["report"] = build_report(record)
                    refresh_history_summary(conn, record)
                    self._save_record(conn, record)
                return self._enrich_report(record)
            if record["owner_tab_id"] is not None:
                self._require_owner(record, tab_id)
            self._close_if_expired(conn, record)
            if record["status"] in ("submitted", "expired"):
                return self._enrich_report(record)
            timing._accumulate(record, self.clock)
            activity.stop(record)
            record["status"] = "submitted"
            record["phase"] = "finished"
            record["closed_at"] = now_iso(self.clock)
            record["close_reason"] = "manual"
            record["report"] = build_report(record)
            refresh_history_summary(conn, record)
            self._save_record(conn, record)
            return self._enrich_report(record)

    # ---------- DTO ----------

    def _audio_elapsed_ms(self, record: dict, timing_dto: dict) -> int:
        if record["mode"] != "exam":
            return 0
        if record["phase"] == "listening" or (
                record["phase"] == "practice" and record["scope"] in ("part", "custom")
                and record["audio_queue"]):
            return timing_dto["elapsed_ms"]
        if "listening" in record["timer"].get("phases", []):
            return round(record["timer"]["phase_durations"].get("listening", 0.0) * 1000)
        return 0

    def _dto(self, record: dict) -> dict:
        timing_dto = timing.compute_timing(record, self.clock)
        audio_elapsed = self._audio_elapsed_ms(record, timing_dto)
        public_questions = []
        for q in record["questions"]:
            public = {k: v for k, v in q.items() if not k.startswith("_")}
            if q["part"] in (1, 2):
                public["stem"] = ""
                public["options"] = [{"id": o["id"], "text": ""} for o in q["options"]]
            public_questions.append(public)
        public_groups = []
        for g in record["groups"]:
            public = {k: v for k, v in g.items() if not k.startswith("_")}
            if record["mode"] == "practice" and record["status"] != "ready":
                script, _ = self._listening_presentation(record, g)
                if script:
                    public["listening_script"] = script
            public_groups.append(public)
        return {
            "id": record["id"],
            "title": record["title"],
            "scope": record["scope"],
            "mode": record["mode"],
            "original_mode": record["original_mode"],
            "status": record["status"],
            "created_at": record["created_at"],
            "exam_ids": record["exam_ids"],
            "parts": record["parts"],
            "question_count": record["question_count"],
            "current_index": record["current_index"],
            "questions": public_questions,
            "groups": public_groups,
            "answers": record["answers"],
            "timing": timing_dto,
            "timer_config": {
                "kind": record["timer"].get("kind", "none"),
                "duration_seconds": record["timer"].get("duration_seconds"),
            },
            "audio_queue": record["audio_queue"],
            "audio_elapsed_ms": audio_elapsed,
            "media_state": record["media_state"],
            "owner_tab_id": record["owner_tab_id"],
            "interruptions": record["interruptions"],
            "integrity": record["integrity"],
            "activity_session_id": record["activity"].get("session_id") if record.get("activity") else None,
            "activity": activity.summary(record, self.clock),
        }

    def _enrich_report(self, record: dict) -> dict:
        """Add reviews and group review_text from the attempt's own snapshot."""
        report = deepcopy(record["report"])
        # Old closed reports predate activity. Expose an honest unavailable DTO,
        # without rewriting their stored grade snapshots.
        if "activity" not in report:
            report["activity"] = activity.summary({**record, "activity": None})
        # Scores/questions remain the frozen grade snapshot. Reliability may
        # subsequently be downgraded by a delayed offline media event.
        report["attempt"] = {**report["attempt"], "integrity": record["integrity"],
                             "interruptions": record["interruptions"]}
        review_rows = self.store.query(
            "SELECT question_id, causes FROM reviews WHERE attempt_id=?", (record["id"],)
        )
        reviews = {r["question_id"]: {"causes": loads(r["causes"])} for r in review_rows}
        word_rows = self.store.query(
            "SELECT DISTINCT question_id, term, sense, modality FROM vocab_evidence "
            "WHERE attempt_id=? AND active=1",
            (record["id"],),
        )
        words_by_q: dict = {}
        for row in word_rows:
            words_by_q.setdefault(row["question_id"], []).append(
                {"term": row["term"], "sense": row["sense"], "modality": row["modality"]}
            )
        for q in report["questions"]:
            entry = dict(reviews.get(q["id"], {}))
            if q["id"] in words_by_q:
                entry["words"] = words_by_q[q["id"]]
            if entry:
                q["review"] = entry
        snapshot_groups = {g["id"]: g for g in record["groups"]}
        enriched_groups = []
        for g in report["groups"]:
            enriched = dict(g)
            source = snapshot_groups.get(g["id"])
            if source and source.get("_review_text"):
                enriched["review_text"] = source["_review_text"]
            if source and source.get("part") in LISTENING_PARTS:
                script, audio = self._listening_presentation(record, source)
                if script:
                    enriched["listening_script"] = deepcopy(script)
                if audio:
                    enriched["review_audio"] = deepcopy(audio)
            enriched_groups.append(enriched)
        report["groups"] = enriched_groups
        report["reviews"] = reviews
        return report

    def _listening_presentation(self, record, source):
        if source.get("part") not in LISTENING_PARTS:
            return None, None
        script = (source["_listening_script"] if "_listening_script" in source else
                  extract_listening_script(source, record["questions"]))
        audio = (source["_review_audio"] if "_review_audio" in source else
                 frozen_group_audio(source, record["audio_queue"]))
        return enrich_script(self.library, source, script, audio,
                             frozen=source.get("_subtitle_frozen") is True,
                             quality_verified=source.get("_subtitle_quality_version") == 2), audio
