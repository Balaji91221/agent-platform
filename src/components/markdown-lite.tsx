import type { ReactNode } from 'react';

/**
 * Enough markdown for a chat bubble: paragraphs, bullet lists, headings,
 * **bold**, `code`. No HTML passthrough, so model output can never inject
 * markup.
 */
export function MarkdownLite({ text }: { text: string }) {
  const blocks = text.replace(/\r/g, '').split(/\n{2,}/).filter((b) => b.trim());
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split('\n');
        const isList = lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l));
        if (isList) {
          return (
            <ul key={i}>
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ''))}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i}>
            {lines.map((l, j) => (
              <span key={j}>
                {line(l)}
                {j < lines.length - 1 ? <br /> : null}
              </span>
            ))}
          </p>
        );
      })}
    </>
  );
}

/**
 * One line inside a paragraph block. Models mix a `###` heading and a `-`
 * bullet into the same block constantly; left raw, the punctuation shows.
 */
function line(raw: string): ReactNode {
  const heading = raw.match(/^\s*#{1,6}\s+(.*)$/);
  if (heading) return <b className="mdh">{inline(heading[1])}</b>;

  const bullet = raw.match(/^\s*([-*•]|\d+[.)])\s+(.*)$/);
  if (bullet) return <span className="mdb">{inline(bullet[2])}</span>;

  return inline(raw);
}

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <b key={i}>{part.slice(2, -2)}</b>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>;
    return <span key={i}>{part}</span>;
  });
}

/**
 * One line of plain text for a preview row. Markdown belongs in the full
 * view; in a two-line clamp the asterisks and hashes are just noise.
 */
export function plainPreview(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/^\s*#{1,6}\s*/gm, '')
    .replace(/^\s*([-*•]|\d+[.)])\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}
