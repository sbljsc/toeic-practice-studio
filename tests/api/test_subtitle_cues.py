"""Observable subtitle privacy, frozen history and fail-closed sidecar contracts."""
import copy
import hashlib
import json

import pytest

from test_listening_review import review_services, create, snapshot


@pytest.fixture
def timed_services(review_services):
    svc = review_services
    exam = svc.library.exams["test-01"]
    group = next(g for g in exam.groups if g["part"] == 1)
    cue = svc.library.group_cue_for(exam, group)
    english = "(A) They're rowing.\n(B) They're lifting.\n(C) They're sitting.\n(D) They're swimming."
    entry = {
        "verified": True, "exam_id": exam.id, "group_id": group["id"], "part": 1,
        "question_ids": group["question_ids"], "english_sha256": hashlib.sha256(english.encode()).hexdigest(),
        "source_pages": [401], "asset_id": exam.audio["asset_id"],
        "asset_sha256": hashlib.sha256((svc.library.root / "media/test-01.mp3").read_bytes()).hexdigest(),
        "source_duration_seconds": 120.0,
        "start_seconds": cue.start_seconds, "end_seconds": cue.end_seconds,
        "provenance": {"method": "source-word-alignment-v1", "evidence": ".data/audio-audit/subtitle-alignment.json", "acoustic_version": 1},
        "sentences": [{"id": group["id"] + f"-s{i+1:03d}", "text": text,
                       "start_seconds": i * 1.0, "end_seconds": i * 1.0 + .7}
                      for i, text in enumerate(english.splitlines())],
    }
    path = svc.library.root / "subtitle-cues.json"
    path.write_text(json.dumps({"schema_version": 1, "groups": [entry]}), encoding="utf-8")
    svc.library.load()
    return svc, entry, path


def first_script(dto):
    return dto["groups"][0].get("listening_script")


@pytest.mark.parametrize("mode", ["practice", "exam"])
def test_timed_script_visibility_follows_active_mode_and_start(timed_services, mode):
    svc, entry, _ = timed_services
    a = create(svc, "part", mode, [1])
    assert first_script(a) is None
    assert first_script(svc.attempts.claim(a["id"], "subtitle", False)) is None
    started = svc.attempts.start(a["id"], "subtitle", True)
    if mode == "practice":
        assert first_script(started)["sentences"] == entry["sentences"]
        assert first_script(svc.attempts.pause(a["id"], "subtitle"))["sentences"] == entry["sentences"]
    else:
        assert first_script(started) is None
        # An interrupted/paused exam must not reveal scripts on its next read.
        with svc.store.transaction() as conn:
            conn.execute("UPDATE attempts SET status='paused',integrity='interrupted' WHERE id=?", (a["id"],))
        assert first_script(svc.attempts.get(a["id"])) is None
        converted = svc.attempts.continue_practice(a["id"], "subtitle")
        assert converted["mode"] == "practice"
        assert first_script(converted)["sentences"] == entry["sentences"]
    report = svc.attempts.submit(a["id"], "subtitle")
    assert first_script(report)["sentences"] == entry["sentences"]
    assert not any(k.startswith("_") for g in started["groups"] for k in g)


def test_exam_report_gets_timing_only_after_closure(timed_services):
    svc, entry, _ = timed_services
    a = create(svc, "part", "exam", [1])
    assert first_script(svc.attempts.submit(a["id"], None))["sentences"] == entry["sentences"]
    assert first_script(svc.attempts.get(a["id"])) is None


def test_new_snapshot_keeps_sentences_when_sidecar_removed(timed_services):
    svc, entry, path = timed_services
    a = create(svc, "part", "exam", [1])
    before = snapshot(svc, a["id"])
    frozen = json.loads(before["groups"])[0]["_listening_script"]
    assert frozen["sentences"] == entry["sentences"]
    path.write_text('{"schema_version":1,"groups":[]}', encoding="utf-8")
    svc.library.load()
    assert first_script(svc.attempts.submit(a["id"], None)) == frozen
    assert snapshot(svc, a["id"])["groups"] == before["groups"]


def test_pre_acoustic_provisional_snapshot_hides_timing_without_rewriting_history(timed_services):
    svc, _, _ = timed_services
    a = create(svc, "part", "exam", [1])
    svc.attempts.submit(a["id"], None)
    row = snapshot(svc, a["id"])
    groups = json.loads(row["groups"])
    for group in groups:
        group.pop("_subtitle_quality_version", None)
    with svc.store.transaction() as conn:
        conn.execute("UPDATE attempts SET groups=? WHERE id=?", (json.dumps(groups), a["id"]))
    before = snapshot(svc, a["id"])
    assert "sentences" not in first_script(svc.attempts.report(a["id"]))
    assert snapshot(svc, a["id"]) == before


