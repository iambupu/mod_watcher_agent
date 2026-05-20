import React from "react";

export function MarkdownText({ text, className = "" }: { text: string; className?: string }) {
  const lines = text.split(/\r?\n/);
  const elements: React.ReactNode[] = [];
  let listItems: React.ReactNode[] = [];
  let orderedListItems: React.ReactNode[] = [];
  let tableRows: string[][] = [];

  const flushList = () => {
    if (listItems.length === 0) return;
    elements.push(
      <ul key={`ul-${elements.length}`} className="my-2 list-disc space-y-1 pl-5">
        {listItems}
      </ul>,
    );
    listItems = [];
  };

  const flushOrderedList = () => {
    if (orderedListItems.length === 0) return;
    elements.push(
      <ol key={`ol-${elements.length}`} className="my-2 list-decimal space-y-1 pl-5">
        {orderedListItems}
      </ol>,
    );
    orderedListItems = [];
  };

  const flushTable = () => {
    if (tableRows.length === 0) return;
    const rows = tableRows;
    tableRows = [];
    const [head, ...body] = rows;
    elements.push(
      <div key={`table-${elements.length}`} className="my-3 overflow-x-auto rounded-md border border-gray-200">
        <table className="min-w-full border-collapse text-left text-xs">
          <thead className="bg-gray-50 text-gray-700">
            <tr>
              {head.map((cell, cellIndex) => (
                <th key={`th-${cellIndex}`} className="border-b border-gray-200 px-3 py-2 font-semibold">
                  {renderInlineMarkdown(cell)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={`tr-${rowIndex}`} className="odd:bg-white even:bg-gray-50/60">
                {row.map((cell, cellIndex) => (
                  <td key={`td-${rowIndex}-${cellIndex}`} className="border-t border-gray-100 px-3 py-2 align-top">
                    {renderInlineMarkdown(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
  };

  const flushBlocks = () => {
    flushList();
    flushOrderedList();
    flushTable();
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (isTableStart(lines, index)) {
      flushList();
      flushOrderedList();
      tableRows.push(parseTableRow(line));
      index += 1; // Skip delimiter row.
      while (index + 1 < lines.length && isTableRow(lines[index + 1])) {
        index += 1;
        tableRows.push(parseTableRow(lines[index]));
      }
      flushTable();
      continue;
    }

    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
    if (unordered) {
      flushOrderedList();
      flushTable();
      listItems.push(
        <li key={`li-${index}`} className="break-words">
          {renderInlineMarkdown(unordered[1] || "")}
        </li>,
      );
      continue;
    }
    if (ordered) {
      flushList();
      flushTable();
      orderedListItems.push(
        <li key={`oli-${index}`} className="break-words">
          {renderInlineMarkdown(ordered[1] || "")}
        </li>,
      );
      continue;
    }

    flushBlocks();

    if (!line.trim()) {
      elements.push(<div key={`br-${index}`} className="h-2" />);
      continue;
    }

    if (/^\s*[-*_]{3,}\s*$/.test(line)) {
      elements.push(<hr key={`hr-${index}`} className="my-3 border-gray-200" />);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const Tag = (`h${Math.min(level + 2, 6)}`) as keyof JSX.IntrinsicElements;
      elements.push(
        <Tag key={`h-${index}`} className={headingClass(level)}>
          {renderInlineMarkdown(heading[2])}
        </Tag>,
      );
      continue;
    }

    elements.push(
      <p key={`p-${index}`} className="whitespace-pre-wrap break-words leading-6">
        {renderInlineMarkdown(line)}
      </p>,
    );
  }

  flushBlocks();

  return <div className={`space-y-1 ${className}`}>{elements}</div>;
}

function headingClass(level: number): string {
  if (level <= 2) return "mt-3 text-base font-semibold leading-6";
  if (level === 3) return "mt-3 text-sm font-semibold leading-6";
  return "mt-2 text-xs font-semibold leading-5";
}

function isTableRow(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.includes("|") && parseTableRow(trimmed).length >= 2;
}

function isTableDelimiter(line: string): boolean {
  if (!isTableRow(line)) return false;
  return parseTableRow(line).every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function isTableStart(lines: string[], index: number): boolean {
  return isTableRow(lines[index] || "") && isTableDelimiter(lines[index + 1] || "");
}

function parseTableRow(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function renderInlineMarkdown(text: string): React.ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={`strong-${match.index}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      nodes.push(
        <code key={`code-${match.index}`} className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[0.9em] text-gray-800">
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      const label = token.match(/^\[([^\]]+)\]/)?.[1] || token;
      const href = match[2];
      nodes.push(
        <a
          key={`link-${match.index}`}
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-blue-600 underline underline-offset-2 hover:text-blue-700"
        >
          {label}
        </a>,
      );
    }
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}
