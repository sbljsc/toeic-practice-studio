// The backend only accepts a review on a CLOSED, VALID, WRONG question:
//   PUT /attempts/{id}/reviews/{qid} -> closed wrong valid questions
// Offering the form for an unanswered or interrupted attempt produces a
// guaranteed rejection, so the UI must gate it identically.

export interface ReviewEligibilityInput {
  result: 'correct' | 'wrong' | 'unanswered';
  integrity: 'valid' | 'interrupted' | undefined;
  status: string;
}

export interface ReviewEligibility {
  allowed: boolean;
  reason: string | null;
}

export function reviewEligibility(input: ReviewEligibilityInput): ReviewEligibility {
  if (input.status !== 'submitted' && input.status !== 'expired') {
    return { allowed: false, reason: '本轮尚未结束，结束后才能记录错因。' };
  }
  if (input.integrity !== undefined && input.integrity !== 'valid') {
    return { allowed: false, reason: '本轮存在中断记录，成绩仅供参考，不记录错因与生词。' };
  }
  if (input.result === 'unanswered') {
    return { allowed: false, reason: '这题没有作答，不属于错题。' };
  }
  if (input.result === 'correct') {
    return { allowed: false, reason: null };
  }
  return { allowed: true, reason: null };
}
