import random

import pytest

from toeic_practice.random_pool import choose_groups, draw_template
from toeic_practice.errors import ApiError


def group(i, part, size, passage_type=None):
    return {"id": f"g{i}", "part": part, "question_ids": [f"q{i}-{j}" for j in range(size)],
            "passage_type": passage_type}


def test_exact_sum_keeps_shared_groups_and_does_not_repeat():
    pool = [group(i, 7, size) for i, size in enumerate([2, 2, 3, 3, 4, 5])]
    draws = [choose_groups(pool, 9, random.Random(seed)) for seed in range(24)]
    assert all(sum(len(g['question_ids']) for g in d) == 9 for d in draws)
    assert all(len({g['id'] for g in d}) == len(d) for d in draws)
    assert len({tuple(g['id'] for g in d) for d in draws}) > 8


def test_impossible_target_does_not_silently_split_a_group():
    with pytest.raises(ApiError):
        choose_groups([group(i, 3, 3) for i in range(8)], 5, random.Random(1))


def test_exact_group_count_and_seed_reproducibility():
    pool = [group(i, 7, 2 + i % 3) for i in range(30)]
    a = choose_groups(pool, 29, random.Random(42), group_count=10)
    assert len(a) == 10 and sum(len(g['question_ids']) for g in a) == 29
    assert a == choose_groups(pool, 29, random.Random(42), group_count=10)


def test_preference_maximizes_eligible_questions_then_fills_without_repeating():
    pool = [group(i,5,1) for i in range(12)]
    draw = choose_groups(pool,8,random.Random(6),priority_scores={'g0':1,'g1':1})
    assert {'g0','g1'} <= {g['id'] for g in draw}
    assert len(draw) == len({g['id'] for g in draw}) == 8


def test_preference_respects_exact_sum_instead_of_greedy_material_choice():
    pool=[group(0,7,4),group(1,7,2),group(2,7,3),group(3,7,3)]
    draw=choose_groups(pool,6,random.Random(2),priority_scores={'g0':4,'g1':1,'g2':2,'g3':2})
    assert {g['id'] for g in draw} == {'g0','g1'}


def test_standard_template_retains_part7_single_double_triple_structure():
    groups = []
    for part, size, count in [(1, 1, 20), (2, 1, 60), (3, 3, 30), (4, 3, 25), (5, 1, 60), (6, 4, 12)]:
        groups += [group(f'{part}-{i}', part, size) for i in range(count)]
    groups += [group(f's{i}', 7, 2 + i % 3, 'single') for i in range(50)]
    groups += [group(f'd{i}', 7, 5, 'double') for i in range(12)]
    groups += [group(f't{i}', 7, 5, 'triple') for i in range(12)]
    draw = draw_template(groups, 'full', {}, random.Random(16))
    assert [sum(len(g['question_ids']) for g in draw if g['part'] == p) for p in range(1, 8)] == [6,25,39,30,30,16,54]
    part7 = [g for g in draw if g['part'] == 7]
    assert [sum(g['passage_type'] == t for g in part7) for t in ['single','double','triple']] == [10,2,3]
    assert len({g['id'] for g in draw}) == len(draw)


@pytest.mark.parametrize('target', [True, -1, 0, 1.5, 10**200])
def test_invalid_or_unbounded_target_rejected(target):
    with pytest.raises(ApiError):
        choose_groups([group(i, 5, 1) for i in range(10)], target, random.Random(1))
