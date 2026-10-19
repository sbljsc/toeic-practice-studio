import { createElement, type ReactNode } from 'react';
import type { GroupMaterial } from '../domain/types';
import { materialImageUrl, parseMaterialInline, parseMaterialMarkdown, reflowSoftLines, verifiedMaterialTranscript, type MaterialFlow } from '../domain/materialMarkdown';
import { repairLegacyMaterial, type DisplayNumbers } from '../domain/legacyMaterialRepair';
import './MaterialContent.css';

function inline(text: string): ReactNode {
  function nodes(parts: ReturnType<typeof parseMaterialInline>): ReactNode {
    return parts.map((part, index) => part.kind === 'text' ? part.text.split('\n').flatMap((line, li) => li > 0 ? [<br key={`${index}:${li}`} />, line] : [line])
      : createElement(part.kind === 'strong' ? 'strong' : 'em', { key: index }, nodes(part.children)));
  }
  return nodes(parseMaterialInline(text));
}

/** Phrasing-only Markdown for text inside option/subtitle buttons. */
export function MarkdownInline({ text, className = '' }: { text: string; className?: string }) {
  return <span className={`markdown-inline ${className}`.trim()}>{inline(reflowSoftLines(text))}</span>;
}

/** Shared safe Markdown for all learning text, including old frozen reports. */
export function MarkdownText({ text, className = '', flow = 'document' }: { text: string; className?: string; flow?: MaterialFlow }) {
  return <div className={`material-content markdown-text ${className}`.trim()}>
    {parseMaterialMarkdown(text, flow).map((block, bi) => {
      if (block.kind === 'heading') return createElement(`h${block.level}`, { key: bi }, inline(block.text));
      if (block.kind === 'list') return createElement(block.ordered ? 'ol' : 'ul',
        { key: bi, ...(block.ordered ? { start: block.start } : {}) },
        block.items.map((item, ii) => <li key={ii} value={block.ordered ? block.values?.[ii] : undefined}>{inline(item)}</li>));
      if (block.kind === 'table') return <div key={bi} className="material-content__table-scroll" role="region" aria-label="材料表格，可横向滚动" tabIndex={0}>
        <table>
          <thead><tr>{block.header.map((cell, ci) => <th scope="col" key={ci} style={{ textAlign: block.align[ci] }}>{inline(cell)}</th>)}</tr></thead>
          <tbody>{block.rows.map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci} style={{ textAlign: block.align[ci] }}>{inline(cell)}</td>)}</tr>)}</tbody>
        </table>
      </div>;
      return <p key={bi}>{inline(block.text)}</p>;
    })}
  </div>;
}

export function MaterialContent({ materials, className = '', questionNumbers }: { materials: GroupMaterial[]; className?: string; questionNumbers?: DisplayNumbers }) {
  return <div className={`material-content ${className}`.trim()}>
    {materials.map((material, index) => {
      const transcript = material.kind === 'image' ? verifiedMaterialTranscript(material) : undefined;
      if (material.kind === 'image' && transcript === undefined) {
        const src = materialImageUrl(material.url);
        return src ? <figure className="material-content__figure" key={index}>
          <img src={src} alt={material.alt || '题目图片'} loading="lazy" />
        </figure> : <p key={index}>{material.alt || '题目图片暂不可用'}</p>;
      }
      return <MarkdownText key={index} className="material-content__text" text={repairLegacyMaterial(transcript ?? material.text ?? '', questionNumbers)} />;
    })}
  </div>;
}
