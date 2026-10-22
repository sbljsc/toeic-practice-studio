import type { VocabReference } from '../../domain/types';

export interface LookupOutcome {
  exact: VocabReference | null;
  matches: VocabReference[];
}

/** The word to send to the API, or an empty string when nothing was typed. */
export function lookupQuery(input: string): string {
  return (input ?? '').trim();
}

/**
 * The API answers with an exact entry for a single word, and with matches
 * when the word is only a prefix. A phrase never resolves to one word, so
 * a phrase query always reads as a search.
 */
export function isPhraseQuery(query: string): boolean {
  return lookupQuery(query).split(/\s+/).filter(Boolean).length > 1;
}

/** Keep the exact entry first and drop any duplicate that also matched. */
export function orderLookup(outcome: LookupOutcome): LookupOutcome {
  const exact = outcome.exact ?? null;
  const matches = outcome.matches ?? [];
  if (!exact) {
    return { exact: null, matches };
  }
  const exactWord = exact.word.toLowerCase();
  return {
    exact,
    matches: matches.filter((match) => match.word.toLowerCase() !== exactWord),
  };
}

/** A short credit line for the reference material. */
export function referenceCredit(reference: VocabReference | null): string {
  if (!reference || !reference.license) {
    return '';
  }
  return `释义与例句来自 CC BY 4.0 词汇库`;
}

