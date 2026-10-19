// Wire types mirroring docs/api-contract.md v1 exactly. The backend is the
// source of truth; these types are the frontend's single translation target.

export type Section = 'listening' | 'reading';
export type Part = 1 | 2 | 3 | 4 | 5 | 6 | 7;

export interface ExamPartMeta {
  part: number;
  section: Section;
  count: number;
  ready: boolean;
  reason?: string;
}

export interface ExamMeta {
  id: string;
  title: string;
  version: string;
  question_count: number;
  parts: ExamPartMeta[];
  audio_duration_seconds: number;
  exam_audio_duration_seconds?: number;
  ready: boolean;
}

export interface ExamsResponse {
  library_version: string;
  exams: ExamMeta[];
}

export interface QuestionPoolPart {
  part: Part;
  question_count: number;
  group_count: number;
  group_sizes: number[];
  ready: boolean;
}

export interface QuestionPoolCatalog {
  library_version: string;
  question_count: number;
  group_count: number;
  ready: boolean;
  parts: QuestionPoolPart[];
  templates: {
    full: { part_counts: Record<string, number> };
    listening: { part_counts: Record<string, number> };
    reading: { part_counts: Record<string, number> };
  };
}

export type PoolQuestionStatus = 'answered' | 'unanswered' | 'wrong';

export interface QuestionPoolStatusQuestion {
  id: string;
  number: number;
  part: Part;
  group_id: string;
  status: PoolQuestionStatus;
  stem: string;
}

export interface QuestionPoolStatusResponse {
  library_version: string;
  total: number;
  answered: number;
  unanswered: number;
  wrong: number;
  answered_percent: number;
  unanswered_percent: number;
  wrong_percent: number;
  questions: QuestionPoolStatusQuestion[];
}

export interface QuestionPoolQuestionDetail {
  question: {
    id: string;
    number: number;
    part: Part;
    section: Section;
    group_id: string;
    stem: string;
    options: AttemptOption[];
    answer?: 'A' | 'B' | 'C' | 'D';
    explanation?: Explanation;
  };
  group: {
    id: string;
    part: Part;
    section: Section;
    question_ids: string[];
    materials: GroupMaterial[];
    source_pages?: number[];
    review_text?: string;
    listening_script?: ListeningScript;
    review_audio?: AudioQueueItem;
  };
  status: PoolQuestionStatus;
  solution_available: boolean;
};

export interface GroupMeta {
  id: string;
  part: number;
  section: Section;
  question_ids: string[];
  numbers: number[];
  ready: boolean;
  reason?: string;
}

export interface GroupsResponse {
  groups: GroupMeta[];
}

export type AttemptScope = 'full' | 'listening' | 'reading' | 'part' | 'custom';
export type AttemptMode = 'exam' | 'practice';
export type TimerKind = 'countdown' | 'countup' | 'none';
export type QuestionFilter = 'all' | 'unanswered' | 'wrong' | 'bookmarked';
export type SelectionPreference = 'unanswered_first' | 'wrong_first' | 'answered_first' | 'random';
export type AttemptStatus = 'ready' | 'running' | 'paused' | 'submitted' | 'expired';
export type TimingPhase = 'listening' | 'reading' | 'practice' | 'finished';
export type Integrity = 'valid' | 'interrupted';

export interface AttemptOption {
  id: 'A' | 'B' | 'C' | 'D';
  text: string;
}

export interface AttemptQuestion {
  id: string;
  canonical_id: string;
  number: number;
  part: number;
  section: Section;
  group_id: string;
  exam_id: string;
  stem: string;
  options: AttemptOption[];
  source_pages: number[];
}

export type MaterialKind = 'text' | 'image';

export interface GroupMaterial {
  kind: MaterialKind;
  text?: string;
  asset_id?: string;
  url?: string;
  alt?: string;
}

export interface SubtitleSentence {
  id: string;
  text: string;
  start_seconds: number;
  end_seconds: number;
}

