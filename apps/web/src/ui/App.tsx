import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../domain/http';
import type { AttemptStatus, AttemptScope, AttemptMode, AttemptSummary } from '../domain/types';
import { navigate, useRoute } from './router';
import { AttemptWorkspace } from './attempt/AttemptWorkspace';
import { InterruptionDelivery } from './attempt/interruptionDelivery';
import { PracticeHome, type AttemptSummaryView } from './screens/PracticeHome';
import { ReportScreen } from './screens/ReportScreen';
import { HistoryScreen } from './screens/HistoryScreen';
import { WrongScreen } from './screens/WrongScreen';
import { VocabScreen } from './screens/VocabScreen';
import { SettingsScreen } from './screens/SettingsScreen';
import { PoolScreen } from './screens/PoolScreen';

interface SummaryRow {
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
  summary?: { correct: number; wrong: number; unanswered: number; correct_percent: number };
}

const NAV = [
  { key: 'practice', label: '练习' },
  { key: 'history', label: '历史' },
  { key: 'wrong', label: '错题' },
  { key: 'pool', label: '题库' },
  { key: 'vocab', label: '生词' },
  { key: 'settings', label: '设置' },
] as const;

function App() {
  const route = useRoute();
  const [attempts, setAttempts] = useState<SummaryRow[]>([]);
  const [attemptsError, setAttemptsError] = useState<string | null>(null);

  const loadAttempts = useCallback(() => {
    setAttemptsError(null);
    api
      .listAttempts()
      .then((response) => setAttempts(response.attempts as SummaryRow[]))
      .catch((error: unknown) => setAttemptsError(error instanceof ApiError ? error.message : '历史读取失败。'));
  }, []);

  useEffect(loadAttempts, [loadAttempts]);

  const resumable = attempts.filter(
    (item) => item.status === 'ready' || item.status === 'running' || item.status === 'paused',
  ) as AttemptSummaryView[];

  // Returning home, finishing an attempt, or creating a new one must all
  // re-read the list, otherwise a just-submitted record still shows "继续作答".
  useEffect(() => {
    if (route.name === 'practice' || route.name === 'history') loadAttempts();
  }, [route.name, loadAttempts]);

  const openAttempt = useCallback((id: string) => navigate({ name: 'attempt', id }), []);
  const openReport = useCallback((id: string) => navigate({ name: 'report', id }), []);

  const inWorkspace = route.name === 'attempt';

  return (
    <div className="app" data-route={route.name}>
      <InterruptionDelivery />
      <header className="topbar">
        <a className="brand" href="#/practice" aria-label="TOEIC Practice Studio 练习首页">
          <span className="brand-mark" aria-hidden="true">
            T
          </span>
          <span>
            TOEIC <span className="brand-light">PRACTICE STUDIO</span>
          </span>
        </a>
        {!inWorkspace ? (
          <nav className="main-nav" aria-label="主导航">
            {NAV.map((item) => (
              <a
                key={item.key}
                href={`#/${item.key}`}
                className="nav-link"
                data-active={route.name === item.key || (item.key === 'history' && route.name === 'report')}
                aria-current={route.name === item.key ? 'page' : undefined}
                data-testid={`nav-${item.key}`}
              >
                {item.label}
              </a>
            ))}
          </nav>
        ) : null}
        <span className="local-badge">
          <span aria-hidden="true" className="local-dot" />
          本机运行 · 无需账户
        </span>
      </header>

      <div className={inWorkspace ? 'workspace-host' : 'page-host'}>
        {route.name === 'practice' ? (
          <PracticeHome
            resumable={resumable}
            onOpenAttempt={openAttempt}
            onStarted={openAttempt}
            onOpenHistory={() => navigate({ name: 'history' })}
            reloadResumable={loadAttempts}
          />
        ) : null}

        {route.name === 'attempt' ? (
          <AttemptWorkspace
            attemptId={route.id}
            onSubmitted={openReport}
            onExit={() => navigate({ name: 'practice' })}
          />
        ) : null}

        {route.name === 'report' ? (
          <ReportScreen
            attemptId={route.id}
            focusQuestionId={route.focusQuestionId}
            onBack={() => navigate({ name: 'practice' })}
            onRetake={() => navigate({ name: 'practice' })}
            onOpenAttempt={openAttempt}
          />
        ) : null}

        {route.name === 'history' ? (
          <HistoryScreen onOpenAttempt={openAttempt} onOpenReport={openReport} />
        ) : null}

        {route.name === 'wrong' ? <WrongScreen /> : null}

        {route.name === 'pool' ? <PoolScreen questionId={route.questionId} /> : null}

        {route.name === 'vocab' ? <VocabScreen /> : null}

        {route.name === 'settings' ? <SettingsScreen /> : null}

        {attemptsError && route.name !== 'attempt' ? (
          <p className="muted-note" role="status">
            {attemptsError}
          </p>
        ) : null}
      </div>

      {!inWorkspace ? (
        <footer className="app-footer">
          <span>TOEIC Practice Studio</span>
          <span>仅供个人学习使用 · 非商业用途</span>
        </footer>
      ) : null}
    </div>
  );
}

export type { AttemptSummary };
export default App;
