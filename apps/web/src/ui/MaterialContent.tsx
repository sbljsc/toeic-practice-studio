import { createElement, type ReactNode } from 'react';
import type { GroupMaterial } from '../domain/types';
import { materialImageUrl, parseMaterialInline, parseMaterialMarkdown, verifiedMaterialTranscript } from '../domain/materialMarkdown';
import './MaterialContent.css';

function inline(text: string): ReactNode {
  function nodes(parts: ReturnType<typeof parseMaterialInline>): ReactNode {
    return parts.map((part, index) => part.kind === 'text' ? part.text
      : createElement(part.kind === 'strong' ? 'strong' : 'em', { key: index }, nodes(part.children)));
  }
  return nodes(parseMaterialInline(text));
}

export function MaterialContent({ materials, className = '' }: { materials: GroupMaterial[]; className?: string }) {
  return <div className={`material-content ${className}`.trim()}>
    {materials.map((material, index) => {
      const transcript = material.kind === 'image' ? verifiedMaterialTranscript(material) : undefined;
      if (material.kind === 'image' && transcript === undefined) {
        const src = materialImageUrl(material.url);
        return src ? <figure className="material-content__figure" key={index}>
          <img src={src} alt={material.alt || '题目图片'} loading="lazy" />
        </figure> : <p key={index}>{material.alt || '题目图片暂不可用'}</p>;
      }
      return <div className="material-content__text" key={index}>
        {parseMaterialMarkdown(transcript ?? material.text ?? '').map((block, bi) => {
          if (block.kind === 'heading') return createElement(`h${block.level}`, { key: bi }, inline(block.text));
          if (block.kind === 'list') return createElement(block.ordered ? 'ol' : 'ul',
            { key: bi, ...(block.ordered ? { start: block.start } : {}) },
            block.items.map((item, ii) => <li key={ii}>{inline(item)}</li>));
          if (block.kind === 'table') return <div key={bi} className="material-content__table-scroll" role="region" aria-label="材料表格，可横向滚动" tabIndex={0}>
            <table>
              <thead><tr>{block.header.map((cell, ci) => <th scope="col" key={ci} style={{ textAlign: block.align[ci] }}>{inline(cell)}</th>)}</tr></thead>
              <tbody>{block.rows.map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci} style={{ textAlign: block.align[ci] }}>{inline(cell)}</td>)}</tr>)}</tbody>
            </table>
          </div>;
          return <p key={bi}>{inline(block.text)}</p>;
        })}
      </div>;
    })}
  </div>;
}
