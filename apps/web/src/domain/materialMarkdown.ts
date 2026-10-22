/** Deliberately small Markdown grammar: no HTML, links, code or embedded media. */
export type MaterialBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'list'; ordered: boolean; start: number; items: string[]; values?: number[] }
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
const bullet = /^\s*(?:([-+*])\s+|(\d+)[.)]\s+)(\S.*)$/;

/** PDF extraction can put a bullet glyph alone on a row. A star inside a
 * Chinese title remains a literal footnote marker, not the start of a list. */
function sourceBullets(source: string): string {
  const lines = source.split('\n');
  const splitOrdinal = /^\s*\d{1,2}[.)]\s*$/;
  const ordinalRows = lines.filter(line => splitOrdinal.test(line)).length;
  let titleDepth = 0;
  let splitDashList = false;
  for (let at = 0; at < lines.length; at++) {
    const line = lines[at];
    if (!line.trim() && lines[at + 1]?.trim() !== '-') splitDashList = false;
    let previous = '';
    for (let before = at - 1; before >= 0 && !previous; before--) previous = lines[before].trim();
    const dash = line.trim() === '-' && !/[-‐‑]{2,}$/.test(previous) &&
      (!previous || /[:：]$/.test(previous) || splitDashList);
    const optionLabel = /^[）)]$|^[（(][A-D][）)]$/i.test(previous);
    const ordinal = splitOrdinal.test(line) && !optionLabel && (ordinalRows > 1 || !previous || /[:：]$/.test(previous));
    if ((/^\s*\*\s*$/.test(line) || dash || ordinal) && lines[at + 1]?.trim()) {
      if (titleDepth > 0 && line.trim() === '*') lines[at] = '\\*';
      else { lines[at] = line.trim() + ' ' + lines[at + 1].trimStart(); lines.splice(at + 1, 1); if (dash) splitDashList = true; }
    }
    titleDepth += (line.match(/《/g) ?? []).length - (line.match(/》/g) ?? []).length;
    titleDepth = Math.max(0, titleDepth);
  }
  return lines.join('\n');
}

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
    const compound = /[\p{L}\p{N}][-‐‑]$/u.test(result);
    const splitBlank = /[-‐‑]/.test(last) && /[-‐‑]/.test(first);
    const gap = hardBreak(lines[i - 1]) ? '\n' : /^[（(][A-D][）)]$/.test(lines[i - 1].trim()) && /^[a-z]/i.test(first) ? ' ' :
      !last || compound || splitBlank || han.test(last) || han.test(first) || /[([{“‘（【「『《，。！？；：、）】》」』]/.test(last) || /[,.;:!?%)}\]”’，。！？；：、）》」』】]/.test(first) ? '' : ' ';
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
  const lines = sourceBullets(source.replace(/\r\n?/g, '\n'))
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
      const values: number[] = [];
      const start = ordered ? Number(item[2]) : 1;
      while (at < lines.length) {
        const next = bullet.exec(lines[at]);
        if (!lines[at].trim()) {
          let after = at + 1;
          while (after < lines.length && !lines[after].trim()) after++;
          const following = after < lines.length ? bullet.exec(lines[after]) : null;
          if (following && !!following[2] === ordered && (!ordered || Number(following[2]) === values.at(-1)! + 1)) { at = after; continue; }
          break;
        }
        const boundary = choice.test(lines[at].trim()) || annotation.test(lines[at].trim()) ||
          mailField.test(lines[at].trim()) || speaker.test(lines[at].trim()) || chat.test(lines[at].trim()) ||
          /^(?:Results|Analysis|Overview|Key Goals|Our Core Values)$/i.test(lines[at].trim());
        if (!next && items.length && lines[at].trim() && !boundary && !heading.test(lines[at]) && !tableAt(lines, at)) {
          const detail = lines[at++].trimStart();
          // Form subchoices and postal fields intentionally keep their rows.
          if (/^(?:[□■]|(?:Mr|Ms|Mrs|Dr)\.\s|\d+\s+.*(?:Road|Street|Drive|Lane|Avenue)\b)/.test(detail)) items[items.length - 1] += '\n' + detail;
          else {
            const item = items[items.length - 1], last = item.lastIndexOf('\n') + 1;
            items[items.length - 1] = item.slice(0, last) + reflowSoftLines(item.slice(last) + '\n' + detail);
          }
          continue;
        }
        if (!next || !!next[2] !== ordered) break;
        items.push(next[3]); if (ordered) values.push(Number(next[2])); at++;
      }
      blocks.push({ kind: 'list', ordered, start, items,
        ...(ordered && values.some((value, index) => value !== start + index) ? { values } : {}) }); continue;
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
    // A run is atomic: never start emphasis halfway through a printed blank.
    const blank = /^_{3,}/.exec(source.slice(at))?.[0];
    if (blank && (blank.length > 3 || !/\S/.test(source[at + blank.length] ?? ''))) {
      plain += blank; at += blank.length; continue;
    }
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
