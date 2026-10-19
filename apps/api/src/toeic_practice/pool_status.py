"""Canonical question-bank browsing does not create attempts or score evidence."""
from copy import deepcopy

from .errors import conflict, not_found
from .pool_attempts import pool_audio_item


def current_status(service):
    library = service.library
    if not library.available or not library.pool_mode:
        raise conflict('独立题库尚未就绪。','library_unavailable')
    service.list()  # Close due attempts before deriving canonical question states.
    latest = service._latest_results('pool')
    questions = []
    for q in library.exams['pool'].questions:
        result = latest.get(q['canonical_id'],{}).get('result')
        status = 'unanswered' if result is None else 'wrong' if result == 'wrong' else 'answered'
        # Part1/2 text stays in the explicitly requested solution, never in the
        # catalog while a strict simulation is running in another tab.
        questions.append({'id':q['id'],'number':q['number'],'part':q['part'],'group_id':q['group_id'],
            'status':status,'stem':q.get('stem','') if q['part'] > 2 else ''})
    total = len(questions)
    unanswered = sum(q['status'] == 'unanswered' for q in questions)
    wrong = sum(q['status'] == 'wrong' for q in questions)
    answered = total-unanswered
    return {'library_version':library.library_version(),'total':total,'answered':answered,
        'unanswered':unanswered,'wrong':wrong,'answered_percent':round(answered*100/total,2) if total else 0,
        'unanswered_percent':round(unanswered*100/total,2) if total else 0,
        'wrong_percent':round(wrong*100/total,2) if total else 0,'questions':questions}


def question_detail(service,qid,include_solution=False):
    library = service.library
    status = current_status(service)
    active = bool(service.store.query("SELECT 1 FROM attempts WHERE mode='exam' AND status IN ('running','paused') LIMIT 1"))
    exam = library.exams['pool']
    q = next((q for q in exam.questions if q['id'] == qid),None)
    if q is None:
        raise not_found('题目不存在。','question_not_found')
    current = next(g for g in exam.groups if g['id'] == q['group_id'])
    # Advance lazy clocks before evaluating the global one-learner lock.
    if include_solution and active:
        raise conflict('模拟考试进行中，请交卷后查看完整题解。','solutions_locked')
    question = {k:deepcopy(q[k]) for k in ('id','number','part','section','group_id','stem','options') if k in q}
    group = {k:deepcopy(current[k]) for k in ('id','part','section','question_ids','materials') if k in current}
    group['source_pages'] = []
    question['source_pages'] = []
    if q['part'] in (1,2) and not include_solution:
        question['stem'] = ''
        question['options'] = [{'id':o['id'],'text':''} for o in q['options']]
    if include_solution:
        question['answer'] = q['answer']
        question['explanation'] = deepcopy(q.get('explanation'))
        group['review_text'] = current.get('review_text','')
        if q['part'] <= 4:
            group['listening_script'] = deepcopy(current['listening_script'])
            group['review_audio'] = pool_audio_item(current)
    numbers={old['id']:old['number'] for old in exam.questions}
    for material in group.get('materials',[]):
        if material.get('text'):
            for related in current['question_ids']:
                material['text']=material['text'].replace('{{qid:'+related+'}}',f'({numbers[related]})')
    for material in group.get('materials',[]):
        if material.get('asset_id'):
            material['url'] = '/api/assets/'+material['asset_id']
    return {'question':question,'group':group,'status':next(row['status'] for row in status['questions'] if row['id']==qid),
        'solution_available':not active}
