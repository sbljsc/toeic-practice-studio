// A single stable tab identity per browser tab session. Reload keeps it (that
// is the point); a second tab gets a different id and is read-only until an
// explicit takeover flips ownership server-side.
const STORAGE_KEY = 'toeic.tab-id';

function randomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `tab-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

export function getTabId(): string {
  try {
    const existing = window.sessionStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
    const fresh = randomId();
    window.sessionStorage.setItem(STORAGE_KEY, fresh);
    return fresh;
  } catch {
    // Private-mode / disabled storage still needs a per-load identity.
    return randomId();
  }
}
