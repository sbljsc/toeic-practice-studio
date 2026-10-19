import { legacyMaterialRepairs } from './legacyMaterialRepairs.ts';

export type DisplayNumbers = Readonly<Record<string, number>>;

/** Only an individually verified, whole-source-matched legacy marker can be
 * rebound. The supplied stable-ID map must also agree with every frozen label.
 * This returns presentation text; no stored snapshot or answer is changed. */
export function repairLegacyMaterial(source: string, numbers: DisplayNumbers = {}): string {
  const normalized = source.replace(/\r\n?/g, '\n');
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const repair of legacyMaterialRepairs) {
    const number = numbers[repair.questionId];
    if (!Number.isInteger(number) || number < 1) continue;
    const tokens: string[] = [];
    const pieces = repair.source.split(/(\{\{qid:[^}]+\}\})/);
    if (repair.source.split(repair.legacyLabel).length !== 2) continue;
    const pattern = pieces.map(piece => {
      if (!piece.startsWith('{{qid:')) return escape(piece);
      tokens.push(piece.slice(6, -2));
      return `(${escape(piece)}|\\([1-9][0-9]*\\))`;
    }).join('');
    const match = new RegExp('^' + pattern + '$').exec(normalized);
    if (!match || !tokens.every((qid, index) => {
      const value = match[index + 1];
      return value.startsWith('{{qid:') || (Number.isInteger(numbers[qid]) && numbers[qid] === Number(value.slice(1, -1)));
    })) continue;
    // Reconstruct the verified template: captured labels must remain unchanged
    // even when another blank happens to display the same old number.
    let capture = 0;
    return pieces.map(piece => piece.startsWith('{{qid:') ? match[++capture] :
      piece.replace(repair.legacyLabel, `(${number})`)).join('');
  }
  return source;
}
