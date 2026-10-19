export type TextLayout = {
  source: string;
  paragraphs: number[];
  hardBreaks: number[];
  headings: { line: number; endLine?: number; level: 3 | 4 }[];
};

type LayoutIndex = { exact: Map<string, TextLayout[]>; templates: { layout: TextLayout; pattern: RegExp; tokens: string[] }[] };
const indexes = new WeakMap<readonly TextLayout[], LayoutIndex>();
const normalize = (source: string) => source.replace(/\r\n?/g, '\n');
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function indexFor(layouts: readonly TextLayout[]): LayoutIndex {
  const cached = indexes.get(layouts);
  if (cached) return cached;
  const index: LayoutIndex = { exact: new Map(), templates: [] };
  for (const layout of layouts) {
    const source = normalize(layout.source);
    const entries = index.exact.get(source) ?? [];
    entries.push(layout); index.exact.set(source, entries);
    if (source.includes('{{qid:')) {
      const tokens: string[] = [];
      const pattern = source.split(/(\{\{qid:[^}]+\}\})/).map(piece => {
        if (!piece.startsWith('{{qid:')) return escape(piece);
        tokens.push(piece);
        return `(${escape(piece)}|\\([1-9][0-9]*\\))`;
      }).join('');
      index.templates.push({ layout, pattern: new RegExp(`^${pattern}$`), tokens });
    }
  }
  indexes.set(layouts, index); return index;
}

function renderLayout(source: string, layout: TextLayout): string | undefined {
  const lines = source.split('\n');
  const valid = (at: number) => Number.isInteger(at) && at >= 0 && at < lines.length;
  if (!layout.paragraphs.every(valid) || !layout.hardBreaks.every(valid) ||
      !layout.headings.every(h => valid(h.line) && valid(h.endLine ?? h.line) && (h.endLine ?? h.line) >= h.line && (h.level === 3 || h.level === 4) && lines[h.line].trim() &&
        !layout.hardBreaks.includes(h.line))) return undefined;
  const paragraphs = new Set(layout.paragraphs), hardBreaks = new Set(layout.hardBreaks);
  const headings = new Map<number, { level: number; endLine: number }>();
  const occupied = new Set<number>();
  for (const heading of layout.headings) {
    const endLine = heading.endLine ?? heading.line;
    for (let at = heading.line; at <= endLine; at++) { if (occupied.has(at)) return undefined; occupied.add(at); }
    headings.set(heading.line, { level: heading.level, endLine });
  }
  const output: string[] = [];
  for (let at = 0; at < lines.length; at++) {
    if (paragraphs.has(at) && output.length && output.at(-1)?.trim()) output.push('');
    const heading = headings.get(at);
    if (heading) {
      const text = lines.slice(at, heading.endLine + 1).map(line => line.trim()).join(' ')
        .replace(/(\p{Script=Han}) (?=\p{Script=Han})/gu, '$1');
      output.push(`${'#'.repeat(heading.level)} ${text}`);
      at = heading.endLine;
    } else output.push(lines[at].trimEnd() + (hardBreaks.has(at) ? '  ' : ''));
  }
  return output.join('\n');
}

/** Apply only a source-identified presentation, never a line-length guess.
 * Frozen Part 6 numbers may replace qid tokens only after an entire-template
 * match, keeping the snapshot's actual labels and all original words intact. */
export function applyTextLayout(source: string, layouts: readonly TextLayout[]): string | undefined {
  const normalized = normalize(source), index = indexFor(layouts);
  const candidates = [...(index.exact.get(normalized) ?? [])];
  if (!candidates.length) for (const template of index.templates) {
    const match = template.pattern.exec(normalized);
    if (!match) continue;
    const values = new Map<string, string>();
    let consistent = true;
    template.tokens.forEach((token, at) => {
      if (values.has(token) && values.get(token) !== match[at + 1]) consistent = false;
      values.set(token, match[at + 1]);
    });
    if (consistent) candidates.push(template.layout);
  }
  const results = new Set(candidates.map(layout => renderLayout(normalized, layout)).filter((value): value is string => value !== undefined));
  return results.size === 1 ? results.values().next().value : undefined;
}
