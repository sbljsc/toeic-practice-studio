"""Validated flat pool adapter; public data contains no source-set registry."""
import json
import math
import hashlib

from .random_pool import TEMPLATES
from .subtitle_cues import valid_sentences


def positive_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def load_pool(library):
    from .library import Exam
    try:
        root = library.root.resolve()
        entry = library.manifest['pool']
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('题库路径超出目录')
        content = json.loads(path.read_text(encoding='utf-8'))
        questions, groups = content['questions'], content['groups']
        if (not isinstance(questions,list) or not isinstance(groups,list)
                or not all(isinstance(row,dict) for row in questions+groups)
                or not questions or not groups or library.manifest.get('validated') is not True):
            raise ValueError('题库尚未通过校验')
        library.assets = {}
        registrations=library.manifest.get('assets',[])
        if not isinstance(registrations,list) or not all(isinstance(a,dict) for a in registrations):
            raise ValueError('资产登记格式无效')
        for asset in registrations:
            if not isinstance(asset.get('id'), str) or asset['id'] in library.assets:
                raise ValueError('资产编号无效或重复')
            library.assets[asset['id']] = asset
            asset_path,_=library.asset_path(asset['id'])
            expected=asset.get('sha256')
            if not isinstance(expected,str) or len(expected)!=64:
                raise ValueError('缺少资产校验和')
            with asset_path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:
                    raise ValueError('资产校验和不一致')
        qmap, gmap, canonical = {}, {}, set()
        numbers=set()
        for q in questions:
            part = q['part']
            options = q['options']
            if (type(part) is not int or part not in range(1,8)
                or type(q['number']) is not int or q['number'] < 1 or q['number'] in numbers
                or any(not isinstance(q[k],str) or not q[k] for k in ('id','canonical_id','group_id','section'))
                or not isinstance(q['stem'],str)
                or not isinstance(options,list) or any(not isinstance(o,dict) or not isinstance(o.get('text'),str) for o in options)
                or q['id'] in qmap or q['canonical_id'] in canonical
                or q['section'] != ('listening' if part <= 4 else 'reading')
                or [o['id'] for o in options] != list('ABC' if part == 2 else 'ABCD')
                or q['answer'] not in [o['id'] for o in options]):
                raise ValueError('题目编号、题型或答案无效')
            qmap[q['id']] = q
            canonical.add(q['canonical_id'])
            numbers.add(q['number'])
            if not isinstance(q.get('explanation'),dict) or not isinstance(q['explanation'].get('text'),str):
                raise ValueError('缺少可显示的题解')
        seen = set()
        for group in groups:
            ids, part = group['question_ids'], group['part']
            if (not isinstance(ids,list) or not isinstance(group['id'],str)
                    or group['id'] in gmap or not ids or len(set(ids)) != len(ids)
                    or any(qid in seen or qid not in qmap for qid in ids)):
                raise ValueError('材料编号或所属题目无效')
            if (type(part) is not int or part not in range(1,8)
                    or any(qmap[qid]['group_id'] != group['id'] or qmap[qid]['part'] != part for qid in ids)
                    or group['section'] != ('listening' if part <= 4 else 'reading')):
                raise ValueError('题目与材料关系无效')
            expected = {1:1,2:1,3:3,4:3,5:1,6:4}.get(part)
            if expected and len(ids) != expected:
                raise ValueError('共享材料题量不符合题型')
            if part == 7 and (group.get('passage_type') not in ('single','double','triple')
                    or len(ids) not in ([2,3,4] if group['passage_type'] == 'single' else [5])):
                raise ValueError('阅读材料类型或题量无效')
            materials=group.get('materials',[])
            if not isinstance(materials,list) or not all(isinstance(m,dict) for m in materials):
                raise ValueError('材料格式无效')
            for material in materials:
                if material.get('kind') not in ('text','image'):
                    raise ValueError('材料类型无效')
                if material['kind']=='text' and not isinstance(material.get('text'),str):
                    raise ValueError('材料文字无效')
                if material.get('asset_id'):
                    library.asset_path(material['asset_id'])
            if part <= 4:
                audio = group['audio']
                if (not isinstance(audio,dict) or audio.get('verified') is not True or type(audio.get('start_seconds')) not in (int,float)
                        or audio['start_seconds'] != 0 or not positive_number(audio.get('end_seconds'))):
                    raise ValueError('听力片段尚未通过校验')
                library.asset_path(audio['asset_id'])
                duration=library.assets[audio['asset_id']].get('duration_seconds')
                if not positive_number(duration) or audio['end_seconds']>duration:
                    raise ValueError('音频边界超出资产登记时长')
                script = group.get('listening_script')
                if (not isinstance(script,dict) or not isinstance(script.get('english'),str)
                        or not isinstance(script.get('chinese'),str) or not isinstance(script.get('source_pages'),list)
                        or not valid_sentences(script.get('sentences'),script,group,audio)):
                    raise ValueError('逐句字幕与音频边界不一致')
            gmap[group['id']] = group
            seen.update(ids)
        if seen != set(qmap):
            raise ValueError('存在无所属材料的题目')
        library.pool_mode = True
        library.exams = {'pool': Exam(id='pool',title='随机题库',version=library.manifest_version,
            question_count=len(questions),validated=True,questions=questions,groups=groups,cues_verified=True)}
        library.sources = {}
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as error:
        library.exams = {}
        library.load_error = f'独立题库无法加载：{error}'


