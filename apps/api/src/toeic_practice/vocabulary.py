"""Causal vocabulary evidence: explicit word confirmation, retraction,
threshold cycles, mastery. Co-occurrence candidates never auto-confirm."""

import re
from collections import Counter

from .clock import now_iso
from .errors import bad_request, conflict, not_found
from .store import dumps, loads

STOPWORDS = set(
    "a an the and or but if of at by for with about into through during before after "
    "above below to from up down in out on off over under again further then once "
    "here there when where why how all any both each few more most other some such "
    "no nor not only own same so than too very can will just should now is are was "
    "were be been being have has had having do does did doing would could ought i "
    "you he she it we they them his her its our their this that these those am as".split()
)

WORD_RE = re.compile(r"[A-Za-z][a-z'-]{2,}")


def extract_candidates(text: str) -> list:
    words = [w.lower() for w in WORD_RE.findall(text or "")]
    counts = Counter(w for w in words if w not in STOPWORDS and len(w) > 2)
    return [{"term": w, "context": text[:160], "count": c} for w, c in counts.most_common(20)]


class VocabularyService:
    def __init__(self, store, clock, library=None, reference=None) -> None:
        self.store = store
        self.clock = clock
        self.library = library
        self.reference = reference

    def _reference_for(self, term: str) -> dict | None:
        """The reference entry for a word, when the reference is available."""
        if self.reference is None:
            return None
        from .vocab_reference import reference_entry
        return reference_entry(self.reference, term)

    def _reference_sense(self, term: str) -> str:
        """A short gloss for a word, taken from the open word list."""
        entry = self._reference_for(term)
        if entry is None:
            return ""
        definition = entry.get("definition_simplified") or entry.get("definition") or ""
        return definition.strip()

    def _threshold(self, conn) -> int:
        row = conn.execute("SELECT value FROM settings WHERE key='vocabulary_threshold'").fetchone()
        return int(row["value"]) if row else 3

    def candidates(self, attempt_record: dict, qid: str) -> dict:
        if attempt_record["status"] not in ("submitted", "expired"):
            raise conflict("练习结束后才能查看复盘词汇候选。", "attempt_open")
        question = next((q for q in attempt_record["questions"] if q["id"] == qid), None)
        if question is None:
            raise not_found("该题不在本次练习范围内。", "question_not_in_attempt")
        text = " ".join(
            [question.get("stem", "")]
            + [o.get("text", "") for o in question.get("options", [])]
        )
        for g in attempt_record["groups"]:
            if qid in g.get("question_ids", []):
                for m in g.get("materials", []):
                    if m.get("text"):
                        text += " " + m["text"]
        candidates = extract_candidates(text)
        # Show the meaning of a candidate right where the learner picks it,
        # so confirming a word does not need a second page.
        for candidate in candidates:
            candidate["reference"] = self._reference_for(candidate["term"])
        return {"candidates": candidates}

    def put_review(self, conn, record: dict, qid: str, body: dict) -> dict:
        if record["status"] not in ("submitted", "expired"):
            raise conflict("练习结束后才能填写错因。", "attempt_open")
        if record["integrity"] != "valid":
            raise conflict("中断的练习不计入有效统计。", "invalid_attempt")
        question = next((q for q in record["questions"] if q["id"] == qid), None)
        if question is None:
            raise not_found("该题不在本次练习范围内。", "question_not_in_attempt")
        selected = record["answers"].get(qid, {}).get("option_id")
        answer = question.get("_answer")
        if selected is None or selected == answer:
            raise conflict("仅错题可以填写错因与词汇证据。", "not_wrong")

        causes = [c for c in (body.get("causes") or []) if isinstance(c, str)]
        legal_causes = {"meaning", "listening", "grammar", "paraphrase", "time",
                        "careless", "material", "unknown"}
        if any(c not in legal_causes for c in causes):
            raise bad_request("错因取值无效。", "bad_cause")
        words = body.get("words") or []
        if words and self.library:
            keys = self.library.current_keys()
            if question["canonical_id"] not in keys or answer != keys[question["canonical_id"]]:
                raise conflict("该题答案已修订，旧判分不能新增当前词汇证据。", "question_key_changed")

        conn.execute(
            "INSERT INTO reviews(attempt_id, question_id, causes, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(attempt_id, question_id) DO UPDATE SET causes=excluded.causes, "
            "updated_at=excluded.updated_at",
            (record["id"], qid, dumps(causes), now_iso(self.clock)),
        )
        # Retraction: deactivate this review's previous evidence for the question.
        conn.execute(
            "UPDATE vocab_evidence SET active=0 WHERE attempt_id=? AND question_id=? AND active=1",
            (record["id"], qid),
        )
        for word in words:
            term = str(word.get("term", "")).strip().lower()
            if not term or not word.get("causal", False):
                continue
            modality = word.get("modality", "meaning")
            if modality not in ("meaning", "listening"):
                raise bad_request("词汇模态无效。", "bad_modality")
            sense = str(word.get("sense", ""))
            # A word the learner confirmed but did not gloss gets its meaning
            # from the open word list, so the evidence is readable later.
            if not sense.strip():
                sense = self._reference_sense(term)
            state = conn.execute(
                "SELECT cycle FROM vocab_state WHERE term=? AND sense=? AND modality=?",
                (term, sense, modality),
            ).fetchone()
            cycle = state["cycle"] if state else 0
            context = (question.get("stem", "") or "")[:160]
            conn.execute(
                "INSERT INTO vocab_evidence(term,sense,modality,canonical_id,exam_id,"
                "question_id,group_id,attempt_id,cycle,active,library_version,context,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?)",
                (term, sense, modality, question["canonical_id"],
                 record["question_exam"].get(qid, ""), qid, question["group_id"],
                 record["id"], cycle, record.get("library_version", ""),
                 context, now_iso(self.clock)),
            )
        return {"ok": True}

    def list_entries(self, current_library_version: str = "") -> dict:
        with self.store.transaction() as conn:
            threshold = self._threshold(conn)
            rows = conn.execute(
                "SELECT term, sense, modality, cycle, canonical_id, exam_id, question_id,"
                " group_id, attempt_id, context, created_at, library_version"
                " FROM vocab_evidence WHERE active=1"
            ).fetchall()
            current_keys = self.library.current_keys() if self.library else None
            attempts = conn.execute("SELECT id, questions, integrity, status FROM attempts").fetchall()
            snapshots = {r["id"]: {q["id"]: q for q in loads(r["questions"])} for r in attempts}
            eligible_attempts = {r["id"] for r in attempts
                if r["integrity"] == "valid" and r["status"] in ("submitted", "expired")}
            def still_valid(e):
                if e["attempt_id"] not in eligible_attempts:
                    return False
                q = snapshots.get(e["attempt_id"], {}).get(e["question_id"])
                return current_keys is None or (q is not None and
                    e["canonical_id"] in current_keys and
                    q.get("_answer") == current_keys[e["canonical_id"]])
            states = {
                (r["term"], r["sense"], r["modality"]): r
                for r in conn.execute("SELECT * FROM vocab_state").fetchall()
            }
            grouped: dict = {}
            for r in rows:
                key = (r["term"], r["sense"], r["modality"])
                grouped.setdefault(key, []).append(r)
            entries = []
            for (term, sense, modality), evs in sorted(grouped.items()):
                state = states.get((term, sense, modality))
                cycle = state["cycle"] if state else 0
                mastered = bool(state["mastered"]) if state else False
                manual_required = bool(state["manual_required"]) if state else False
                current = [e for e in evs if e["cycle"] == cycle and still_valid(e)]
                distinct_questions = {e["canonical_id"] for e in current}
                distinct_materials = {(e["exam_id"], e["group_id"]) for e in current}
                lifetime_questions = {e["canonical_id"] for e in evs}
                # must_learn: >=threshold distinct questions across >=2 groups.
                auto = (len(distinct_questions) >= threshold
                        and len(distinct_materials) >= 2)
                if mastered:
                    status = "mastered"
                elif auto or manual_required:
                    status = "must_learn"
                elif len(distinct_questions) >= threshold and len(distinct_materials) == 1:
                    # concentrated: errors repeat on one shared material; the
                    # learner may promote it manually via manual_required.
                    status = "concentrated"
                else:
                    status = "candidate"
                entries.append({
                    "id": f"{term}|{sense}|{modality}",
                    "term": term, "sense": sense, "modality": modality,
                    "status": status,
                    "question_count": len(distinct_questions),
                    "material_count": len(distinct_materials),
                    "lifetime_question_count": len(lifetime_questions),
                    "threshold": threshold,
                    "manual_required": manual_required,
                    "reference": self._reference_for(term),
                    "evidence": [
                        {"attempt_id": e["attempt_id"], "question_id": e["question_id"],
                         "exam_id": e["exam_id"],
                         "number": int(e["question_id"].split("-q")[-1]) if "-q" in e["question_id"] else 0,
                         "group_id": e["group_id"], "context": e["context"]}
                        for e in current
                    ],
                })
            return {"threshold": threshold, "entries": entries}

    def patch_entry(self, entry_id: str, body: dict) -> dict:
        parts = entry_id.split("|")
        if len(parts) != 3:
            raise not_found("词条不存在。", "entry_not_found")
        term, sense, modality = parts
        with self.store.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM vocab_state WHERE term=? AND sense=? AND modality=?",
                (term, sense, modality),
            ).fetchone()
            mastered = row["mastered"] if row else 0
            manual = row["manual_required"] if row else 0
            cycle = row["cycle"] if row else 0
            if "mastered" in body:
                new_mastered = int(bool(body["mastered"]))
                if new_mastered and not mastered:
                    mastered = 1
                elif not new_mastered and mastered:
                    mastered = 0
                    cycle += 1  # relearning starts a fresh evidence cycle
            if "manual_required" in body:
                manual = int(bool(body["manual_required"]))
            conn.execute(
                "INSERT INTO vocab_state(term,sense,modality,mastered,manual_required,cycle) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(term,sense,modality) DO UPDATE SET "
                "mastered=excluded.mastered, manual_required=excluded.manual_required, "
                "cycle=excluded.cycle",
                (term, sense, modality, mastered, manual, cycle),
            )
        return self.list_entries()
