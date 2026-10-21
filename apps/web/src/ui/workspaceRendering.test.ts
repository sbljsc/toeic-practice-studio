import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer, type ViteDevServer } from 'vite';
import type { Attempt } from '../domain/types.ts';

let server: ViteDevServer;
let parts: Awaited<ReturnType<ViteDevServer['ssrLoadModule']>>;
let statistics: Awaited<ReturnType<ViteDevServer['ssrLoadModule']>>;
let transcript: Awaited<ReturnType<ViteDevServer['ssrLoadModule']>>;
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL('../../', import.meta.url)), configFile: false,
    server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true } });
  parts = await server.ssrLoadModule('/src/ui/attempt/parts.tsx');
  statistics = await server.ssrLoadModule('/src/ui/ActivityStatistics.tsx');
  transcript = await server.ssrLoadModule('/src/ui/TranscriptPanel.tsx');
});
after(async () => { await server?.close(); });

function fixture(): Attempt {
  return { id: 'a', scope: 'part', mode: 'practice', status: 'running', created_at: '2026-10-19',
    question_count: 1, questions: [{ id: 'q', group_id: 'g', part: 5, section: 'reading', stem: 'Question',
      options: ['A', 'B', 'C', 'D'].map((id) => ({ id, text: `Text ${id}` })) }],
    groups: [{ id: 'g', materials: [] }], answers: {},
    timing: { phase: 'practice', phase_question_ids: ['q'], is_paused: false, kind: 'none' },
  } as unknown as Attempt;
}
const answer = { option_id: 'B', flagged: false, visited: true, dirty: false };
function panel(value: Attempt) {
  return renderToStaticMarkup(createElement(parts.QuestionPanel, {
    attempt: value, question: value.questions[0], group: value.groups[0], answer,
    readOnly: value.status !== 'running', onSelect() {}, onFlag() {},
    solution: { answer: 'C', selected: 'B' },
  }));
}
test('live QuestionPanel refuses correctness decorations even if supplied a solution prop', () => {
  const html = panel(fixture());
  assert.doesNotMatch(html, /正确答案|你的选择|data-correct|data-wrong/);
  assert.match(html, /标记本题/); assert.doesNotMatch(html, /清空本题/);
});

test('a group renders its passage once with every question of that group below it', () => {
  const value = fixture();
  value.questions = [
    { ...value.questions[0], id: 'q1', group_id: 'g', stem: 'First question' },
    { ...value.questions[0], id: 'q2', group_id: 'g', stem: 'Second question' },
  ];
  value.groups = [{ id: 'g', materials: [{ kind: 'text', text: 'The shared passage.' }] }];
  const html = renderToStaticMarkup(createElement(parts.GroupPanel, {
    attempt: value,
    group: value.groups[0],
    questions: value.questions,
    answers: { q1: answer, q2: answer },
    currentQuestionId: 'q1',
    readOnly: false,
    onSelect() {},
    onFlag() {},
  }));
  // The passage appears once, not once per question.
  assert.equal(html.match(/The shared passage\./g)?.length, 1);
  assert.equal(html.match(/group-panel__question/g)?.length, 2);
  assert.match(html, /First question/);
  assert.match(html, /Second question/);
  assert.match(html, /第 1 题/);
  assert.match(html, /第 2 题/);
});

test('the group container owns the practice form and the current question', () => {
  const value = fixture();
  value.questions = [
    { ...value.questions[0], id: 'q1', group_id: 'g', stem: 'First question' },
    { ...value.questions[0], id: 'q2', group_id: 'g', stem: 'Second question' },
  ];
  value.groups = [{ id: 'g', materials: [] }];
  const html = renderToStaticMarkup(createElement(parts.GroupPanel, {
    attempt: value,
    group: value.groups[0],
    questions: value.questions,
    answers: { q1: answer, q2: answer },
    currentQuestionId: 'q2',
    readOnly: false,
    onSelect() {},
    onFlag() {},
  }));
  // Exactly one practice form: the group. Each question keeps its own block.
  assert.equal(html.match(/data-testid="practice-form"/g)?.length, 1);
  assert.match(html, /data-question-id="q2"/);
  assert.match(html, /data-testid="question-block-q1"/);
  assert.match(html, /data-testid="question-block-q2"/);
  // The current question is the one marked as current.
  assert.match(html, /data-testid="question-block-q2"[^>]*data-current="true"/);
  assert.match(html, /data-testid="question-block-q1"[^>]*data-current="false"/);
});

test('every question of a group answers and flags on its own', () => {
  const value = fixture();
  value.questions = [
    { ...value.questions[0], id: 'q1', group_id: 'g', stem: 'First question' },
    { ...value.questions[0], id: 'q2', group_id: 'g', stem: 'Second question' },
  ];
  value.groups = [{ id: 'g', materials: [] }];
  const html = renderToStaticMarkup(createElement(parts.GroupPanel, {
    attempt: value,
    group: value.groups[0],
    questions: value.questions,
    answers: { q1: answer, q2: answer },
    currentQuestionId: 'q1',
    readOnly: false,
    onSelect() {},
    onFlag() {},
  }));
  for (const id of ['q1', 'q2']) {
    for (const option of ['A', 'B', 'C', 'D']) {
      assert.match(html, new RegExp(`data-testid="option-${id}-${option}"`));
    }
    assert.match(html, new RegExp(`data-testid="question-block-${id}"`));
  }
  // Each question keeps its own flag button.
  assert.equal(html.match(/data-testid="flag-button"/g)?.length, 2);
});

