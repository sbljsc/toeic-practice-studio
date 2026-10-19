import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../domain/http';

export interface AsyncState<T> {
  state: 'loading' | 'ready' | 'error';
  data: T | null;
  error: string | null;
}

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ state: 'loading', data: null, error: null });
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let active = true;
    setState((prev) => ({ ...prev, state: 'loading', error: null }));
    loaderRef
      .current()
      .then((data) => active && setState({ state: 'ready', data, error: null }))
      .catch((error: unknown) =>
        active &&
        setState({
          state: 'error',
          data: null,
          error: error instanceof ApiError ? error.message : '加载失败。',
        }),
      );
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
