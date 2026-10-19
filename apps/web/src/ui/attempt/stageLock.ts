// Which questions are editable right now. The backend is the authority, but the
// UI must not invert the rule: listening questions ARE answerable while the
// listening phase runs, and lock only once the exam moves into reading.

export interface StageLockInput {
  questionPart: number;
  questionId: string;
  section: 'listening' | 'reading';
  phase: 'listening' | 'reading' | 'practice' | 'finished';
  /** Question ids the server says belong to the current phase. */
  phaseQuestionIds: string[];
  status: 'ready' | 'running' | 'paused' | 'submitted' | 'expired';
  isPaused: boolean;
  mode: 'exam' | 'practice';
}

export interface StageLock {
  editable: boolean;
  reason: string | null;
}

const LISTENING_LAST_PART = 4;

export function stageLock(input: StageLockInput): StageLock {
  if (input.status === 'submitted' || input.status === 'expired' || input.phase === 'finished') {
    return { editable: false, reason: '本轮已结束，答案为只读记录。' };
  }
  if (input.status === 'ready') {
    return { editable: false, reason: '尚未开始，本轮还不能作答。' };
  }
  if (input.isPaused || input.status === 'paused') {
    return { editable: false, reason: '已暂停，继续后即可作答。' };
  }

  // Practice keeps its own selected scope fully editable while running.
  if (input.mode === 'practice' || input.phase === 'practice') {
    return { editable: true, reason: null };
  }

  const isListeningQuestion = input.questionPart <= LISTENING_LAST_PART || input.section === 'listening';

  if (input.phase === 'listening') {
    // Listening answers are collected live; they lock when reading begins.
    return isListeningQuestion
      ? { editable: true, reason: null }
      : { editable: false, reason: '阅读题在听力阶段不能作答，听力结束后开放。' };
  }

  // Reading phase: listening answers are locked, reading answers are open.
  return isListeningQuestion
    ? { editable: false, reason: '听力阶段已结束，听力答案已锁定。' }
    : { editable: true, reason: null };
}

export function isCurrentPhaseQuestion(input: { phaseQuestionIds: string[]; questionId: string }): boolean {
  if (input.phaseQuestionIds.length === 0) return true;
  return input.phaseQuestionIds.includes(input.questionId);
}
