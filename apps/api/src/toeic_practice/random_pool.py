"""Count-exact, group-preserving random assembly; no source-set dependency."""
import random

from .errors import bad_request, conflict

PART_COUNTS = {1: 6, 2: 25, 3: 39, 4: 30, 5: 30, 6: 16, 7: 54}
TEMPLATES = {name: {p: n for p, n in PART_COUNTS.items() if p in parts}
             for name, parts in [('full', range(1, 8)), ('listening', range(1, 5)), ('reading', range(5, 8))]}


def choose_groups(groups, target, rng=None, *, group_count=None, priority_scores=None):
    rng = rng or random.SystemRandom()
    if type(target) is not int or not 1 <= target <= 2000:
        raise bad_request('目标题数必须是1至2000的整数。', 'bad_target_count')
    if group_count is not None and (type(group_count) is not int or not 1 <= group_count <= 2000):
        raise bad_request('材料数量无效。', 'bad_target_count')
    if len({g['id'] for g in groups}) != len(groups):
        raise conflict('题库存在重复材料编号。', 'duplicate_group')
    sizes = [len(g['question_ids']) for g in groups]
    scores = [int((priority_scores or {}).get(g['id'],0)) for g in groups]
    if not groups or any(n <= 0 for n in sizes) or sum(sizes) < target:
        raise conflict('符合筛选条件的完整题组不足，请减少题数或放宽筛选。', 'insufficient_pool')
    if len(set(sizes)) == 1:
        size = sizes[0]
        if target % size or (group_count is not None and target // size != group_count):
            raise conflict(f'所选题型每组{size}题，目标数量无法由完整题组组成。', 'impossible_group_count')
        ranked = list(zip(groups,scores))
        rng.shuffle(ranked)
        ranked.sort(key=lambda row:row[1],reverse=True)
        chosen = [g for g,_ in ranked[:target // size]]
        rng.shuffle(chosen)
        return chosen
    # Number of exact subsets per prefix. Backtracking uses those counts as
    # weights, so feasible subsets are sampled uniformly rather than taking a
    # shuffled prefix or retrying until an arbitrary greedy solution happens.
    counted = group_count is not None
    tables = [{(0, 0): (0,1)}]
    for size,score in zip(sizes,scores):
        prior = tables[-1]
        current = dict(prior)
        for (total, count), (best,ways) in prior.items():
            key = (total + size, count + 1 if counted else 0)
            if key[0] <= target and (not counted or key[1] <= group_count):
                old = current.get(key)
                candidate = best + score
                if old is None or candidate > old[0]:
                    current[key] = (candidate,ways)
                elif candidate == old[0]:
                    current[key] = (candidate,old[1]+ways)
        tables.append(current)
    state = (target, group_count if counted else 0)
    if state not in tables[-1]:
        raise conflict('目标题数无法由符合条件的完整题组组成，请调整题数。', 'impossible_group_count')
    selected = []
    for index in range(len(groups) - 1, -1, -1):
        prior = tables[index]
        best = tables[index+1][state][0]
        skip = prior.get(state)
        without = skip[1] if skip and skip[0] == best else 0
        include_state = (state[0] - sizes[index], state[1] - 1 if counted else 0)
        included = prior.get(include_state)
        take = included[1] if included and included[0]+scores[index] == best else 0
        if take and rng.randrange(without + take) < take:
            selected.append(groups[index])
            state = include_state
    assert state == (0, 0)
    rng.shuffle(selected)
    return selected


def draw_template(groups, scope, part_counts, rng=None, *, priority_scores=None):
    rng = rng or random.SystemRandom()
    template = TEMPLATES.get(scope)
    if template:
        if part_counts and part_counts != {str(p): n for p, n in template.items()}:
            raise bad_request('完整与分区模板的Part题量固定，请使用专项自定义题数。', 'fixed_template_counts')
        counts = template
    else:
        if not isinstance(part_counts, dict) or not part_counts:
            raise bad_request('请选择Part及目标题数。', 'part_counts_required')
        counts = {}
        for key, count in part_counts.items():
            if key not in {str(p) for p in PART_COUNTS} or type(count) is not int or not 1 <= count <= 2000:
                raise bad_request('Part与目标题数无效。', 'bad_target_count')
            counts[int(key)] = count
        if sum(counts.values()) > 2000:
            raise bad_request('单轮最多2000题。', 'bad_target_count')
    result = []
    for part, count in sorted(counts.items()):
        available = [g for g in groups if g['part'] == part]
        if part == 7 and template:
            selected = choose_groups([g for g in available if g.get('passage_type') == 'single'], 29, rng, group_count=10,priority_scores=priority_scores)
            selected += choose_groups([g for g in available if g.get('passage_type') == 'double'], 10, rng, group_count=2,priority_scores=priority_scores)
            selected += choose_groups([g for g in available if g.get('passage_type') == 'triple'], 15, rng, group_count=3,priority_scores=priority_scores)
        else:
            selected = choose_groups(available, count, rng,priority_scores=priority_scores)
        result.extend(selected)
    return result
