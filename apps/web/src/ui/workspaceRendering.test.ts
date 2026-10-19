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
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL('../../', import.meta.url)), configFile: false,
    server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true } });
  parts = await server.ssrLoadModule('/src/ui/attempt/parts.tsx');
  statistics = await server.ssrLoadModule('/src/ui/ActivityStatistics.tsx');
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
