"""Question attention measurements never influence the examination clock."""
import uuid

from test_attempts import create, start, answer, hdr, TAB


def pulse(client, attempt, sequence, qid, **override):
    body = {"session_id": attempt["activity_session_id"], "sequence": sequence,
            "question_id": qid}
    body.update(override)
    return client.put(f"/api/attempts/{attempt['id']}/activity", json=body, headers=hdr())


def test_dwell_revisit_first_answer_and_frozen_report(client, clock):
    att = start(client, create(client))
    q1, q2 = [q['id'] for q in att['questions'][:2]]
    assert pulse(client, att, 1, q1).status_code == 200
    clock.advance(4)
    assert answer(client, att, q1, 'A').status_code == 200
    clock.advance(2)
    assert pulse(client, att, 2, q2).status_code == 200
    clock.advance(3)
    assert pulse(client, att, 3, q1).status_code == 200
    clock.advance(1)
    report = client.post(f"/api/attempts/{att['id']}/submit", headers=hdr()).json()
    data = report['activity']
    assert data['coverage'] == 'from_start'
    assert data['total_elapsed_ms'] == data['tracked_ms'] == 10000
    assert data['unattributed_ms'] == 0
    assert data['questions'][0]['dwell_ms'] == 7000
    assert data['questions'][0]['first_answer_ms'] == 4000
    assert data['questions'][1]['dwell_ms'] == 3000
    assert data['parts'] == [{'part': 5, 'dwell_ms': 10000}]
    clock.advance(90)
    assert pulse(client, att, 4, q2).status_code == 410
    assert client.get(f"/api/attempts/{att['id']}/report").json()['activity'] == data


def test_statistics_background_and_pause_are_not_question_time(client, clock):
    att = start(client, create(client))
    q1 = att['questions'][0]['id']
    pulse(client, att, 1, q1)
    clock.advance(2)
    pulse(client, att, 2, None)
    clock.advance(5)
    pulse(client, att, 3, q1)
    clock.advance(3)
    client.post(f"/api/attempts/{att['id']}/pause", headers=hdr())
    clock.advance(200)
    pulse(client, att, 4, q1)  # a paused pulse cannot start a lease
    client.post(f"/api/attempts/{att['id']}/resume", headers=hdr())
    clock.advance(2)
    data = pulse(client, att, 5, None).json()['activity']
    assert data['tracked_ms'] == 5000
    assert data['total_elapsed_ms'] == 12000
    assert data['unattributed_ms'] == 7000


def test_lease_bounds_disconnect_and_read_poll_does_not_renew(client, clock):
    att = start(client, create(client))
    pulse(client, att, 1, att['questions'][0]['id'])
    clock.advance(9)
    client.get(f"/api/attempts/{att['id']}/clock")
    clock.advance(30)
    data = client.get(f"/api/attempts/{att['id']}").json()['activity']
    assert data['tracked_ms'] == 15000
    assert data['unattributed_ms'] == 24000


def test_activity_sequence_and_claim_session_block_late_events(client, clock):
    att = start(client, create(client))
    q1, q2 = [q['id'] for q in att['questions'][:2]]
    pulse(client, att, 2, q1)
    clock.advance(2)
    assert pulse(client, att, 1, q2).status_code == 200  # harmless stale event
    clock.advance(2)
    claimed = client.post(f"/api/attempts/{att['id']}/claim", json={}, headers=hdr()).json()
    assert claimed['activity_session_id'] != att['activity_session_id']
    assert pulse(client, att, 3, q2).status_code == 409
    clock.advance(2)
    data = pulse(client, claimed, 1, None).json()['activity']
    assert data['questions'][0]['dwell_ms'] == 4000
    assert data['questions'][1]['dwell_ms'] == 0
    other = {**hdr(), 'X-Tab-ID': 'another-tab'}
    bad = client.put(f"/api/attempts/{att['id']}/activity", json={
        'session_id': claimed['activity_session_id'], 'sequence': 2, 'question_id': q2}, headers=other)
    assert bad.status_code == 409


