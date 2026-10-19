"""Real HTTP contracts for flat pools, priorities, snapshots and bank browsing."""
import json
import hashlib

import pytest
from fastapi.testclient import TestClient

from toeic_practice.app import create_app
from toeic_practice.library import Library
from test_attempts import hdr,start,answer


@pytest.fixture
def pool_root(tmp_path):
    root=tmp_path/'pool';root.mkdir()
    (root/'clip.flac').write_bytes(b'fLaC'+b'0'*128)
    groups,questions=[],[]
    shape=[(p,s,None) for p,n,s in [(1,6,1),(2,25,1),(3,13,3),(4,10,3),(5,30,1),(6,4,4)] for _ in range(n)]
    shape += [(7,s,'single') for s in [2,2,2,2,3,3,3,4,4,4]]
    shape += [(7,5,t) for t in ['double','double','triple','triple','triple']]
    for batch in range(2):
        for i,(part,size,category) in enumerate(shape):
            gid=f'g{batch}-{i}'
            ids=[f'{gid}-q{j}' for j in range(size)]
            g={'id':gid,'part':part,'section':'listening' if part<=4 else 'reading','question_ids':ids,
                'materials':[],'review_text':'Material explanation.','source_pages':[]}
            if part<=4:
                script='Example speech.'
                g['audio']={'asset_id':'clip','start_seconds':0,'end_seconds':2,'verified':True}
                g['listening_script']={'english':script,'chinese':'示例译文','source_pages':[],
                    'sentences':[{'id':gid+'-s001','text':script,'start_seconds':.1,'end_seconds':1.2}]}
            if part==7:g['passage_type']=category
            for qid in ids:
                q={'id':qid,'canonical_id':'bank:'+qid,'number':len(questions)+1,'part':part,
                    'section':g['section'],'group_id':gid,'stem':'Example question?',
                    'options':[{'id':o,'text':'Choice '+o} for o in ('ABC' if part==2 else 'ABCD')],
                    'answer':'A','explanation':{'text':'Answer explanation.','source_pages':[]},'source_pages':[]}
                questions.append(q)
            if part==6:g['materials']=[{'kind':'text','text':'Example blank {{qid:'+ids[0]+'}} ------.'}]
            groups.append(g)
    (root/'pool.json').write_text(json.dumps({'questions':questions,'groups':groups}),encoding='utf-8')
    (root/'manifest.json').write_text(json.dumps({'schema_version':2,'version':'synthetic-pool-v1','validated':True,
        'assets':[{'id':'clip','path':'clip.flac','media_type':'audio/flac','duration_seconds':2,
            'sha256':hashlib.sha256((root/'clip.flac').read_bytes()).hexdigest()}],'pool':{'path':'pool.json'}}),encoding='utf-8')
    return root


@pytest.fixture
def pool_client(pool_root,clock,store,tmp_path):
    app=create_app(clock=clock,store=store,library=Library(pool_root),backup_root=tmp_path/'backups',serve_web=False,allow_test_host=True)
    with TestClient(app) as client:yield client


def create(client,**over):
    body={'scope':'full','mode':'practice','timer':{'kind':'countdown','duration_seconds':7200},'random':{},'selection_preference':'random'}
    body.update(over)
    r=client.post('/api/attempts',json=body,headers=hdr())
    assert r.status_code==200,r.text
    return r.json()


def test_catalog_and_new_numbering_have_no_source_sets(pool_client):
    catalog=pool_client.get('/api/question-pool').json()
    assert catalog['ready'] and catalog['question_count']==400 and catalog['group_count']==206
    for part in catalog['parts']:
        assert len(part['group_sizes']) == part['group_count']
        assert sum(part['group_sizes']) == part['question_count']
    a=create(pool_client)
    assert [q['number'] for q in a['questions']]==list(range(1,201))
    assert len({q['id'] for q in a['questions']})==200
    assert [sum(q['part']==p for q in a['questions']) for p in range(1,8)]==[6,25,39,30,30,16,54]
    assert len(a['audio_queue'])==54
    assert not any('listening_script' in g for g in a['groups'])
    assert all('answer' not in q for q in a['questions'])
    assert all('{{qid:' not in m.get('text','') for g in a['groups'] for m in g['materials'])
    b=create(pool_client)
    assert [q['id'] for q in b['questions']] != [q['id'] for q in a['questions']]


def test_strict_fixed_phases_and_bank_solution_lock(pool_client,clock):
    a=start(pool_client,create(pool_client,mode='exam'))
    qid=a['questions'][0]['id']
    assert a['timing']['remaining_ms']==2700000
    assert not any('listening_script' in g for g in a['groups'])
    assert pool_client.get('/api/question-pool/questions/'+qid+'?include_solution=true').status_code==409
    first_deadline=a['timing']['deadline_at_ms']
    clock.advance(2700)
    reading=pool_client.get('/api/attempts/'+a['id']).json()
    assert reading['timing']['phase']=='reading' and reading['timing']['remaining_ms']==4500000
    assert reading['timing']['deadline_at_ms']==first_deadline+4500000
    clock.advance(4500)
    expired=pool_client.get('/api/attempts/'+a['id']).json()
    assert expired['status']=='expired'
    assert pool_client.get('/api/question-pool/questions/'+qid+'?include_solution=true').status_code==200


def test_exact_retake_does_not_redraw_or_change_old_report(pool_client):
    a=create(pool_client)
    report=pool_client.post('/api/attempts/'+a['id']+'/submit',json={},headers=hdr()).json()
    b=create(pool_client,retake_attempt_id=a['id'])
    assert a['id']!=b['id']
    assert [q['id'] for q in a['questions']]==[q['id'] for q in b['questions']]
    assert a['audio_queue']==b['audio_queue']
    assert report==pool_client.get('/api/attempts/'+a['id']+'/report').json()


