// Recovery drafts are durable only after the transaction completes. A late
// acknowledgment may delete only its own mutation, never a newer choice.
export interface PendingDraft {
  attemptId: string;
  questionId: string;
  mutationId: string;
  expectedRevision: number;
  optionId: 'A' | 'B' | 'C' | 'D' | null;
  flagged: boolean;
  visited: boolean;
  createdAt: number;
  attempts: number;
  lastError: string;
  tabId?: string;
}
const DB_NAME = 'toeic-practice';
const STORE = 'pending-answer-drafts';
let dbPromise: Promise<IDBDatabase> | null = null;
const keyOf = (attempt: string, question: string, tab?: string) =>
  [attempt, question, ...(tab ? [tab] : [])].join('::');

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE))
        request.result.createObjectStore(STORE, { keyPath: 'key' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => { dbPromise = null; reject(request.error); };
  });
  return dbPromise;
}
async function transaction<T>(mode: IDBTransactionMode,
  action: (store: IDBObjectStore, result: (value: T) => void) => void): Promise<T> {
  const db = await openDb();
  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    let value: T;
    tx.oncomplete = () => resolve(value);
    tx.onerror = () => reject(tx.error ?? new Error('无法保存本机草稿'));
    tx.onabort = () => reject(tx.error ?? new Error('草稿保存被中止'));
    try { action(tx.objectStore(STORE), (next) => { value = next; }); }
    catch (error) { tx.abort(); reject(error); }
  });
}
export async function saveDraft(draft: Omit<PendingDraft, 'attempts'>): Promise<void> {
  const key = keyOf(draft.attemptId, draft.questionId, draft.tabId);
  await transaction<void>('readwrite', (store, result) => {
    const get = store.get(key);
    get.onsuccess = () => {
      const previous = get.result as PendingDraft | undefined;
      // Saving is asynchronous; a slow older operation cannot replace a newer
      // choice or undo the revision from an acknowledged predecessor.
      if (!previous || (previous.createdAt <= draft.createdAt &&
          (previous.mutationId !== draft.mutationId ||
           previous.expectedRevision <= draft.expectedRevision))) {
        store.put({ ...draft, key, attempts: previous?.attempts ?? 0 });
      }
      result(undefined);
    };
  });
}
export async function readDraft(attempt: string, question: string, tab?: string): Promise<PendingDraft | null> {
  return transaction('readonly', (store, result) => {
    const request = store.get(keyOf(attempt, question, tab));
    request.onsuccess = () => result(request.result ?? null);
  });
}
export async function listDrafts(attempt: string, tab?: string): Promise<PendingDraft[]> {
  const all = await transaction<PendingDraft[]>('readonly', (store, result) => {
    const request = store.getAll();
    request.onsuccess = () => result(request.result);
  });
  return all.filter((draft) => draft.attemptId === attempt &&
    (tab === undefined || !draft.tabId || draft.tabId === tab));
}
export async function deleteDraft(attempt: string, question: string,
  mutationId?: string, tab?: string): Promise<void> {
  await transaction<void>('readwrite', (store, result) => {
    const key = keyOf(attempt, question, tab);
    const request = store.get(key);
    request.onsuccess = () => {
      if (request.result && (!mutationId || request.result.mutationId === mutationId)) store.delete(key);
      result(undefined);
    };
  });
}
export async function deleteDrafts(attempt: string): Promise<void> {
  for (const draft of await listDrafts(attempt))
    await deleteDraft(attempt, draft.questionId, draft.mutationId, draft.tabId);
}