@pytest.mark.parametrize("mismatch", [None, "english", "asset", "bounds", "url"])
def test_legacy_derivation_requires_exact_frozen_identity_and_never_writes(timed_services, mismatch):
    svc, entry, _ = timed_services
    a = create(svc, "part", "exam", [1])
    svc.attempts.submit(a["id"], None)
    row = snapshot(svc, a["id"])
    groups = json.loads(row["groups"])
    target = groups[0]
    target.pop("_subtitle_frozen", None)
    target["_listening_script"].pop("sentences", None)
    if mismatch == "english": target["_listening_script"]["english"] += " Changed."
    if mismatch == "asset": target["_review_audio"]["asset_id"] = "other"
    if mismatch == "bounds": target["_review_audio"]["end_seconds"] -= .1
    if mismatch == "url": target["_review_audio"]["url"] = "/api/assets/other"
    with svc.store.transaction() as conn:
        conn.execute("UPDATE attempts SET groups=? WHERE id=?", (json.dumps(groups), a["id"]))
    before = snapshot(svc, a["id"])
    got = first_script(svc.attempts.report(a["id"]))
    assert (got.get("sentences") == entry["sentences"]) == (mismatch is None)
    assert snapshot(svc, a["id"]) == before


@pytest.mark.parametrize("corrupt", ["schema", "english", "pages", "asset", "hash", "bounds", "duration",
    "empty", "nan", "overlap", "reorder", "text", "duplicate", "unverified", "provenance", "bool", "clip_bool", "part_bool", "schema_bool", "huge_integer", "huge_sentence_integer"])
def test_invalid_metadata_hides_all_sentence_data_without_hiding_source(timed_services, corrupt):
    svc, entry, path = timed_services
    entry = copy.deepcopy(entry)
    data = {"schema_version": 1, "groups": [entry]}
    if corrupt == "schema": data["schema_version"] = 9
    if corrupt == "english": entry["english_sha256"] = "0" * 64
    if corrupt == "pages": entry["source_pages"] = [999]
    if corrupt == "asset": entry["asset_id"] = "other"
    if corrupt == "hash": entry["asset_sha256"] = "0" * 64
    if corrupt == "bounds": entry["start_seconds"] += .1
    if corrupt == "duration": entry["source_duration_seconds"] = 121
    if corrupt == "empty": entry["sentences"] = []
    if corrupt == "nan": entry["sentences"][0]["start_seconds"] = float("nan")
    if corrupt == "overlap": entry["sentences"][1]["start_seconds"] = .5
    if corrupt == "reorder": entry["sentences"].reverse()
    if corrupt == "text": entry["sentences"][0]["text"] = "ASR paraphrase."
    if corrupt == "duplicate": entry["sentences"][1]["id"] = entry["sentences"][0]["id"]
    if corrupt == "unverified": entry["verified"] = False
    if corrupt == "provenance": entry.pop("provenance")
    if corrupt == "bool": entry["sentences"][0]["start_seconds"] = False
    if corrupt == "clip_bool": entry["start_seconds"] = False
    if corrupt == "part_bool": entry["part"] = True
    if corrupt == "schema_bool": data["schema_version"] = True
    if corrupt == "huge_integer": entry["source_duration_seconds"] = 10**1000
    if corrupt == "huge_sentence_integer": entry["sentences"][0]["start_seconds"] = 10**1000
    path.write_text(json.dumps(data), encoding="utf-8")
    svc.library.load()
    a = create(svc, "part", "exam", [1])
    script = first_script(svc.attempts.submit(a["id"], None))
    assert script and "sentences" not in script


def test_sentence_validation_rejects_overflow_without_raising(timed_services):
    from toeic_practice.subtitle_cues import valid_sentences
    svc, entry, _ = timed_services
    script = {"english": "\n".join(s["text"] for s in entry["sentences"])}
    sentences = copy.deepcopy(entry["sentences"])
    group = {"id": entry["group_id"], "part": 1}
    audio = {"start_seconds": 0, "end_seconds": 5}
    sentences[0]["end_seconds"] = 10**1000
    assert valid_sentences(sentences, script, group, audio) is False
    audio["end_seconds"] = 10**1000
    assert valid_sentences(entry["sentences"], script, group, audio) is False


def test_subtitle_presentation_does_not_invalidate_library_filters(timed_services):
    svc, _, path = timed_services
    version = svc.library.library_version()
    path.write_text('{"schema_version":1,"groups":[]}', encoding="utf-8")
    svc.library.load()
    assert svc.library.library_version() == version


def test_sentence_segmentation_preserves_options_labels_and_abbreviations():
    from toeic_practice.subtitle_cues import sentence_units
    assert sentence_units("(A) Dr. Smith left at 9 a.m.\n(B) It costs 3.5 dollars.\n(C) See example.com.\n(D) Wait... please.", 1) == [
        "(A) Dr. Smith left at 9 a.m.", "(B) It costs 3.5 dollars.", "(C) See example.com.", "(D) Wait... please."]
    assert sentence_units("M: Mr. Jones arrives at 5 p.m. today. W: Really?", 3) == [
        "M: Mr. Jones arrives at 5 p.m. today.", "W: Really?"]
    assert sentence_units("Arrives at 4:50 p. m. on Friday. Call Dr. Smith.", 4) == [
        "Arrives at 4:50 p. m. on Friday.", "Call Dr. Smith."]
