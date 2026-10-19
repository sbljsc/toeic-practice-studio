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

export type MaterialFlow = 'document' | 'prose';
const han = /\p{Script=Han}/u;
const mailField = /^(?:From|To|Cc|Bcc|Sent|Date|Subject|Re|E-?mail|Tel|Phone|Fax|收件人|发件人|主题|日期)\s*[:：]/i;
const speaker = /^(?:M\d?|W\d?|Man|Woman|Q|A)\s*[:：](?:\s|$)|^[MW]\d?$/i;
const chat = /^.{1,60}\[\d{1,2}:\d{2}\s*(?:[AP]\.?M\.?)?\]$/i;
const choice = /^[（(][A-D][）)](?:\s|[^a-z]|$)/i;
const salutation = /^(?:Dear\b.+[,，:]|尊敬的.+[：:]|您好[！!：:]?)$/i;
const closing = /^(?:Best regards|Kind regards|Regards|Sincerely(?: yours)?|Yours (?:truly|sincerely|faithfully)|Thank you|Thanks)[,!，！]?$/i;
const annotation = /^(?:[▶→➤]|[·•]\s*[A-Za-z])/;
const sentenceEnd = /[.!?。！？][”’"'）)]?$/;
const short = (line: string) => Array.from(line).reduce((n, ch) => n + (han.test(ch) ? 2 : 1), 0) < 60;
const hardBreak = (line: string) => / {2,}$/.test(line) || /(?<!\\)(?:\\\\)*\\$/.test(line);
const trimLine = (line: string) => line.replace(/ {2,}$|(?<!\\)(?:\\\\)*\\$/, match => match.startsWith(' ') ? '' : match.slice(0, -1)).trim();

/** A source newline is a Markdown soft break, unless explicitly marked hard.
 * Joining only whitespace retains every word, number, hyphen and blank label. */
export function reflowSoftLines(source: string): string {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  let result = trimLine(lines[0] ?? '');
  for (let i = 1; i < lines.length; i++) {
    const next = trimLine(lines[i]);
    if (!next) continue;
    const last = result.at(-1) ?? '', first = next[0];
    const gap = hardBreak(lines[i - 1]) ? '\n' : /^[（(][A-D][）)]$/.test(lines[i - 1].trim()) && /^[a-z]/i.test(first) ? ' ' :
      !last || han.test(last) || han.test(first) || /[-‐‑([{“‘（【「『《，。！？；：、）】》」』]/.test(last) || /[,.;:!?%)}\]”’，。！？；：、）》」』】]/.test(first) ? '' : ' ';
    result += gap + next;
  }
  return result;
}

/** Legacy extracts have no blank lines around many genuine document fields.
 * Recognize those visible boundaries, rather than treating every PDF row as a
 * paragraph. This is display-only; frozen source and answer data stay intact. */
function documentParagraphs(lines: string[], flow: MaterialFlow): string[] {
  if (flow === 'prose') return [reflowSoftLines(lines.join('\n'))];
  // Malformed tables must remain literal, including every row/cell.
  if (lines.filter(line => line.includes('|')).length >= 2) return [lines.join('\n')];
  const paragraphs: string[] = [];
  let current: string[] = [];
  let signature = false;
  const flush = () => { if (current.length) paragraphs.push(reflowSoftLines(current.join('\n'))); current = []; signature = false; };
  const title = (line: string) => short(line) && !sentenceEnd.test(line) &&
    /^(?:[A-Z0-9][\w&’'.,()-]*)(?:[ \t]+(?:[A-Z0-9][\w&’'.,()-]*|for|of|the|and|to|in|a|&))*$/.test(line) &&
    (line.includes(' ') || /^[A-Z\d&]{2,}$/.test(line));
  const address = (line: string) => short(line) &&
    (/^\d+[A-Za-z]?(?:F,)?\s+/.test(line) || /,\s*[A-Z][a-zA-Z ]+\s+\d{4,6}$/.test(line) || /^Attention:/i.test(line) || /\b(?:Inc|Ltd|Co|Corp)\.$/.test(line));
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i], line = raw.trim(), previous = lines[i - 1]?.trim() ?? '';
    if (/^[_=-]{3,}$/.test(line)) { flush(); paragraphs.push(line); continue; }
    if (mailField.test(line)) {
      flush(); const fields = [raw];
      while (i + 1 < lines.length && mailField.test(lines[i + 1].trim())) fields.push(lines[++i]);
      paragraphs.push(fields.map(trimLine).join('\n')); continue;
    }
    if (salutation.test(line)) { flush(); paragraphs.push(line); continue; }
    if (closing.test(line)) { flush(); signature = true; current.push(raw); continue; }
    if (signature) { current[current.length - 1] += '  '; current.push(raw); continue; }
    if (chat.test(line)) {
      flush(); current.push(line + '  '); continue;
    }
    if (speaker.test(line) || choice.test(line) || annotation.test(line) || /^来自\S/.test(line)) flush();
    if (/^[▶→➤]\s*解析\s*$/.test(line)) { paragraphs.push(line.replace(/^([▶→➤])\s*/, '$1 ')); continue; }
    // A block of short title/address lines is layout, not wrapped running prose.
    const chineseTitle = i === 0 && /^[\p{Script=Han}·]{2,16}$/u.test(line) && (lines[i + 1]?.match(/\p{Script=Han}/gu)?.length ?? 0) >= 20;
    if (!current.length && (title(line) || address(line) || chineseTitle) && !speaker.test(line) && !choice.test(line)) {
      const fields = [raw];
      while (i + 1 < lines.length && !salutation.test(lines[i + 1].trim()) && !closing.test(lines[i + 1].trim()) &&
          (title(lines[i + 1].trim()) || address(lines[i + 1].trim()))) fields.push(lines[++i]);
      paragraphs.push(fields.map(trimLine).join('\n').replace(/\b(and|or|of|the|to|&)\n/g, '$1 ')); continue;
    }
    if (current.length && !hardBreak(lines[i - 1]) && !chat.test(previous) &&
        ((short(previous) && sentenceEnd.test(previous) && /^(?:[A-Z“‘"'\p{Script=Han}]|[（(][A-D][）)])/u.test(line)) ||
          (sentenceEnd.test(previous) && !han.test(previous) && /^\p{Script=Han}/u.test(line)) ||
          (choice.test(current[0].trim()) && /[a-z]{3}/i.test(previous.replace(/^[（(][A-D][）)]/, '')) && !han.test(previous) && /^\p{Script=Han}/u.test(line)) ||
          (sentenceEnd.test(previous) && short(line) && /[:：]$/.test(line)) ||
          (/[:：]$/.test(previous) && !speaker.test(previous) && !mailField.test(previous)))) flush();
    current.push(raw);
  }
  flush(); return paragraphs;
}

export function parseMaterialMarkdown(source: string, flow: MaterialFlow = 'document'): MaterialBlock[] {
  const lines = source.replace(/\r\n?/g, '\n')
    .replace(/([（(])\s*\n\s*([A-D])\s*\n\s*([）)])/g, '$1$2$3')
    .replace(/^[▶→➤]\s*\n\s*解析\s*$/gm, match => match.replace(/\s+/g, ' '))
    .split('\n');
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
    blocks.push(...documentParagraphs(prose, flow).map(text => ({ kind: 'paragraph' as const, text })));
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
