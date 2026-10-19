// Plain-Chinese notes for known original-text errata. Two shapes exist:
//   - cyclic numbering  -> states the printed number (mapping note)
//   - bold answer typo  -> states that the printed emphasis is wrong (type note)
// Neither note may reveal or imply an answer, so misprinted/retained letters and
// raw evidence strings are never surfaced.

import type { ReportQuestion } from '../../domain/types';

export interface ErratumNote {
  kind: 'numbering' | 'bold';
  printedNumber: number | null;
  sourcePages: number[];
  text: string;
}

const NUMBERING_KINDS = new Set([
  'answer-book-cyclic-content-numbering',
  'cyclic-content-numbering',
  'numbering',
]);

const BOLD_KINDS = new Set([
  'answer-book-bold-answer-typo',
  'bold-answer-typo',
  'bold-typo',
]);

function isNumbering(kind: string): boolean {
  return NUMBERING_KINDS.has(kind);
}

function isBold(kind: string): boolean {
  return BOLD_KINDS.has(kind);
}

function numberingNote(): ErratumNote {
  return { kind: 'numbering', printedNumber: null, sourcePages: [], text: '题目资料含编号校订，请按本轮题目顺序作答。' };
}

function boldNote(): ErratumNote {
  return {
    kind: 'bold',
    printedNumber: null,
    sourcePages: [],
    text: '题目资料含排版校订；请依据题意作答。',
  };
}

export function erratumNote(question: ReportQuestion): ErratumNote | null {
  const erratum = question.source_erratum;
  if (!erratum) return null;
  if (isNumbering(erratum.kind)) return numberingNote();
  if (isBold(erratum.kind)) return boldNote();
  // An unknown kind must not be shown with a possibly wrong explanation.
  return null;
}