def catalog(library):
    questions = [q for e in library.exams.values() for q in e.questions]
    groups = [g for e in library.exams.values() for g in e.groups]
    return {'library_version':library.library_version(), 'question_count':len(questions),
        'group_count':len(groups),'ready':bool(library.available and questions and groups),
        'parts':[{'part':p,'question_count':sum(q['part']==p for q in questions),
            'group_count':sum(g['part']==p for g in groups),
            'group_sizes':sorted(len(g['question_ids']) for g in groups if g['part']==p),
            'ready':any(g['part']==p for g in groups)} for p in range(1,8)],
        'templates':{key:{'part_counts':{str(p):n for p,n in counts.items()}} for key,counts in TEMPLATES.items()}}


def validate_pool_selected(library, questions, groups, audio_queue, *, frozen=False):
    from .errors import conflict
    from .pool_attempts import pool_audio_item
    if frozen:
        return validate_frozen_pool(library,questions,groups,audio_queue)
    exam = library.exams['pool']
    qmap = {q['id']:q for q in exam.questions}
    gmap = {g['id']:g for g in exam.groups}
    selected = {q['id'] for q in questions}
    if len(selected) != len(questions) or len({g['id'] for g in groups}) != len(groups):
        raise conflict('当前练习出现重复题目或材料。','content_not_ready')
    expected_ids, expected_audio = set(),[]
    for group in groups:
        current = gmap.get(group['id'])
        if not current or group['question_ids'] != current['question_ids']:
            raise conflict('所选材料已变更，请重新组卷。','content_not_ready')
        expected_ids.update(current['question_ids'])
        if current['part'] <= 4:
            expected_audio.append(pool_audio_item(current))
    if selected != expected_ids or expected_audio != audio_queue:
        raise conflict('所选材料或音频队列不完整，请重新组卷。','content_not_ready')
    for q in questions:
        current = qmap.get(q['id'])
        if not current or current['canonical_id'] != q['canonical_id'] or current['answer'] != q['_answer']:
            raise conflict('所选题目或答案已变更，请重新组卷。','content_not_ready')


def validate_frozen_pool(library,questions,groups,audio_queue):
    """Replay immutable content when its original registered assets still exist.

    Current answers/group cuts may have changed; they must not replace frozen
    keys/cuts. Reusing an asset ID for other bytes fails rather than substituting
    the current media into a historical snapshot.
    """
    from .errors import conflict
    try:
        qmap={q['id']:q for q in questions}
        assert len(qmap)==len(questions)
        covered,expected_audio=set(),[]
        for group in groups:
            ids=group['question_ids']
            assert not covered.intersection(ids) and ids
            assert all(qid in qmap and qmap[qid]['group_id']==group['id'] for qid in ids)
            for material in group.get('materials',[]):
                if material.get('asset_id'):library.asset_path(material['asset_id'])
            covered.update(ids)
            if group['part']>4:continue
            item=group['_review_audio'];original=group['_audio_asset']
            current=library.assets[item['asset_id']]
            library.asset_path(item['asset_id'])
            assert original['id']==item['asset_id']
            assert original.get('sha256')==current.get('sha256')
            duration=current.get('duration_seconds')
            assert positive_number(duration) and 0<=item['start_seconds']<item['end_seconds']<=duration
            script=group['_listening_script']
            assert valid_sentences(script['sentences'],script,group,item)
            expected_audio.append(item)
        assert covered==set(qmap) and expected_audio==audio_queue
        for q in questions:
            assert q['_answer'] in [o['id'] for o in q['options']]
    except (KeyError,TypeError,ValueError,AssertionError,OSError):
        raise conflict('原题快照所需素材缺失或身份已变更，无法安全重练；原报告仍保留。','content_not_ready')
