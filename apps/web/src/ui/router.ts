import { useCallback, useEffect, useState } from 'react';

export type Route =
  | { name: 'practice'; retake?: string }
  | { name: 'attempt'; id: string }
  | { name: 'report'; id: string; focusQuestionId?: string }
  | { name: 'history' }
  | { name: 'wrong' }
  | { name: 'pool'; questionId?: string }
  | { name: 'vocab' }
  | { name: 'settings' };

export const DEFAULT_ROUTE: Route = { name: 'practice' };

function parse(hash: string): Route {
  const clean = hash.replace(/^#\/?/, '');
  const [path, query] = clean.split('?');
  const [head, id] = path.split('/');
  const params = new URLSearchParams(query ?? '');
  switch (head) {
    case 'attempt':
      return id ? { name: 'attempt', id } : DEFAULT_ROUTE;
    case 'report':
      return id
        ? { name: 'report', id, focusQuestionId: params.get('question') ?? undefined }
        : DEFAULT_ROUTE;
    case 'history':
      return { name: 'history' };
    case 'wrong':
      return { name: 'wrong' };
    case 'pool':
      try { return { name: 'pool', questionId: id ? decodeURIComponent(id) : undefined }; }
      catch { return { name: 'pool', questionId: undefined }; }
    case 'vocab':
      return { name: 'vocab' };
    case 'settings':
      return { name: 'settings' };
    case 'practice':
    case '':
    case undefined: {
      const retake = params.get('retake');
      return retake ? { name: 'practice', retake } : { name: 'practice' };
    }
    default:
      return DEFAULT_ROUTE;
  }
}

export function routeToHash(route: Route): string {
  switch (route.name) {
    case 'attempt':
      return `#/attempt/${route.id}`;
    case 'report':
      return route.focusQuestionId
        ? `#/report/${route.id}?question=${encodeURIComponent(route.focusQuestionId)}`
        : `#/report/${route.id}`;
    case 'history':
      return '#/history';
    case 'wrong':
      return '#/wrong';
    case 'pool':
      return route.questionId ? `#/pool/${encodeURIComponent(route.questionId)}` : '#/pool';
    case 'vocab':
      return '#/vocab';
    case 'settings':
      return '#/settings';
    case 'practice':
    default:
      return route.name === 'practice' && route.retake ? `#/practice?retake=${route.retake}` : '#/practice';
  }
}

export function navigate(route: Route): void {
  window.location.hash = routeToHash(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  const sync = useCallback(() => setRoute(parse(window.location.hash)), []);
  useEffect(() => {
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, [sync]);
  return route;
}
