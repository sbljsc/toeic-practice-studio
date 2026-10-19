"""Listening review: source layout, private creation snapshots and legacy bounds."""
import copy
import json
import re
from pathlib import Path

import pytest

from toeic_practice.errors import ApiError
from toeic_practice.library import Library


SHORT = {
    1: "（\nA\n）They're rowing.\n（B）They're lifting.\n（C）They're sitting.\n（D）They're swimming.\n"
       "（A）他们在划船。\n（B）他们在抬东西。\n（C）他们坐着。\n（D）他们在游泳。\n·They're riding.\n他们乘船。",
    2: "When will you leave?\n（A）On Monday.\n（B）With Jane.\n（C）By train.\n"
       "你什么时候出发？\n（A）星期一。\n（B）和简一起。\n（C）坐火车。\nQ When are you leaving?\nA Tomorrow.\n明天。",
}
EXPECTED = {
    1: ("(A) They're rowing.\n(B) They're lifting.\n(C) They're sitting.\n(D) They're swimming.",
        "(A) 他们在划船。\n(B) 他们在抬东西。\n(C) 他们坐着。\n(D) 他们在游泳。"),
    2: ("When will you leave?\n(A) On Monday.\n(B) With Jane.\n(C) By train.",
        "你什么时候出发？\n(A) 星期一。\n(B) 和简一起。\n(C) 坐火车。"),
    3: ("M1: Are you ready?\nW: Yes, let's go.", "M1: 你准备好了吗？\nW: 是的，走吧。"),
    4: ("Welcome to CTV. We begin at 9:30.", "CTV年度活动将在9点半开始。"),
}


@pytest.fixture
def review_services(app_services):
    svc = app_services
    path = svc.library.root / "exams/test-01.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in raw["questions"]}
    cues = []
    for part in (1, 2, 3, 4):
        groups = [g for g in raw["groups"] if g["part"] == part]
        for i, g in enumerate(groups):
            numbers = [questions[qid]["number"] for qid in g["question_ids"]]
            cues.append({"part": part, "first_question": min(numbers), "last_question": max(numbers),
                         "start_seconds": (part - 1) * 30 + i * 30 / len(groups),
                         "end_seconds": (part - 1) * 30 + (i + 1) * 30 / len(groups), "verified": True})
            if part <= 2:
                questions[g["question_ids"][0]]["explanation"] = {"text": SHORT[part], "source_pages": [401]}
            else:
                g["review_source_pages"] = [402, 403]
                heading = f"Questions {min(numbers)} through {max(numbers)} refer to the following "
                g["review_text"] = (
                    heading + "conversation and survey.\nM1: Are you\nready?\n（\n" + str(min(numbers)) +
                    ", " + str(max(numbers)) + "\n）\nW: Yes, let's go.\nSurvey Results\nM1\n：你准备好了吗？\n"
                    "W: 是的，走吧。\n调查结果\nready\n准备好的\n go\n走"
                    if part == 3 else
                    heading + "talk.\nWelcome to CTV. We begin at 9:30.\n（" + str(min(numbers)) +
                    "）\nCTV\n年度活动将在\n9\n点半开始。\nannual\n年度的\n begin\n开始"
                )
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    cue_path = svc.library.root / "audio-cues.json"
    data = json.loads(cue_path.read_text(encoding="utf-8"))
    data["exams"]["test-01"]["groups"] = cues
    cue_path.write_text(json.dumps(data), encoding="utf-8")
    svc.library.load()
    return svc


def create(svc, scope="listening", mode="practice", parts=None):
    return svc.attempts.create({"exam_ids": ["test-01"], "scope": scope, "mode": mode,
                                "parts": parts or [1, 2, 3, 4], "question_filter": "all",
                                "timer": {"kind": "countdown", "duration_seconds": 600}})


def snapshot(svc, aid):
    return dict(svc.store.query("SELECT questions,groups,audio_queue,report FROM attempts WHERE id=?", (aid,))[0])


@pytest.mark.parametrize("scope,mode,parts", [("listening", "practice", None),
    ("full", "exam", None), ("listening", "exam", None), ("part", "exam", [1, 2, 3, 4])])
