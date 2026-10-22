import type {
  ActivityEvent,
  ActivitySummary,
  Attempt,
  AttemptReport,
  AttemptsResponse,
  BackupsResponse,
  CandidatesResponse,
  ClockResponse,
  CreateAttemptRequest,
  CreateBackupResponse,
  ExamsResponse,
  QuestionPoolCatalog,
  QuestionPoolStatusResponse,
  QuestionPoolQuestionDetail,
  GroupsResponse,
  InterruptEvent,
  ReviewPayload,
  SettingsResponse,
  UpdateStatus,
  StatisticsResponse,
  VocabularyResponse,
  VocabReferenceResponse,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;

  constructor(status: number, detail: string, code?: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }

  get isRevisionConflict(): boolean {
    return this.status === 409 && this.code === 'revision_conflict';
  }
}

type JsonBody = object;

function readTabId(): string | undefined {
  try {
    return window.sessionStorage.getItem('toeic.tab-id') ?? undefined;
  } catch {
    return undefined;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let detail = `请求失败（HTTP ${response.status}）`;
  let code: string | undefined;
  try {
    const payload = (await response.json()) as { detail?: unknown; code?: unknown };
    if (typeof payload?.detail === 'string') detail = payload.detail;
    if (typeof payload?.code === 'string') code = payload.code;
  } catch {
    // Non-JSON error bodies (proxy/HTML) keep the HTTP-status detail.
  }
  return new ApiError(response.status, detail, code);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const tabId = readTabId();
  // Never overwrite an explicitly supplied X-Tab-ID (e.g. an interruption
  // retry sent on behalf of the tab that originally observed the stall).
  if (tabId && !headers.has('X-Tab-ID')) headers.set('X-Tab-ID', tabId);
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers });
  } catch (error) {
    throw new ApiError(0, '无法连接本地服务。请确认服务仍在运行后重试。');
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function body(payload: JsonBody): string {
  return JSON.stringify(payload);
}

export const api = {
  activity: (id: string, payload: ActivityEvent) =>
    request<{ activity: ActivitySummary }>(`/attempts/${encodeURIComponent(id)}/activity`, {
      method: 'PUT', keepalive: true, signal: AbortSignal.timeout(10000), body: body(payload),
    }),
  questionPool: () => request<QuestionPoolCatalog>('/question-pool'),
  questionPoolStatus: () => request<QuestionPoolStatusResponse>('/question-pool/status'),
  questionPoolQuestion: (questionId: string, includeSolution = false) =>
    request<QuestionPoolQuestionDetail>(`/question-pool/questions/${encodeURIComponent(questionId)}?include_solution=${includeSolution}`),
  exams: () => request<ExamsResponse>('/exams'),
  groups: (examId: string) =>
    request<GroupsResponse>(`/exams/${encodeURIComponent(examId)}/groups`),

  listAttempts: () => request<AttemptsResponse>('/attempts'),
  getAttempt: (id: string) => request<Attempt>(`/attempts/${encodeURIComponent(id)}`),
  createAttempt: (payload: CreateAttemptRequest) =>
    request<Attempt>('/attempts', { method: 'POST', body: body(payload) }),
  claim: (id: string, takeover: boolean) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/claim`, {
      method: 'POST',
      body: body({ takeover }),
    }),
  start: (id: string, mediaReady: boolean) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/start`, {
      method: 'POST',
      body: body({ media_ready: mediaReady }),
    }),
  pause: (id: string) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/pause`, { method: 'POST' }),
  resume: (id: string) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/resume`, { method: 'POST' }),
  // Optional event envelope lets durable pending media events be retried
  // idempotently; the two-argument form stays compatible.
  interrupt: (
    id: string,
    reason: string,
    event?: InterruptEvent,
    ownerTabId?: string,
  ) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/interrupt`, {
      method: 'POST',
      // keepalive lets a pending event survive page unload during a retry.
      keepalive: true,
      ...(ownerTabId ? { headers: { 'X-Tab-ID': ownerTabId } } : {}),
      body: body(event ? { reason, ...event } : { reason }),
    }),
  continuePractice: (id: string) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/continue-practice`, {
      method: 'POST',
    }),
  clock: (id: string) => request<ClockResponse>(`/attempts/${encodeURIComponent(id)}/clock`),
  setPosition: (id: string, currentIndex: number) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/position`, {
      method: 'PATCH',
      body: body({ current_index: currentIndex }),
    }),
  mediaState: (id: string, payload: { queue_index: number; position_seconds: number; playback_rate: number }) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/media-state`, {
      method: 'PUT',
      body: body(payload),
    }),
  saveAnswer: (
    id: string,
    questionId: string,
    payload: {
      option_id: 'A' | 'B' | 'C' | 'D' | null;
      flagged?: boolean;
      visited?: boolean;
      revision: number;
      mutation_id: string;
    },
  ) =>
    request<Attempt>(`/attempts/${encodeURIComponent(id)}/answers/${encodeURIComponent(questionId)}`, {
      method: 'PUT',
      body: body(payload),
    }),
  submit: (id: string) =>
    request<AttemptReport>(`/attempts/${encodeURIComponent(id)}/submit`, { method: 'POST' }),
  report: (id: string) =>
    request<AttemptReport>(`/attempts/${encodeURIComponent(id)}/report`),
  saveReview: (attemptId: string, questionId: string, payload: ReviewPayload) =>
    request<AttemptReport>(`/attempts/${encodeURIComponent(attemptId)}/reviews/${encodeURIComponent(questionId)}`, {
      method: 'PUT',
      body: body(payload),
    }),
  candidates: (attemptId: string, questionId: string) =>
    request<CandidatesResponse>(
      `/attempts/${encodeURIComponent(attemptId)}/candidates/${encodeURIComponent(questionId)}`,
    ),

  vocabulary: () => request<VocabularyResponse>('/vocabulary'),
  vocabReference: (query: string, limit = 20) =>
    request<VocabReferenceResponse>(
      `/vocabulary/reference?q=${encodeURIComponent(query)}&limit=${limit}`,
    ),
  patchVocab: (id: string, payload: { mastered?: boolean; manual_required?: boolean }) =>
    request<VocabularyResponse>(`/vocabulary/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: body(payload),
    }),
  settings: () => request<SettingsResponse>('/settings'),
  patchSettings: (vocabularyThreshold: number) =>
    request<SettingsResponse>('/settings', {
      method: 'PATCH',
      body: body({ vocabulary_threshold: vocabularyThreshold }),
    }),
  statistics: () => request<StatisticsResponse>('/statistics'),
  updateStatus: () => request<UpdateStatus>('/update/status'),
  stageUpdate: () => request<UpdateStatus>('/update/stage', { method: 'POST', body: body({}) }),
  installUpdate: (archive: string) =>
    request<{ scheduled: boolean; log: string }>('/update/install', {
      method: 'POST',
      body: body({ archive }),
    }),

  backups: () => request<BackupsResponse>('/backups'),
  createBackup: (includeLibrary: boolean) =>
    request<CreateBackupResponse>('/backups', {
      method: 'POST',
      body: body({ include_library: includeLibrary }),
    }),
  restoreBackup: (id: string) =>
    request<unknown>(`/backups/${encodeURIComponent(id)}/restore`, {
      method: 'POST',
      body: body({ confirm: true }),
    }),
};
