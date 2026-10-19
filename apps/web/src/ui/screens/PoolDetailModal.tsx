import { useEffect, useId, useRef, type ReactNode } from 'react';

/** Native modal supplies background inertness, focus containment and Escape. */
export function PoolDetailModal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const element = dialog.current!;
    element.showModal();
    return () => {
      element.close();
      if (opener?.isConnected && opener !== document.body) opener.focus();
      else document.querySelector<HTMLElement>('.pool-list-panel h2')?.focus();
    };
  }, []);
  return <dialog ref={dialog} className="pool-detail-modal" aria-labelledby={title}
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <div className="pool-modal-header"><h2 id={title}>题目详情</h2>
      <button type="button" className="btn btn-secondary" autoFocus onClick={onClose} aria-label="关闭题目详情">关闭 ×</button>
    </div>
    <div className="pool-modal-content">{children}</div>
  </dialog>;
}