def test_takeover_settles_previous_owner_then_requires_new_presence(client, clock):
    att = start(client, create(client))
    q1, q2 = [q['id'] for q in att['questions'][:2]]
    pulse(client, att, 1, q1)
    clock.advance(4)
    other = {**hdr(), 'X-Tab-ID': 'another-tab'}
    took = client.post(f"/api/attempts/{att['id']}/claim", json={'takeover': True}, headers=other).json()
    clock.advance(3)
    assert pulse(client, att, 2, q1).status_code == 409
    data = client.put(f"/api/attempts/{att['id']}/activity", json={
        'session_id': took['activity_session_id'], 'sequence': 1, 'question_id': q2}, headers=other).json()['activity']
    assert data['tracked_ms'] == 4000
    assert data['unattributed_ms'] == 3000
    clock.advance(2)
    data = client.get(f"/api/attempts/{att['id']}").json()['activity']
    assert data['questions'][1]['dwell_ms'] == 2000


def test_retry_first_answer_is_idempotent_and_instant_observation_is_zero(client, clock):
    att = start(client, create(client))
    q1, q2 = [q['id'] for q in att['questions'][:2]]
    pulse(client, att, 1, q1)
    instant = answer(client, att, q1, 'A').json()
    assert instant['activity']['questions'][0]['first_answer_ms'] == 0
    pulse(client, att, 2, q2)
    clock.advance(2)
    mutation = str(uuid.uuid4())
    answer(client, att, q2, 'B', mutation_id=mutation)
    clock.advance(3)
    retry = answer(client, att, q2, 'B', mutation_id=mutation).json()['activity']
    assert retry['questions'][1]['first_answer_ms'] == 2000
    assert retry['questions'][1]['dwell_ms'] == 5000


def test_expiry_and_full_phase_boundary_cap_attention(client, clock):
    att = start(client, create(client, timer={'kind': 'countdown', 'duration_seconds': 10}))
    pulse(client, att, 1, att['questions'][0]['id'])
    clock.advance(99)
    report = client.get(f"/api/attempts/{att['id']}/report").json()
    assert report['activity']['tracked_ms'] == report['activity']['total_elapsed_ms'] == 10000
    full = start(client, create(client, scope='full', parts=[], mode='exam'))
    q1 = full['questions'][0]['id']
    clock.advance(118)
    pulse(client, full, 1, q1)
    clock.advance(6)
    data = client.get(f"/api/attempts/{full['id']}").json()
    assert data['timing']['phase'] == 'reading'
    assert data['activity']['questions'][0]['dwell_ms'] == 2000
    assert pulse(client, full, 2, q1).status_code == 409
    reading_id = next(q['id'] for q in full['questions'] if q['part'] == 5)
    assert pulse(client, full, 3, reading_id).status_code == 200


def test_server_restart_does_not_charge_foreign_monotonic_lease(app_services, clock):
    service = app_services.attempts
    att = service.create({'exam_ids': ['test-01'], 'scope': 'part', 'parts': [5],
                          'mode': 'practice', 'timer': {'kind': 'countup'}})
    service.claim(att['id'], TAB, False)
    att = service.start(att['id'], TAB, True)
    service.set_activity(att['id'], TAB, {'session_id': att['activity_session_id'],
        'sequence': 1, 'question_id': att['questions'][0]['id']})
    clock.advance(3)
    assert service.get(att['id'])['activity']['tracked_ms'] == 3000
    clock.identity = uuid.uuid4().hex
    clock.advance(300)
    data = service.get(att['id'])['activity']
    assert data['tracked_ms'] == 3000
    assert data['unattributed_ms'] == 300000


def test_legacy_data_remains_unavailable_and_running_upgrade_is_partial(client, clock):
    att = start(client, create(client))
    store = client.app.state.services.store
    with store.transaction() as db:
        db.execute('UPDATE attempts SET activity=NULL WHERE id=?', (att['id'],))
    clock.advance(10)
    loaded = client.get(f"/api/attempts/{att['id']}").json()
    assert loaded['activity']['coverage'] == 'unavailable'
    assert all(q['dwell_ms'] is None for q in loaded['activity']['questions'])
    claimed = client.post(f"/api/attempts/{att['id']}/claim", json={}, headers=hdr()).json()
    pulse(client, claimed, 1, claimed['questions'][0]['id'])
    clock.advance(3)
    report = client.post(f"/api/attempts/{att['id']}/submit", headers=hdr()).json()
    assert report['activity']['coverage'] == 'partial'
    assert report['activity']['tracked_ms'] == 3000
    assert report['activity']['unattributed_ms'] == 10000