test('a group with no passage renders its questions without a material box', () => {
  const value = fixture();
  value.questions = [
    { ...value.questions[0], id: 'q1', group_id: 'g', stem: 'First question' },
    { ...value.questions[0], id: 'q2', group_id: 'g', stem: 'Second question' },
  ];
  value.groups = [{ id: 'g', materials: [] }];
  const html = renderToStaticMarkup(createElement(parts.GroupPanel, {
    attempt: value,
    group: value.groups[0],
    questions: value.questions,
    answers: {},
    currentQuestionId: 'q1',
    readOnly: false,
    onSelect() {},
    onFlag() {},
  }));
  assert.doesNotMatch(html, /group-panel__material/);
  assert.match(html, /First question/);
  assert.match(html, /Second question/);
});

test('the scroll anchor of a question is stable and unique', () => {
  assert.equal(parts.questionBlockId('q-abc'), 'question-block-q-abc');
  assert.notEqual(parts.questionBlockId('q-abc'), parts.questionBlockId('q-abd'));
});

test('question stems and options share safe Markdown reflow inside their real controls', () => {
  const value = fixture();
  value.questions[0].stem = 'Which **service** will the company\nprovide?\n\nChoose one.';
  value.questions[0].options[0].text = 'A **new** service that will\nopen soon.';
  const html = panel(value);
  assert.match(html, /<p>Which <strong>service<\/strong> will the company provide\?<\/p><p>Choose one\.<\/p>/);
  assert.match(html, /class="markdown-inline option-text">A <strong>new<\/strong> service that will open soon\.<\/span>/);
  assert.doesNotMatch(html, /<span[^>]*option-text[^>]*>[^]*?<(?:p|table|div)\b/);
});

test('the displayed question number is a Markdown heading, separate from the immutable question identity', () => {
  const html = panel(fixture());
  assert.match(html, /<h3>第 1 题 · 阅读<\/h3>/);
  assert.match(html, /data-question-id="q"/);
});

test('fallback listening text gains paragraph reflow while Chinese stays hidden by default', () => {
  const html = renderToStaticMarkup(createElement(transcript.TranscriptPanel, { script: {
    english: 'M: Shall we meet at the\nstation?\nW: Yes, at noon.', chinese: '中文默认隐藏', sentences: [],
  } }));
  assert.match(html, /<p>M: Shall we meet at the station\?<\/p><p>W: Yes, at noon\.<\/p>/);
  assert.doesNotMatch(html, /中文默认隐藏|data-testid="chinese-subtitles"/);
});
test('closed review reuses disabled options with correct and selected labels', () => {
  const value = fixture(); value.status = 'submitted'; value.timing.phase = 'finished';
  const html = panel(value);
  assert.match(html, /正确答案/); assert.match(html, /你的选择/);
  assert.match(html, /data-correct="true"/); assert.match(html, /data-wrong="true"/);
  assert.equal((html.match(/role="radio"[^>]*disabled=""/g) ?? []).length, 4);
});
test('answer cards render one centered number per question and identify incorrect current cells', () => {
  const value = fixture(); value.status = 'submitted';
  const html = renderToStaticMarkup(createElement(parts.AnswerCard, { attempt: value,
    answers: { q: answer }, currentIndex: 0, onJump() {}, results: { q: 'wrong' } }));
  assert.equal((html.match(/class="cell-index"/g) ?? []).length, 1);
  assert.doesNotMatch(html, /class="cell-number"/);
  assert.match(html, /data-result="wrong"/); assert.match(html, /aria-current="step"/);
  assert.match(html, /第 1 题，已答，错误/);
});
test('header groups answer/statistics controls immediately before answered count', () => {
  const html = renderToStaticMarkup(createElement(parts.StickyHeader, { attempt: fixture(),
    clockDisplay: '00:10', saveBadge: { label: '已保存', tone: 'good' }, answered: 1,
    flagged: 0, view: 'answer', onView() {}, onExit() {}, onSubmit() {}, onTogglePause() {} }));
  assert.match(html, /data-testid="workspace-view-statistics"[^>]*>统计<\/button><\/div><span class="sticky-stat" data-testid="answered-count"/);
});
test('historical unavailable statistics render honest text without fabricated graph', () => {
  const html = renderToStaticMarkup(createElement(statistics.ActivityStatistics, { live: false }));
  assert.match(html, /没有逐题用时数据/); assert.doesNotMatch(html, /<svg/);
  assert.match(html, /网络异常时可能漏记或多记/);
});
