import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../../domain/http';
import { formatBytes, formatDateTime } from '../../domain/format';
import type { BackupMeta } from '../../domain/types';
import type { UpdateStatus } from '../../domain/types';
import { Banner, EmptyBlock, ErrorBlock, Loading, Tag } from '../components';

export function SettingsScreen() {
  const [threshold, setThreshold] = useState(3);
  const [savedThreshold, setSavedThreshold] = useState(3);
  const [backups, setBackups] = useState<BackupMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [includeLibrary, setIncludeLibrary] = useState(false);
  // Update state: what is available, and the downloaded package.
  const [update, setUpdate] = useState<UpdateStatus>({
    current_version: '',
    latest_version: null,
    update_available: false,
    checked: false,
    portable: false,
    error: null,
  });
  const [stagedArchive, setStagedArchive] = useState<string | null>(null);
  const [stagedBytes, setStagedBytes] = useState(0);
  const [pendingInstall, setPendingInstall] = useState(false);
  // In-page confirmation: a native window.confirm blocks the whole page and
  // cannot be driven or recovered by browser tooling.
  const [pendingRestore, setPendingRestore] = useState<BackupMeta | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([api.settings(), api.backups()])
      .then(([settings, backupList]) => {
        setThreshold(settings.vocabulary_threshold);
        setSavedThreshold(settings.vocabulary_threshold);
        setBackups(backupList.backups);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof ApiError ? cause.message : '读取设置失败。');
        setLoading(false);
      });
  }, []);

  useEffect(load, [load]);

  const checkUpdate = async () => {
    setBusy('check');
    setNotice(null);
    setError(null);
    try {
      setUpdate(await api.updateStatus());
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '检查更新失败。');
    } finally {
      setBusy(null);
    }
  };

  const downloadUpdate = async () => {
    setBusy('update');
    setNotice(null);
    setError(null);
    try {
      const staged = await api.stageUpdate();
      setStagedArchive(staged.archive ?? null);
      setStagedBytes(staged.bytes ?? 0);
      setUpdate((previous) => ({ ...previous, ...staged }));
      setNotice('更新包已下载并通过校验。');
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '下载更新失败。');
    } finally {
      setBusy(null);
    }
  };

  const installUpdate = async () => {
    if (!stagedArchive) return;
    setBusy('install');
    setError(null);
    try {
      await api.installUpdate(stagedArchive);
      setNotice('正在停止服务并安装更新，完成后会自动重新启动。');
      setPendingInstall(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '安装更新失败。');
    } finally {
      setBusy(null);
    }
  };

  const saveThreshold = async () => {
    setBusy('threshold');
    setNotice(null);
    try {
      const response = await api.patchSettings(threshold);
      setSavedThreshold(response.vocabulary_threshold);
      setThreshold(response.vocabulary_threshold);
      setNotice('阈值已保存。');
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '保存阈值失败。');
    } finally {
      setBusy(null);
    }
  };

  const createBackup = async () => {
    setBusy('backup');
    setNotice(null);
    setError(null);
    try {
      const created = await api.createBackup(includeLibrary);
      setBackups((prev) => [created, ...prev.filter((item) => item.id !== created.id)]);
      setNotice('备份已创建。');
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '创建备份失败。');
    } finally {
      setBusy(null);
    }
  };

  const restore = async (backup: BackupMeta) => {
    setBusy(backup.id);
    setNotice(null);
    setError(null);
    try {
      await api.restoreBackup(backup.id);
      setPendingRestore(null);
      setNotice('恢复完成，正在重新读取。');
      load();
    } catch (cause) {
      setPendingRestore(null);
      setError(cause instanceof ApiError ? cause.message : '恢复失败。');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="page page-settings" data-testid="settings-screen">
      <header className="page-head">
        <div>
          <p className="eyebrow">设置</p>
          <h1>本地设置与备份</h1>
          <p className="page-sub">仅影响本机学习数据。这里只备份你自己的练习记录。</p>
        </div>
      </header>

      {notice ? <Banner tone="success" title="已完成">{notice}</Banner> : null}
      {error ? <ErrorBlock message={error} /> : null}

      {loading ? <Loading label="正在读取设置…" /> : null}

      {!loading ? (
        <>
          <section className="settings-block" aria-labelledby="threshold-title">
            <h2 id="threshold-title">生词阈值</h2>
            <p className="settings-hint">
              经你确认因这个词答错，累计至少 {savedThreshold} 道不同题且涉及 2 份材料，才进入必背。
            </p>
            <div className="threshold-row">
              <label>
                <span className="sr-only">阈值</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={threshold}
                  onChange={(event) => setThreshold(Number(event.target.value) || 1)}
                  data-testid="threshold-input"
                />
              </label>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy === 'threshold' || threshold === savedThreshold}
                onClick={() => void saveThreshold()}
                data-testid="threshold-save"
              >
                保存
              </button>
            </div>
          </section>

          <section className="settings-block" aria-labelledby="update-title">
            <h2 id="update-title">检查更新</h2>
            <p className="settings-hint">
              便携版可从 GitHub 官方发行页获取新版本。你的学习数据保存在程序目录的
              <code>.data</code> 中，更新不会改动它。
            </p>
            {update.error ? <p className="settings-hint">{update.error}</p> : null}
            {update.checked && !update.update_available && update.latest_version ? (
              <p className="settings-hint" data-testid="update-current">
                已是最新版本（{update.current_version || '未知'}）。
              </p>
            ) : null}
            {update.update_available ? (
              <>
                <p data-testid="update-available">
                  发现新版本 {update.latest_version}（当前 {update.current_version || '未知'}）。
                </p>
                <div className="update-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy === 'update'}
                    onClick={() => void downloadUpdate()}
                    data-testid="update-download"
                  >
                    {busy === 'update' ? '下载中…' : '下载更新'}
                  </button>
                  {stagedArchive ? (
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={busy === 'install' || pendingInstall}
                      onClick={() => setPendingInstall(true)}
                      data-testid="update-install"
                    >
                      安装并重启
                    </button>
                  ) : null}
                </div>
                {stagedArchive ? (
                  <p className="settings-hint" data-testid="update-staged">
                    更新包已下载并通过校验（{formatBytes(stagedBytes)}）。
                  </p>
                ) : null}
              </>
            ) : null}
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy === 'check'}
              onClick={() => void checkUpdate()}
              data-testid="update-check"
            >
              {busy === 'check' ? '检查中…' : '检查更新'}
            </button>
          </section>

          <section className="settings-block" aria-labelledby="backup-title">
            <h2 id="backup-title">备份与恢复</h2>
            <p className="settings-hint">
              备份会保存成绩、错因与生词记录。勾选后同时包含内置题库（体积更大）。有正在计时的练习时不能恢复。
            </p>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={includeLibrary}
                onChange={(event) => setIncludeLibrary(event.target.checked)}
              />
              <span>同时包含内置题库</span>
            </label>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy === 'backup'}
              onClick={() => void createBackup()}
              data-testid="create-backup"
            >
              {busy === 'backup' ? '创建中…' : '创建备份'}
            </button>

            {backups.length === 0 ? (
              <EmptyBlock title="还没有备份" hint="建议在完成一轮练习后创建一次备份。" />
            ) : (
              <ul className="backup-list">
                {backups.map((backup) => (
                  <li key={backup.id} className="backup-row">
                    <div>
                      <strong>{formatDateTime(backup.created_at)}</strong>
                      <span>
                        {formatBytes(backup.size_bytes)} ·{' '}
                        {backup.includes_library ? <Tag tone="info">含题库</Tag> : <Tag tone="neutral">仅学习数据</Tag>}
                      </span>
                    </div>
                    <div className="backup-actions">
                      <a className="btn btn-secondary" href={`/api/backups/${backup.id}/download`} data-testid={`download-${backup.id}`}>
                        下载
                      </a>
                      <button
                        type="button"
                        className="btn btn-danger"
                        disabled={busy !== null}
                        onClick={() => setPendingRestore(backup)}
                        data-testid={`restore-${backup.id}`}
                      >
                        恢复
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}

      {pendingRestore ? (
        <div className="dialog-backdrop" onClick={() => setPendingRestore(null)}>
          <div
            className="confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="restore-dialog-title"
            aria-describedby="restore-dialog-body"
            data-testid="restore-dialog"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="restore-dialog-title">确认恢复这份备份？</h2>
            <div id="restore-dialog-body">
              <p>
                将用备份「{formatDateTime(pendingRestore.created_at)}」
                覆盖当前学习数据（{formatBytes(pendingRestore.size_bytes)}
                {pendingRestore.includes_library ? ' · 含内置题库' : ' · 仅学习数据'}）。
              </p>
              <p className="confirm-warn">
                有正在计时的练习时不能恢复。恢复后会回到这份备份的时间点，之后的学习记录将不再保留；如需找回，可再从恢复前自动生成的备份还原。
              </p>
            </div>
            <div className="confirm-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setPendingRestore(null)}
                data-testid="restore-cancel"
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={busy !== null}
                onClick={() => void restore(pendingRestore)}
                data-testid="restore-confirm"
              >
                {busy === pendingRestore.id ? '恢复中…' : '确认恢复'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {pendingInstall ? (
        <div className="dialog-backdrop" onClick={() => setPendingInstall(false)}>
          <div
            className="confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="update-dialog-title"
            aria-describedby="update-dialog-body"
            data-testid="update-dialog"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="update-dialog-title">确认安装更新？</h2>
            <div id="update-dialog-body">
              <p>
                将安装版本 {update.latest_version}。服务会先停止，
                替换程序文件后再自动重新启动，这个页面会断开一次。
              </p>
              <p className="confirm-warn">
                你的学习数据（程序目录中的 <code>.data</code>）不会被改动。
                如果更新失败，原来的程序文件仍然可用。
              </p>
            </div>
            <div className="confirm-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setPendingInstall(false)}
                data-testid="update-cancel"
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy !== null}
                onClick={() => void installUpdate()}
                data-testid="update-confirm"
              >
                {busy === 'install' ? '安装中…' : '确认安装'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