export interface ListeningScript {
  english: string;
  chinese: string;
  source_pages: number[];
  sentences?: SubtitleSentence[];
}

export interface AttemptGroup {
  id: string;
  part: number;
  section: Section;
  exam_id: string;
  question_ids: string[];
  materials: GroupMaterial[];
  source_pages: number[];
  listening_script?: ListeningScript;
}

export interface AnswerState {
  option_id: 'A' | 'B' | 'C' | 'D' | null;
  flagged: boolean;
  visited: boolean;
  revision: number;
}

export interface AttemptTiming {
  kind: TimerKind;
  phase: TimingPhase;
  remaining_ms: number | null;
  elapsed_ms: number;
  server_time_ms: number;
  deadline_at_ms: number | null;
  can_pause: boolean;
  is_paused: boolean;
  integrity: Integrity;
  phase_question_ids: string[];
}

// Additive per-attempt timing configuration (Kimi). Optional until the backend
// ships it: lets preflight and a retake show the real budget instead of
// re-deriving one. Never used for clock math, which stays server-authoritative.
export interface TimerConfig {
  kind: TimerKind;
  duration_seconds?: number;
}

// Optional idempotency envelope for reliability/media interrupt reports, so a
// retried pending event is recorded once instead of duplicated.
export interface InterruptEvent {
  event_id: string;
  occurred_at_ms: number;
}

export interface AudioQueueItem {
  id: string;
  asset_id: string;
  url: string;
  start_seconds: number;
  end_seconds: number;
  part: number;
  exam_id: string;
  question_ids: string[];
  group_id?: string;
}

export interface MediaState {
  queue_index: number;
  position_seconds: number;
  playback_rate: number;
}

export interface Attempt {
  id: string;
  title: string;
  scope: AttemptScope;
  mode: AttemptMode;
  status: AttemptStatus;
  created_at: string;
  exam_ids: string[];
  parts: number[];
  question_count: number;
  current_index: number;
  questions: AttemptQuestion[];
  groups: AttemptGroup[];
  answers: Record<string, AnswerState>;
  timing: AttemptTiming;
  timer_config?: TimerConfig;
  audio_queue: AudioQueueItem[];
  audio_elapsed_ms: number;
  media_state?: MediaState;
  owner_tab_id: string | null;
  interruptions: unknown[];
}

export interface CreateAttemptRequest {
  exam_ids?: string[];
  scope: AttemptScope;
  parts?: number[];
  mode: AttemptMode;
  timer: { kind: TimerKind; duration_seconds?: number };
  question_filter?: QuestionFilter;
  selection_preference?: SelectionPreference;
  group_ids?: string[];
  random?: { part_counts?: Record<string, number> };
  retake_attempt_id?: string;
}

export interface AttemptSummary {
  id: string;
  title: string;
  scope: AttemptScope;
  mode: AttemptMode;
  status: AttemptStatus;
  created_at: string;
  question_count: number;
  answered_count: number;
  parts: number[];
  exam_ids: string[];
  summary?: {
    correct: number;
    wrong: number;
    unanswered: number;
    correct_percent: number;
  };
}

export interface AttemptsResponse {
  attempts: AttemptSummary[];
}

export interface ClockResponse {
  timing: AttemptTiming;
  audio_elapsed_ms: number;
  status: AttemptStatus;
  /**
   * Optional writer identity for cheap ownership sync. Optional until the
   * backend ships it; mirrors Attempt.owner_tab_id exactly when present.
   */
  owner_tab_id?: string | null;
}

export interface PartStat {
  part: number;
  total: number;
  correct: number;
  wrong: number;
  unanswered: number;
  correct_percent: number;
}

export interface ReportSummary {
  total: number;
  correct: number;
  wrong: number;
  unanswered: number;
  correct_percent: number;
  wrong_percent: number;
  unanswered_percent: number;
  answered_accuracy: number | null;
  by_part: PartStat[];
}

export type QuestionResult = 'correct' | 'wrong' | 'unanswered';

