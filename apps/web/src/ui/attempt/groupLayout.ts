// Group-level layout for the practice workspace.
//
// One TOEIC group is one shared passage (reading) or one recording
// (listening). Its questions belong together on one page, so the workspace
// renders the whole group instead of repeating the passage for every
// question.
//
// These helpers are pure: no React, no DOM. The global index into
// `attempt.questions` stays the single source of truth for "where am I",
// and every helper maps between that index and the group it belongs to.

import type { Attempt, AttemptGroup, AttemptQuestion } from '../../domain/types';

export interface GroupPlacement {
  /** The group that owns the current question. */
  group: AttemptGroup;
  /** Global index of the current question inside `attempt.questions`. */
  index: number;
  /** Position of the current question inside its group, starting at 0. */
  indexInGroup: number;
  /** The group's questions, in the order they are answered. */
  questions: AttemptQuestion[];
}

export interface GroupView {
  group: AttemptGroup;
  questions: AttemptQuestion[];
  /** Global index of the group's first question. */
  startIndex: number;
}

function groupOrder(attempt: Pick<Attempt, 'groups'>): AttemptGroup[] {
  return attempt.groups ?? [];
}

/**
 * The group's questions, taken from the attempt's own question order so the
 * on-screen order always matches the numbering the learner sees.
 */
export function groupQuestions(
  attempt: Pick<Attempt, 'questions' | 'groups'>,
  group: AttemptGroup,
): AttemptQuestion[] {
  const ids = new Set(group.question_ids ?? []);
  const ordered = attempt.questions.filter((question) => ids.has(question.id));
  if (ordered.length === ids.size) return ordered;
  // A frozen snapshot may carry a question id the live list no longer has.
  // Keep the group order rather than dropping the shared passage silently.
  const byId = new Map(attempt.questions.map((question) => [question.id, question]));
  const fallback = (group.question_ids ?? [])
    .map((id) => byId.get(id))
    .filter((question): question is AttemptQuestion => question !== undefined);
  return fallback.length ? fallback : ordered;
}

/** Locate the group that owns `questionId`. */
export function groupOfQuestion(
  attempt: Pick<Attempt, 'questions' | 'groups'>,
  questionId: string,
): GroupPlacement | undefined {
  const index = attempt.questions.findIndex((question) => question.id === questionId);
  if (index < 0) return undefined;
  const question = attempt.questions[index];
  const group = groupOrder(attempt).find((item) => item.id === question.group_id) ??
    groupOrder(attempt).find((item) => (item.question_ids ?? []).includes(questionId));
  if (!group) return undefined;
  const questions = groupQuestions(attempt, group);
  const indexInGroup = Math.max(0, questions.findIndex((item) => item.id === questionId));
  return { group, index, indexInGroup, questions };
}

/** The group that owns the question at the global index `currentIndex`. */
export function groupAtIndex(
  attempt: Pick<Attempt, 'questions' | 'groups'>,
  currentIndex: number,
): GroupPlacement | undefined {
  const question = attempt.questions[currentIndex];
  if (!question) return undefined;
  return groupOfQuestion(attempt, question.id);
}

/** Every group of the attempt, each with its questions and its first index. */
export function visibleGroups(attempt: Pick<Attempt, 'questions' | 'groups'>): GroupView[] {
  const views: GroupView[] = [];
  for (const group of groupOrder(attempt)) {
    const questions = groupQuestions(attempt, group);
    if (!questions.length) continue;
    const startIndex = attempt.questions.findIndex((question) => question.id === questions[0].id);
    views.push({ group, questions, startIndex: startIndex < 0 ? 0 : startIndex });
  }
  return views;
}

function groupIndexOf(attempt: Pick<Attempt, 'questions' | 'groups'>, currentIndex: number): number {
  const views = visibleGroups(attempt);
  const question = attempt.questions[currentIndex];
  if (!question) return -1;
  const found = views.findIndex((view) => view.questions.some((item) => item.id === question.id));
  return found;
}

/** The global index of the first question of the next group, or null. */
export function nextGroupIndex(
  attempt: Pick<Attempt, 'questions' | 'groups'>,
  currentIndex: number,
): number | null {
  const views = visibleGroups(attempt);
  const at = groupIndexOf(attempt, currentIndex);
  if (at < 0 || at + 1 >= views.length) return null;
  return views[at + 1].startIndex;
}

/** The global index of the first question of the previous group, or null. */
export function prevGroupIndex(
  attempt: Pick<Attempt, 'questions' | 'groups'>,
  currentIndex: number,
): number | null {
  const views = visibleGroups(attempt);
  const at = groupIndexOf(attempt, currentIndex);
  if (at <= 0) return null;
  return views[at - 1].startIndex;
}

