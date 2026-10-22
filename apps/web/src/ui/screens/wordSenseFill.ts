import type { Candidate, VocabReference } from '../../domain/types';

/** The open word list's entry for a term, when it knows the word.
 *
 * A candidate comes with its reference attached. A word the learner typed by
 * hand is not a candidate, so its reference is looked up separately and kept
 * in `lookup`.
 */
export function referenceFor(
  term: string,
  candidates: Candidate[],
  lookup: VocabReference | null,
): VocabReference | null {
  const key = (term ?? '').trim().toLowerCase();
  if (!key) return null;
  const candidate = candidates.find((item) => item.term.toLowerCase() === key);
  if (candidate?.reference) return candidate.reference;
  return lookup && lookup.word.toLowerCase() === key ? lookup : null;
}

/** The text the fill button puts into the sense field. */
export function senseFromReference(entry: VocabReference | null): string {
  if (!entry) return '';
  return (entry.definition_simplified || entry.definition || '').trim();
}

/** Whether a word still needs the word list's meaning. */
export function needsSenseFill(sense: string, entry: VocabReference | null): boolean {
  if (!entry) return false;
  if ((sense ?? '').trim()) return false;
  return senseFromReference(entry).length > 0;
}

