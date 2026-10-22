import { useCallback, useState } from 'react';
import { api } from '../domain/http';
import { updateBadge, updateErrorText, useUpdateIndicator } from './updateIndicator';

export function UpdateIndicator() {
  const { state, check, startDownload } = useUpdateIndicator(true);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const badge = state ? updateBadge(state) : null;

  const onClick = useCallback(async () => {
    if (!state) return;
    setError(null);
    if (state.phase === 'ready') {
      setConfirming(true);
      return;
    }
    if (state.phase === 'available') {
      await startDownload();
      return;
    }
    if (state.phase === 'error') {
      await check();
    }
  }, [state, startDownload, check]);

  const install = useCallback(async () => {
    if (!state?.archive) return;
    setError(null);
    try {
      await api.installUpdate(state.archive);
      setConfirming(false);
    } catch (cause) {
      setError(updateErrorText(cause));
    }
  }, [state?.archive]);

  // The hook must run on every render, so the empty case is handled here
  // rather than by returning early.
  if (!badge || !badge.label) return null;

  return (
    <>
      <button
        type="button"
        className="update-badge"
        data-tone={badge.tone}
        data-phase={state?.phase}
        onClick={() => void onClick()}
        disabled={!badge.clickable}
        data-testid="update-badge"
        title={
          state?.latest_version && state.phase === 'available'
            ? `新版本 ${state.latest_version}`
            : undefined
        }
      >
        {badge.percent !== null && state?.phase === 'downloading' ? (
          <span className="update-badge-bar" style={{ width: `${badge.percent}%` }} />
        ) : null}
        <span className="update-badge-label">{badge.label}</span>
      </button>

      {confirming ? (
        <div className="dialog-backdrop" onClick={() => setConfirming(false)}>
          <div
            className="confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="update-reboot-title"
            aria-describedby="update-reboot-body"
            data-testid="update-reboot-dialog"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="update-reboot-title">确认重启并安装更新？</h2>
            <div id="update-reboot-body">
              <p>
                新版本 {state?.latest_version} 已下载并通过校验。确认后服务会停止，
                替换程序文件并自动重新启动，这个页面会断开一次。
              </p>
              <p className="confirm-warn">
                你的学习数据（程序目录中的 .data）不会被改动。更新失败时原程序仍然可用。
              </p>
              {error ? <p className="confirm-warn">{error}</p> : null}
            </div>
            <div className="confirm-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirming(false)}
                data-testid="update-reboot-cancel"
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void install()}
                data-testid="update-reboot-confirm"
              >
                确认重启
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}