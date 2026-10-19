import { materialTranscripts } from './materialTranscripts.ts';

/** Deliberately small Markdown grammar: no HTML, links, code or embedded media. */
export type MaterialBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'list'; ordered: boolean; start: number; items: string[] }
  | { kind: 'table'; header: string[]; rows: string[][]; align: ('left' | 'center' | 'right')[] };

export type MaterialInline = { kind: 'text'; text: string }
  | { kind: 'strong' | 'em'; children: MaterialInline[] };

export function tableCells(line: string): string[] {
  let value = line.trim();
  if (value.startsWith('|')) value = value.slice(1);
  if (value.endsWith('|') && !value.endsWith('\\|')) value = value.slice(0, -1);
  return value.split(/(?<!\\)\|/).map(cell => cell.trim());
}

function tableAt(lines: string[], at: number): Extract<MaterialBlock, { kind: 'table' }> | null {
  if (!lines[at]?.includes('|') || !lines[at + 1]?.includes('|')) return null;
  const header = tableCells(lines[at]);
  const divider = tableCells(lines[at + 1]);
  if (header.length !== divider.length || !divider.every(cell => /^:?-{3,}:?$/.test(cell))) return null;
  const rows: string[][] = [];
  for (let i = at + 2; i < lines.length && lines[i].trim() && lines[i].includes('|'); i++) {
    const row = tableCells(lines[i]);
    // Reject the whole table rather than silently dropping or moving a cell.
    if (row.length !== header.length) return null;
    rows.push(row);
  }
  return { kind: 'table', header, rows, align: divider.map(cell =>
    cell.endsWith(':') ? (cell.startsWith(':') ? 'center' : 'right') : 'left') };
}

const heading = /^(#{1,6})\s+(.+)$/;
const bullet = /^\s*(?:([-+*])\s+|(\d+)[.)]\s+)(.+)$/;

export function parseMaterialMarkdown(source: string): MaterialBlock[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: MaterialBlock[] = [];
  let at = 0;
  while (at < lines.length) {
    const line = lines[at];
    if (!line.trim()) { at++; continue; }
    const table = tableAt(lines, at);
    if (table) { blocks.push(table); at += 2 + table.rows.length; continue; }
    const title = heading.exec(line);
    if (title) { blocks.push({ kind: 'heading', level: title[1].length, text: title[2] }); at++; continue; }
    const item = bullet.exec(line);
    if (item) {
      const ordered = !!item[2];
      const items: string[] = [];
      const start = ordered ? Number(item[2]) : 1;
      while (at < lines.length) {
        const next = bullet.exec(lines[at]);
        if (!next && items.length && /^\s{2,}\S/.test(lines[at])) {
          items[items.length - 1] += '\n' + lines[at++].trimStart(); continue;
        }
        if (!next || !!next[2] !== ordered) break;
        items.push(next[3]); at++;
      }
      blocks.push({ kind: 'list', ordered, start, items }); continue;
    }
    const prose = [line]; at++;
    while (at < lines.length && lines[at].trim() && !heading.test(lines[at]) && !bullet.test(lines[at]) && !tableAt(lines, at)) {
      prose.push(lines[at++]);
    }
    blocks.push({ kind: 'paragraph', text: prose.join('\n') });
  }
  return blocks;
}

/** Escapes and unmatched markers stay readable; every leaf is a React text node. */
export function parseMaterialInline(source: string, depth = 0): MaterialInline[] {
  const result: MaterialInline[] = [];
  let plain = '';
  function flush() { if (plain) { result.push({ kind: 'text', text: plain }); plain = ''; } }
  for (let at = 0; at < source.length;) {
    if (source[at] === '\\' && /[\\*_|]/.test(source[at + 1] ?? '')) {
      plain += source[at + 1]; at += 2; continue;
    }
    const marker = /^(\*\*\*|___|\*\*|__|\*|_)/.exec(source.slice(at))?.[0];
    if (marker && depth < 24 && /\S/.test(source[at + marker.length] ?? '') &&
        !(marker.includes('_') && /[\p{L}\p{N}]/u.test(source[at - 1] ?? ''))) {
      let end = source.indexOf(marker, at + marker.length);
      while (end >= 0 && (source[end - 1] === '\\' || /\s/.test(source[end - 1]))) end = source.indexOf(marker, end + marker.length);
      if (end > at + marker.length) {
        flush();
        const children = parseMaterialInline(source.slice(at + marker.length, end), depth + 1);
        result.push(marker.length === 3 ? { kind: 'strong', children: [{ kind: 'em', children }] }
          : { kind: marker.length === 2 ? 'strong' : 'em', children });
        at = end + marker.length; continue;
      }
    }
    plain += source[at++];
  }
  flush(); return result;
}

/** Only the application's registered, same-origin media endpoint can load pixels. */
export function materialImageUrl(url: string | undefined): string | undefined {
  return url && /^\/api\/assets\/[a-zA-Z0-9_-]+$/.test(url) ? url : undefined;
}

/** Only reviewed asset IDs gain text. Match the entire frozen source template
 * before reusing its displayed Part 6 numbers; never infer labels from order. */
export function verifiedMaterialTranscript(material: { asset_id?: string; text?: string }): string | undefined {
  const id = material.asset_id;
  if (!id || !Object.hasOwn(materialTranscripts, id)) return undefined;
  const verified = materialTranscripts[id];
  if (!verified.sourceText) return verified.markdown;
  if (!material.text) return undefined;
  const tokens: string[] = [];
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = verified.sourceText.split(/(\{\{qid:[^}]+\}\})/).map(piece => {
    if (!piece.startsWith('{{qid:')) return escape(piece);
    tokens.push(piece);
    return `(${escape(piece)}|\\([1-9][0-9]*\\))`;
  }).join('');
  const match = new RegExp('^' + pattern + '$').exec(material.text);
  if (!match) return undefined;
  const labels = new Map(tokens.map((token, index) => [token, match[index + 1]]));
  return verified.markdown.replace(/\{\{qid:[^}]+\}\}/g, token => labels.get(token) ?? token);
}