def test_exact_review_snapshots_in_every_audio_mode_and_private_until_closed(review_services, scope, mode, parts):
    svc = review_services
    a = create(svc, scope, mode, parts)
    groups = json.loads(snapshot(svc, a["id"])["groups"])
    exam = svc.library.exams["test-01"]
    for group in groups:
        if group["part"] > 4:
            assert "_review_audio" not in group and "_listening_script" not in group
            continue
        cue = svc.library.group_cue_for(exam, group)
        item = group["_review_audio"]
        assert (item["start_seconds"], item["end_seconds"]) == (cue.start_seconds, cue.end_seconds)
        assert item["question_ids"] == group["question_ids"]
        assert item["group_id"] == group["id"] and item["part"] == group["part"]
        script = group["_listening_script"]
        assert (script["english"], script["chinese"]) == EXPECTED[group["part"]]
        assert script["source_pages"] == ([401] if group["part"] <= 2 else [402, 403])
    for active in (a, svc.attempts.claim(a["id"], "review", False),
                   svc.attempts.start(a["id"], "review", True), svc.attempts.get(a["id"])):
        if mode == "practice" and active["status"] != "ready":
            assert_practice_scripts(active, groups)
        else:
            assert_private(active)
    with pytest.raises(ApiError) as error:
        svc.attempts.report(a["id"])
    assert error.value.code == "report_not_ready"
    report = svc.attempts.submit(a["id"], "review")
    for group in report["groups"]:
        if group["part"] <= 4:
            source = next(g for g in groups if g["id"] == group["id"])
            assert group["review_audio"] == source["_review_audio"]
            assert group["listening_script"] == source["_listening_script"]
            assert not any(k.startswith("_") for k in group)
    if mode == "practice":
        assert_practice_scripts(svc.attempts.get(a["id"]), groups)
    else:
        assert_private(svc.attempts.get(a["id"]))


def assert_practice_scripts(dto, frozen_groups=None):
    for group in dto["groups"]:
        assert not any(k.startswith("_") for k in group)
        assert "review_text" not in group and "review_audio" not in group
        if group["part"] <= 4:
            assert group.get("listening_script")
            if frozen_groups is not None:
                frozen = next(g for g in frozen_groups if g["id"] == group["id"])
                assert group["listening_script"] == frozen["_listening_script"]


def assert_private(dto):
    value = json.dumps(dto, ensure_ascii=False)
    for field in ("_review_audio", "review_audio", "_listening_script", "listening_script", "review_text", "chinese"):
        assert '"' + field + '"' not in value
    assert "你准备好了吗" not in value and "They're rowing" not in value


def test_creation_freezes_content_and_boundaries_even_if_library_changes_before_submit(review_services):
    svc = review_services
    a = create(svc, "full", "exam")
    before = snapshot(svc, a["id"])
    exam = svc.library.exams["test-01"]
    for g in exam.groups:
        g["review_text"] = "ALTERED LIBRARY"
    for q in exam.questions:
        q["explanation"] = {"text": "ALTERED LIBRARY", "source_pages": [999]}
    for cue in exam.group_cues:
        cue.start_seconds += .125
    report = svc.attempts.submit(a["id"], None)
    frozen = json.loads(before["groups"])
    for g in report["groups"]:
        if g["part"] <= 4:
            old = next(x for x in frozen if x["id"] == g["id"])
            assert g["review_audio"] == old["_review_audio"]
            assert g["listening_script"] == old["_listening_script"]
    svc.library.exams.clear()
    before_read = snapshot(svc, a["id"])
    assert svc.attempts.report(a["id"]) == report
    assert svc.attempts.report(a["id"]) == report
    assert snapshot(svc, a["id"]) == before_read
    with svc.store.transaction() as conn:
        record = svc.attempts._load_record(conn, a["id"])
    frozen_record = copy.deepcopy(record)
    enriched = svc.attempts._enrich_report(record)
    enriched["groups"][0]["listening_script"]["english"] = "caller mutation"
    assert record == frozen_record