def test_invalid_qid_session_and_payload_cannot_change_deadlines(client, clock):
    att = start(client, create(client))
    deadline = att['timing']['deadline_at_ms']
    assert pulse(client, att, 1, 'missing-q').status_code == 404
    assert pulse(client, att, -1, None).status_code == 422
    assert pulse(client, att, 2, None, session_id='missing').status_code == 409
    pulse(client, att, 3, att['questions'][0]['id'], duration_seconds=999999)
    data = client.get(f"/api/attempts/{att['id']}").json()
    assert data['timing']['deadline_at_ms'] == deadline
    assert all('answer' not in q and '_answer' not in q for q in data['activity']['questions'])


def test_unobserved_answer_stays_unknown_even_after_clear_and_reanswer(client, clock):
    att = start(client, create(client))
    qid = att['questions'][0]['id']
    answer(client, att, qid, 'A')
    pulse(client, att, 1, qid)
    clock.advance(2)
    answer(client, att, qid, None, revision=1)
    clock.advance(1)
    data = answer(client, att, qid, 'B', revision=2).json()['activity']
    assert data['questions'][0]['dwell_ms'] == 3000
    assert data['questions'][0]['first_answer_ms'] is None


def test_legacy_closed_report_is_not_rewritten(client):
    att = start(client, create(client))
    report = client.post(f"/api/attempts/{att['id']}/submit", headers=hdr()).json()
    report.pop('activity')
    import json
    raw = json.dumps(report)
    store = client.app.state.services.store
    with store.transaction() as db:
        db.execute('UPDATE attempts SET activity=NULL,report=? WHERE id=?', (raw, att['id']))
    result = client.get(f"/api/attempts/{att['id']}/report").json()
    assert result['activity']['coverage'] == 'unavailable'
    assert store.query_one('SELECT report FROM attempts WHERE id=?', (att['id'],))['report'] == raw


def test_additive_migration_keeps_original_database_and_legacy_backup(client, tmp_path):
    import sqlite3
    from toeic_practice.store import Store
    from toeic_practice.backups import checksum
    store = client.app.state.services.store
    backup_service = client.app.state.services.backups
    att = start(client, create(client))
    meta = backup_service.create()
    path = backup_service._file_path(meta['id'])
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE attempts DROP COLUMN activity')
    meta['sha256'] = checksum(path)
    backup_service._validate_database(path, meta)
    reopened = Store(path)
    assert reopened.query_one('SELECT COUNT(*) AS n FROM attempts')['n'] == 1
    assert reopened.query_one('SELECT activity FROM attempts WHERE id=?', (att['id'],))['activity'] is None
    reopened.close()


def test_partial_upgrade_preserves_prior_answer_fact_across_clear(client, clock):
    att = start(client, create(client))
    qid = att['questions'][0]['id']
    answer(client, att, qid, 'A')
    with client.app.state.services.store.transaction() as db:
        db.execute('UPDATE attempts SET activity=NULL WHERE id=?', (att['id'],))
    claimed = client.post(f"/api/attempts/{att['id']}/claim", json={}, headers=hdr()).json()
    pulse(client, claimed, 1, qid)
    clock.advance(2)
    answer(client, claimed, qid, None, revision=1)
    clock.advance(3)
    result = answer(client, claimed, qid, 'B', revision=2).json()['activity']
    assert result['coverage'] == 'partial'
    assert result['questions'][0]['dwell_ms'] == 5000
    assert result['questions'][0]['first_answer_ms'] is None


def test_actual_same_process_restore_invalidates_presence_and_session(client, clock):
    att = start(client, create(client))
    qid = att['questions'][0]['id']
    pulse(client, att, 1, qid)
    clock.advance(2)
    snapshot = pulse(client, att, 2, qid).json()['activity']
    backup = client.post('/api/backups', json={'include_library': False}, headers=hdr()).json()
    clock.advance(1)
    client.post(f"/api/attempts/{att['id']}/submit", headers=hdr())
    clock.advance(7)
    restored = client.post(f"/api/backups/{backup['id']}/restore", json={'confirm': True}, headers=hdr())
    assert restored.status_code == 200, restored.text
    loaded = client.get(f"/api/attempts/{att['id']}").json()
    assert loaded['activity']['tracked_ms'] == snapshot['tracked_ms'] == 2000
    assert loaded['activity_session_id'] is None
    assert pulse(client, att, 3, qid).status_code == 409
    claimed = client.post(f"/api/attempts/{att['id']}/claim", json={}, headers=hdr()).json()
    pulse(client, claimed, 1, qid)
    clock.advance(1)
    assert client.get(f"/api/attempts/{att['id']}").json()['activity']['tracked_ms'] == 3000