export interface Explanation {
  text: string;
  source_pages: number[];
}

// Structured erratum recorded by the dataset owner for known original-text
// numbering mistakes (e.g. TEST 05 Part 2 Q24-26 cyclic misnumbering).
// Report-only: shown as a plain note with the printed number and source page.
// It never reveals or implies an answer.
export interface SourceErratum {
  kind: string;
  printed_question_number?: number;
  actual_audio_question_number?: number;
  /** Bold-type misprint: the retained answer and the over-emphasized letter are
   *  intentionally never rendered, to avoid leaking the key. */
  retained_answer?: string;
  misprinted_bold?: string;
  source_pages?: number[];
  evidence?: string;
  summary?: string;
  audio_cue_start_seconds?: number;
}

export type ReviewCause =
  | 'meaning'
  | 'listening'
  | 'grammar'
  | 'paraphrase'
  | 'time'
  | 'careless'
  | 'material'
  | 'unknown';

export interface ReviewWord {
  term: string;
  sense: string;
  modality: 'meaning' | 'listening';
  causal: true;
}

export interface ReportQuestion {
  id: string;
  canonical_id: string;
  number: number;
  part: number;
  section: Section;
  group_id: string;
  exam_id: string;
  stem: string;
  options: AttemptOption[];
  source_pages: number[];
  selected_option_id: 'A' | 'B' | 'C' | 'D' | null;
  answer: 'A' | 'B' | 'C' | 'D';
  result: QuestionResult;
  explanation: Explanation;
  source_erratum?: SourceErratum;
  source_review_question_number?: number;
  review?: {
    causes: ReviewCause[];
    words: ReviewWord[];
  };
}

export interface ReportGroup extends AttemptGroup {
  review_text?: string;
  review_audio?: AudioQueueItem;
}

export interface AttemptReport {
  attempt: {
    id: string;
    title: string;
    scope: AttemptScope;
    mode: AttemptMode;
    parts: number[];
    exam_ids: string[];
    status: AttemptStatus;
    interruptions: unknown[];
    created_at?: string;
    closed_at?: string | null;
    /** Always present on the report envelope (apps/api attempts.py). */
    integrity?: Integrity;
    timer_config?: TimerConfig;
  };
  summary: ReportSummary;
  questions: ReportQuestion[];
  groups: ReportGroup[];
  reviews: Record<string, { causes: ReviewCause[]; words: ReviewWord[] }>;
}

export interface ReviewPayload {
  causes: ReviewCause[];
  words: ReviewWord[];
}

export interface Candidate {
  term: string;
  context: string;
  count: number;
}

export interface CandidatesResponse {
  candidates: Candidate[];
}

export type VocabStatus = 'candidate' | 'concentrated' | 'must_learn' | 'mastered';
export type VocabModality = 'meaning' | 'listening';

export interface VocabEvidence {
  attempt_id: string;
  question_id: string;
  exam_id: string;
  number: number;
  group_id: string;
  context: string;
}

export interface VocabEntry {
  id: string;
  term: string;
  sense: string;
  modality: VocabModality;
  status: VocabStatus;
  question_count: number;
  material_count: number;
  lifetime_question_count: number;
  threshold: number;
  manual_required: boolean;
  evidence: VocabEvidence[];
}

export interface VocabularyResponse {
  threshold: number;
  entries: VocabEntry[];
}

export interface SettingsResponse {
  vocabulary_threshold: number;
}

export interface StatisticsResponse {
  attempt_count: number;
  completed_count: number;
  by_part: PartStat[];
  first: AttemptSummary[];
  recent: AttemptSummary[];
}

export interface BackupMeta {
  id: string;
  created_at: string;
  size_bytes: number;
  includes_library: boolean;
}

export interface BackupsResponse {
  backups: BackupMeta[];
}

export interface CreateBackupResponse extends BackupMeta {
  download_url: string;
}

export interface ApiError {
  detail: string;
  code?: string;
}
