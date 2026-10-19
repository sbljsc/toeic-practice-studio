export type WorkspaceView = 'answer' | 'statistics';

export function WorkspaceViewToggle({ view, onChange }: { view: WorkspaceView; onChange: (view: WorkspaceView) => void }) {
  return <div className="workspace-view-toggle" role="group" aria-label="工作区视图">
    {(['answer', 'statistics'] as const).map((item) => <button key={item} type="button"
      aria-pressed={view === item} data-active={view === item} onClick={() => onChange(item)}
      data-testid={`workspace-view-${item}`}>{item === 'answer' ? '答题' : '统计'}</button>)}
  </div>;
}