@pytest.mark.parametrize("legacy_queue", ["exact", "part", "full", "other_group", "extra_question", "wrong_part", "bad_bounds"])
def test_legacy_uses_only_own_text_and_exact_snapshot_group_audio(review_services, legacy_queue):
    svc = review_services
    a = create(svc)
    report = svc.attempts.submit(a["id"], None)
    row = snapshot(svc, a["id"])
    groups = json.loads(row["groups"])
    target = next(g for g in groups if g["part"] == 3)
    exact = copy.deepcopy(target["_review_audio"])
    for g in groups:
        g.pop("_review_audio", None)
        g.pop("_listening_script", None)
    for g in report["groups"]:
        g.pop("review_audio", None)
        g.pop("listening_script", None)
    if legacy_queue == "part":
        exact.pop("group_id", None)
        exact["question_ids"] = [q["id"] for q in report["questions"] if q["part"] == 3]
    elif legacy_queue == "full":
        exact.pop("group_id", None)
        exact["part"] = 0
        exact["question_ids"] = [q["id"] for q in report["questions"]]
    elif legacy_queue == "other_group":
        exact["group_id"] = "another-group"
    elif legacy_queue == "extra_question":
        exact["question_ids"].append("unrelated")
    elif legacy_queue == "wrong_part":
        exact["part"] = 4
    elif legacy_queue == "bad_bounds":
        exact["end_seconds"] = exact["start_seconds"]
    with svc.store.transaction() as conn:
        conn.execute("UPDATE attempts SET groups=?,audio_queue=?,report=? WHERE id=?",
                     (json.dumps(groups), json.dumps([exact]), json.dumps(report), a["id"]))
    svc.library.exams.clear()  # lookup of any current content cannot help a legacy report
    before = snapshot(svc, a["id"])
    got = svc.attempts.report(a["id"])
    for g in got["groups"]:
        assert (g["listening_script"]["english"], g["listening_script"]["chinese"]) == EXPECTED[g["part"]]
        if g["id"] == target["id"] and legacy_queue == "exact":
            assert g["review_audio"] == exact
        else:
            assert "review_audio" not in g
    assert snapshot(svc, a["id"]) == before


@pytest.mark.parametrize("kind", ["missing", "unverified", "out_of_range", "nan"])
def test_no_review_audio_when_no_valid_group_cue(review_services, kind):
    svc = review_services
    exam = svc.library.exams["test-01"]
    if kind == "missing":
        exam.group_cues = []
    else:
        for cue in exam.group_cues:
            if kind == "unverified": cue.verified = False
            if kind == "out_of_range": cue.end_seconds = 9999
            if kind == "nan": cue.start_seconds = float("nan")
    a = create(svc, "full", "exam")
    assert all(g.get("_review_audio") is None for g in json.loads(snapshot(svc, a["id"])["groups"]))
    assert all("review_audio" not in g for g in svc.attempts.submit(a["id"], None)["groups"])


def test_uncertain_script_is_missing_and_original_review_remains(review_services):
    svc = review_services
    exam = svc.library.exams["test-01"]
    for g in exam.groups:
        g["review_text"] = "Unrecognized layout without a translation."
    for q in exam.questions:
        q["explanation"] = {"text": "Unrecognized explanation.", "source_pages": [999]}
    a = create(svc)
    report = svc.attempts.submit(a["id"], None)
    assert all("listening_script" not in g for g in report["groups"])
    assert report["groups"][0]["review_text"] == "Unrecognized layout without a translation."
    assert report["questions"][0]["explanation"]["text"] == "Unrecognized explanation."


@pytest.mark.parametrize("part,corruption", [(1, "missing_option"), (2, "missing_chinese"),
    (3, "wrong_heading"), (3, "unrecognized_annotation"), (4, "missing_chinese")])
def test_unknown_layout_returns_missing_instead_of_inventing_a_script(review_services, part, corruption):
    from toeic_practice.listening_review import extract_listening_script
    exam = review_services.library.exams["test-01"]
    g = copy.deepcopy(next(g for g in exam.groups if g["part"] == part))
    qs = copy.deepcopy([q for q in exam.questions if q["id"] in g["question_ids"]])
    if corruption == "missing_option":
        qs[0]["explanation"]["text"] = SHORT[1].replace("（B）They're lifting.", "")
    elif corruption == "missing_chinese":
        if part == 2:
            qs[0]["explanation"]["text"] = "When?\n(A) Now.\n(B) Later.\n(C) Tomorrow."
        else:
            g["review_text"] = "Questions 71 through 73 refer to the following talk.\nHello."
    elif corruption == "wrong_heading":
        g["review_text"] = g["review_text"].replace("Questions 32", "Questions 99")
    else:
        g["review_text"] = g["review_text"].replace("Are you", "(Q99) Are you")
    assert extract_listening_script(g, qs) is None