def test_bank_status_priorities_and_optional_solution_are_read_only(pool_client):
    a=start(pool_client,create(pool_client,scope='part',random={'part_counts':{'5':1}}))
    qid=a['questions'][0]['id']
    assert answer(pool_client,a,qid,'B').status_code==200
    pool_client.post('/api/attempts/'+a['id']+'/submit',json={},headers=hdr())
    status=pool_client.get('/api/question-pool/status').json()
    assert (status['total'],status['answered'],status['wrong'],status['unanswered'])==(400,1,1,399)
    assert status['answered_percent']==status['wrong_percent']==0.25
    assert status['unanswered_percent']==99.75
    b=create(pool_client,scope='part',selection_preference='wrong_first',random={'part_counts':{'5':3}})
    assert qid in {q['id'] for q in b['questions']}
    c=create(pool_client,scope='part',selection_preference='unanswered_first',random={'part_counts':{'5':3}})
    assert qid not in {q['id'] for q in c['questions']}
    before=pool_client.get('/api/attempts').json()
    detail=pool_client.get('/api/question-pool/questions/'+qid).json()
    assert 'answer' not in detail['question'] and 'explanation' not in detail['question']
    full=pool_client.get('/api/question-pool/questions/'+qid+'?include_solution=true').json()
    assert full['question']['answer']=='A' and full['question']['explanation']['text']
    assert pool_client.get('/api/attempts').json()==before


def test_incomplete_group_and_unverified_pool_fail_closed(pool_root):
    content=json.loads((pool_root/'pool.json').read_text(encoding='utf-8'))
    content['groups'][0]['question_ids']*=2
    (pool_root/'pool.json').write_text(json.dumps(content),encoding='utf-8')
    library=Library(pool_root);library.load()
    assert not library.available


def test_part6_placeholders_resolve_in_bank_with_or_without_solution(pool_client):
    status=pool_client.get('/api/question-pool/status').json()
    q=next(q for q in status['questions'] if q['part']==6)
    for suffix in ['', '?include_solution=true']:
        detail=pool_client.get('/api/question-pool/questions/'+q['id']+suffix).json()
        assert '{{qid:' not in detail['group']['materials'][0]['text']
        assert f"({q['number']})" in detail['group']['materials'][0]['text']


def test_expired_answers_count_before_any_other_history_read(pool_client,clock):
    a=start(pool_client,create(pool_client,scope='part',timer={'kind':'countdown','duration_seconds':1},random={'part_counts':{'5':1}}))
    qid=a['questions'][0]['id'];answer(pool_client,a,qid,'B')
    clock.advance(2)
    status=pool_client.get('/api/question-pool/status').json()
    assert status['answered']==status['wrong']==1
    b=create(pool_client,scope='part',selection_preference='wrong_first',random={'part_counts':{'5':1}})
    assert b['questions'][0]['id']==qid


def test_frozen_retake_survives_current_key_and_group_boundary_changes(pool_client,pool_root):
    a=create(pool_client,scope='part',random={'part_counts':{'1':1}})
    pool_client.post('/api/attempts/'+a['id']+'/submit',json={},headers=hdr())
    content=json.loads((pool_root/'pool.json').read_text(encoding='utf-8'))
    q=next(q for q in content['questions'] if q['id']==a['questions'][0]['id']);q['answer']='B'
    g=next(g for g in content['groups'] if g['id']==q['group_id']);g['audio']['end_seconds']=1.5
    (pool_root/'pool.json').write_text(json.dumps(content),encoding='utf-8')
    pool_client.app.state.services.library.load()
    b=create(pool_client,retake_attempt_id=a['id'])
    running=start(pool_client,b)
    assert running['audio_queue']==a['audio_queue']
    report=pool_client.post('/api/attempts/'+b['id']+'/submit',json={},headers=hdr()).json()
    assert report['questions'][0]['answer']=='A'


@pytest.mark.parametrize('field', ['number','stem','canonical_id'])
def test_missing_required_pool_field_is_not_ready(pool_root,field):
    content=json.loads((pool_root/'pool.json').read_text(encoding='utf-8'))
    content['questions'][0].pop(field)
    (pool_root/'pool.json').write_text(json.dumps(content),encoding='utf-8')
    library=Library(pool_root);library.load()
    assert not library.available


def test_extreme_duration_rejected_before_persistence_and_details_no_store(pool_client):
    r=pool_client.post('/api/attempts',json={'scope':'part','mode':'practice','timer':{'kind':'countdown','duration_seconds':1e308},'random':{'part_counts':{'5':1}}},headers=hdr())
    assert r.status_code==400
    status=pool_client.get('/api/question-pool/status')
    assert status.headers.get('cache-control')=='no-store'
    qid=status.json()['questions'][0]['id']
    assert pool_client.get('/api/question-pool/questions/'+qid+'?include_solution=true').headers.get('cache-control')=='no-store'


@pytest.mark.parametrize('damage',['option_type','materials_type','audio_type','asset_bytes'])
def test_malformed_containers_and_changed_asset_are_not_ready(pool_root,damage):
    content=json.loads((pool_root/'pool.json').read_text(encoding='utf-8'))
    if damage=='option_type':content['questions'][0]['options']=[1,2,3,4]
    if damage=='materials_type':content['groups'][0]['materials']=['invalid']
    if damage=='audio_type':content['groups'][0]['audio']=None
    if damage=='asset_bytes':(pool_root/'clip.flac').write_bytes(b'changed')
    (pool_root/'pool.json').write_text(json.dumps(content),encoding='utf-8')
    library=Library(pool_root);library.load()
    assert not library.available
