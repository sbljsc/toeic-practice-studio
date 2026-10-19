import type { ReactNode } from 'react';

export function Banner({
  tone,
  title,
  children,
  action,
}: {
  tone: 'warn' | 'error' | 'info' | 'success';
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="banner" data-tone={tone} role={tone === 'error' ? 'alert' : 'status'}>
      <div className="banner-text">
        <strong>{title}</strong>
        {children ? <span>{children}</span> : null}
      </div>
      {action ? <div className="banner-action">{action}</div> : null}
    </div>
  );
}

export function Loading({ label = '正在读取…' }: { label?: string }) {
  return (
    <div className="state-block" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state-block state-error" role="alert">
      <strong>无法完成请求</strong>
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}

export function EmptyBlock({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="state-block">
      <strong>{title}</strong>
      {hint ? <span>{hint}</span> : null}
    </div>
  );
}

export function Tag({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'good' | 'warn' | 'bad' | 'info';
}) {
  return (
    <span className="tag" data-tone={tone}>
      {children}
    </span>
  );
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint ? <p className="field-hint">{hint}</p> : null}
    </div>
  );
}

export function Stat({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {note ? <span className="stat-note">{note}</span> : null}
    </div>
  );
}
