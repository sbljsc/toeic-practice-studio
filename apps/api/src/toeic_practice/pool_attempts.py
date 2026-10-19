"""Random pool -> immutable attempt snapshots, using the existing exam engine."""
from copy import deepcopy
import random
import uuid

from . import timing
from .clock import now_iso
from .errors import bad_request, conflict
from .pool_library import positive_number
from .random_pool import draw_template

PREFERENCES = {'unanswered_first','wrong_first','answered_first','random'}


def pool_audio_item(group):
    audio = group['audio']
    return {'id':group['id']+'-audio','group_id':group['id'],'exam_id':'pool',
        'asset_id':audio['asset_id'],'url':f"/api/assets/{audio['asset_id']}",
        'start_seconds':audio['start_seconds'],'end_seconds':audio['end_seconds'],
        'part':group['part'],'question_ids':list(group['question_ids'])}


def create_pool_attempt(service, request):
    library = service.library
    if not library.available or 'pool' not in library.exams:
        raise conflict('独立题库尚未就绪。','library_unavailable')
    scope, mode = request.get('scope','full'), request.get('mode','practice')
    if scope not in {'full','listening','reading','part','custom'} or mode not in {'practice','exam'}:
        raise bad_request('练习范围或模式无效。','bad_scope')
    preference = request.get('selection_preference','unanswered_first')
    if preference not in PREFERENCES:
        raise bad_request('选题偏好无效。','bad_selection_preference')
    timer_req = request.get('timer') or {'kind':'none'}
    kind, duration = timer_req.get('kind','none'),timer_req.get('duration_seconds')
    if kind not in {'countdown','countup','none'}:
        raise bad_request('计时方式无效。','bad_timer')
    exam = library.exams['pool']
    retake_id = request.get('retake_attempt_id')
    if retake_id:
        with service.store.transaction() as conn:
            previous = service._load_record(conn,retake_id)
        if previous['status'] not in {'submitted','expired'}:
            raise conflict('本轮尚未结束，不能重练原题。','retake_not_closed')
        if set(previous['exam_ids']) != {'pool'}:
            raise conflict('旧来源题库的历史仍可复盘，不能混入新的随机题库。','retake_library_mismatch')
        scope = previous['scope']
        questions,groups,queue = [deepcopy(previous[k]) for k in ('questions','groups','audio_queue')]
    else:
        settings = request.get('random') or {}
        if not isinstance(settings,dict):
            raise bad_request('随机组卷参数无效。','bad_random_request')
        counts = settings.get('part_counts') or {}
        if not isinstance(counts,dict):
            raise bad_request('Part题量必须为对象。','bad_target_count')
        service.list()  # Preference must include answers just closed by a deadline.
        latest = service._latest_results('pool') if preference != 'random' else {}
        def preferred(q):
            result = latest.get(q['canonical_id'],{}).get('result')
            return ((preference == 'unanswered_first' and result is None)
                or (preference == 'wrong_first' and result == 'wrong')
                or (preference == 'answered_first' and result is not None))
        priorities = {g['id']:sum(preferred(q) for q in exam.questions if q['id'] in g['question_ids']) for g in exam.groups}
        rng = random.Random(uuid.uuid4().int)
        qmap = {q['id']:q for q in exam.questions}
        # Whole-group draws preserve the native audio. A fixed full/listening
        # exam may never cut formal speech just to force a 45-minute budget.
        for _ in range(40):
            drawn = draw_template(exam.groups,scope,counts,rng,priority_scores=priorities)
            queue = [pool_audio_item(g) for g in drawn if g['part'] <= 4]
            audio_seconds = sum(a['end_seconds']-a['start_seconds'] for a in queue)
            if mode != 'exam' or scope not in {'full','listening'} or audio_seconds <= 2700:
                break
        else:
            raise conflict('当前题库无法组成保留完整录音的45分钟听力卷，请调整题库或使用练习模式。','audio_budget_exceeded')
        questions,groups = [],[]
        for group in drawn:
            groups.append(service._public_group(exam,group))
            for qid in group['question_ids']:
                q = service._public_question(exam,qmap[qid])
                q['number'] = len(questions)+1
                questions.append(q)
        numbers = {q['id']:q['number'] for q in questions}
        for group in groups:
            # Only explicit builder tokens are changed. Literal dates, prices,
            # names and sentence-insertion [1]...[4] markers are untouched.
            for material in group['materials']:
                if material.get('text'):
                    for qid in group['question_ids']:
                        material['text'] = material['text'].replace('{{qid:'+qid+'}}',f'({numbers[qid]})')
    phases,first,phase_durations = ['practice'],'practice',{}
    if mode == 'exam' and scope in {'full','listening','reading'}:
        phases = ['listening','reading'] if scope == 'full' else [scope]
        first = phases[0]
        phase_durations = {p:2700.0 if p == 'listening' else 4500.0 for p in phases}
        if sum(a['end_seconds']-a['start_seconds'] for a in queue) > phase_durations.get('listening',float('inf')):
            raise conflict('原题录音超出听力时间预算，不能截断播放。','audio_budget_exceeded')
        kind,duration = 'countdown',sum(phase_durations.values())
    elif kind == 'countdown':
        if not positive_number(duration) or duration > 7*24*3600:
            raise bad_request('倒计时必须是7天以内的有效正数时长。','duration_required')
        phase_durations = {first:float(duration)}
    label = {'full':'完整随机卷','listening':'听力随机卷','reading':'阅读随机卷','part':'Part专项','custom':'自定义随机卷'}[scope]
    record = {'id':'att-'+uuid.uuid4().hex[:12], 'title':label+('（模拟）' if mode == 'exam' else '（练习）'),
        'scope':scope,'mode':mode,'original_mode':mode,'status':'ready','phase':first,'integrity':'valid',
        'created_at':now_iso(service.clock),'closed_at':None,'close_reason':None,'exam_ids':['pool'],
        'parts':sorted({q['part'] for q in questions}),'question_count':len(questions),'current_index':0,
        'timer':timing.make_timer(kind,duration,phases,phase_durations),'questions':questions,'groups':groups,
        'audio_queue':queue,'media_state':None,'owner_tab_id':None,'interruptions':[],
        'library_version':library.library_version(),
        'phase_question_ids':service._phase_question_ids(questions,first,phases,scope)}
    record['timer']['selection_preference'] = preference
    record['timer']['retake_snapshot'] = bool(retake_id)
    return service._persist_new(record)