def test_expired_attempt_exposes_review_only_after_clock_closes(review_services, clock):
    svc = review_services
    a = create(svc, "part", "practice", [2])
    svc.attempts.claim(a["id"], "review", False)
    assert_practice_scripts(svc.attempts.start(a["id"], "review", True))
    clock.advance(601)
    report = svc.attempts.report(a["id"])
    assert report["attempt"]["status"] == "expired"
    assert all(g.get("review_audio") and g.get("listening_script") for g in report["groups"])


@pytest.mark.parametrize("gid,english,chinese,excluded", [
    ("t03-p3-q068", "www.computerpurchases.com?", "www.computepurchases.com", "可获得的"),
    ("t06-p3-q059", "app", "app", "monitor"),
    ("t10-p4-q077", "Xenox-alpha", "Xenox-alpha", "after-sales service\n售后"),
    ("t09-p4-q074", "CTV", "CTV年度", "prestige"),
    ("t03-p4-q098", "e-mail address", "电子邮件地址", "Radio 103.4 FM Schedule"),
    ("t01-p3-q068", "M: Okay.", "M: 好", "Rosemary's Survey Results"),
])
def test_real_source_wraps_and_graphic_titles(gid, english, chinese, excluded):
    from toeic_practice.listening_review import extract_listening_script
    root = Path(__file__).resolve().parents[2] / ".data/library/exams"
    path = root / f"test-{gid[1:3]}.json"
    if not path.exists():
        pytest.skip("real built-in sources are not installed")
    exam = json.loads(path.read_text(encoding="utf-8"))
    group = next(g for g in exam["groups"] if g["id"] == gid)
    script = extract_listening_script(group, exam["questions"])
    assert script and english in script["english"] and chinese in script["chinese"]
    assert excluded not in script["chinese"]
    if excluded[:1].isupper():  # graphic captions, unlike words actually spoken
        assert excluded not in script["english"]


@pytest.mark.parametrize("gid,en_labels,zh_labels", [
    ("t05-p3-q044", ["M", "W", "M", "W", "M", "W"], ["M", "W", "M", "W", "M", "W"]),
    ("t07-p3-q065", ["M", "W", "M", "W", "M", "W"], ["W", "M", "W", "M", "W", "M"]),
    ("t09-p3-q035", ["W", "M", "W", "M", "W", "M"], ["W", "M", "W", "W", "W", "M"]),
])
def test_printed_source_speaker_identities_are_preserved(gid, en_labels, zh_labels):
    from toeic_practice.listening_review import extract_listening_script
    path = Path(__file__).resolve().parents[2] / f".data/library/exams/test-{gid[1:3]}.json"
    if not path.exists():
        pytest.skip("real built-in sources are not installed")
    exam = json.loads(path.read_text(encoding="utf-8"))
    group = next(g for g in exam["groups"] if g["id"] == gid)
    script = extract_listening_script(group, exam["questions"])
    assert re.findall(r"(?m)^([MW][12]?):", script["english"]) == en_labels
    assert re.findall(r"(?m)^([MW][12]?):", script["chinese"]) == zh_labels


def test_all_ten_builtin_listening_sources_have_exact_cues_and_core_scripts():
    root = Path(__file__).resolve().parents[2] / ".data/library"
    if not (root / "manifest.json").exists():
        pytest.skip("real built-in sources are not installed")
    from toeic_practice.listening_review import extract_listening_script
    library = Library(root)
    library.load()
    counts = [0, 0]
    for exam in library.exams.values():
        for g in exam.groups:
            if g["part"] > 4: continue
            qs = [q for q in exam.questions if q["id"] in g["question_ids"]]
            script = extract_listening_script(g, qs)
            assert script, (exam.id, g["id"])
            cue = library.group_cue_for(exam, g)
            assert cue and cue.verified and 0 <= cue.start_seconds < cue.end_seconds <= exam.full_end_seconds
            assert script["source_pages"] == g.get("review_source_pages", qs[0]["explanation"]["source_pages"])
            assert "·They" not in script["english"] and "\nQ " not in script["english"]
            assert not re.search(r"[（(]\s*(?:Q\s*)?\d+(?:\s*[,，]\s*\d+)*\s*[）)]", script["english"])
            counts[0] += 1
            counts[1] += len(qs)
    assert len(library.exams) == 10 and counts == [540, 1000]
