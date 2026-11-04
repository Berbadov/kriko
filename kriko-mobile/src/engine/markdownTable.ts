/**
 * The block grammar an answer can use, parsed without a Markdown dependency.
 *
 * The agent writes short paragraphs, bullets, one bold phrase and — when it
 * compares models or specifications — a compact GFM pipe table. Everything here
 * is pure text in, plain objects out: no React Native import, so the offline
 * suite can prove the table rules the screen renders.
 *
 * Table grammar (GFM, tolerant):
 * - A table starts at a header row directly above a delimiter row; both need at
 *   least one `|`, so a bare `---` stays a thematic break and a bullet stays a
 *   bullet.
 * - Leading and trailing pipes are optional; escaped `\|` is cell text.
 * - Cells are trimmed and keep their inline Markdown (bold, code, citation,
 *   link); the renderer formats them.
 * - Alignment comes from the delimiter colons: `:--` left, `--:` right, `:-:`
 *   centre, no colon left.
 * - Rows end at the first line without a pipe; they are padded or truncated to
 *   the header's column count, as GFM does.
 */

/** One column's alignment, derived from the delimiter row's colons. */
export type TableAlign = 'left' | 'center' | 'right';

/** A parsed pipe table; cells still hold inline Markdown. */
export interface MarkdownTable {
  header: string[];
  /** One per column; the default GFM alignment (no colon) is left. */
  align: TableAlign[];
  rows: string[][];
}

/** One renderable block of an answer. */
export type MarkdownBlock =
  | { kind: 'p'; text: string }
  | { kind: 'h'; text: string }
  | { kind: 'li'; text: string; marker: string }
  | { kind: 'quote'; text: string }
  | { kind: 'hr' }
  | { kind: 'table'; table: MarkdownTable };

/** A parsed table and how many source lines it consumed. */
export interface ParsedTable {
  table: MarkdownTable;
  /** Lines from the start index, including the header and delimiter rows. */
  consumed: number;
}

/** A thematic break: `---`, `***`, `___` or spaced variants of them. */
const RULE = /^([-*_])(?:\s*\1){2,}$/;

/** One delimiter cell: hyphens with an optional leading/trailing colon. */
const DELIMITER_CELL = /^:?-+:?$/;

const PIPE = '|';

/**
 * Split one table row into trimmed cells.
 *
 * A leading pipe is dropped, a trailing one only when it is not escaped, so
 * `| a | b |`, `a | b` and `| a | b` all read as two cells. `\|` becomes a
 * literal pipe inside the cell and every other character is left alone.
 */
export function splitTableRow(line: string): string[] {
  let text = line.trim();
  if (text.startsWith(PIPE)) text = text.slice(1);
  if (text.endsWith(PIPE) && !text.endsWith(`\\${PIPE}`)) text = text.slice(0, -1);

  const cells: string[] = [];
  let cell = '';
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '\\' && text[index + 1] === PIPE) {
      cell += PIPE;
      index += 1;
    } else if (char === PIPE) {
      cells.push(cell.trim());
      cell = '';
    } else {
      cell += char;
    }
  }
  cells.push(cell.trim());
  return cells;
}

/** The alignment a delimiter cell names; GFM treats a bare cell as left. */
function alignmentOf(cell: string): TableAlign | null {
  const compact = cell.replace(/\s+/g, '');
  if (!DELIMITER_CELL.test(compact)) return null;
  const left = compact.startsWith(':');
  const right = compact.endsWith(':');
  if (left && right) return 'center';
  if (right) return 'right';
  return 'left';
}

/**
 * Parse a table that starts at `lines[start]`, or return null when this is not
 * a table. The caller walks blocks line by line and advances by `consumed`.
 */
export function parseTable(lines: readonly string[], start: number): ParsedTable | null {
  const headerLine = (lines[start] ?? '').trim();
  const delimiterLine = (lines[start + 1] ?? '').trim();
  // A table needs a pipe on both rows: "Text\n---" is a paragraph and a rule,
  // not a one-column table, because no pipe separates a column from anything.
  if (!headerLine.includes(PIPE) || !delimiterLine.includes(PIPE)) return null;

  const header = splitTableRow(headerLine);
  const delimiter = splitTableRow(delimiterLine);
  // One cell is a rule-shaped line, not a table; a real table has at least two
  // columns because a pipe has to separate one from another.
  if (header.length < 2 || delimiter.length !== header.length) return null;

  const align: TableAlign[] = [];
  for (const cell of delimiter) {
    const alignment = alignmentOf(cell);
    if (!alignment) return null;
    align.push(alignment);
  }

  const rows: string[][] = [];
  let index = start + 2;
  while (index < lines.length) {
    const line = (lines[index] ?? '').trim();
    // A blank line or a line with no pipe ends the table; it is the next block.
    if (!line.includes(PIPE)) break;
    const cells = splitTableRow(line);
    // GFM pads a short row and drops a long row's extra cells.
    rows.push(header.map((_, column) => cells[column] ?? ''));
    index += 1;
  }

  return { table: { header, align, rows }, consumed: index - start };
}

/**
 * Split an answer into renderable blocks. Tables are checked before the rule
 * and list branches, so their `---` delimiter is consumed as a table row and
 * everything else keeps exactly the behaviour it had before tables existed.
 */
export function parseMarkdownBlocks(source: string): MarkdownBlock[] {
  const lines = source.replace(/\r/g, '').split('\n');
  const out: MarkdownBlock[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    if (!paragraph.length) return;
    out.push({ kind: 'p', text: paragraph.join(' ') });
    paragraph = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (!line) {
      flush();
      continue;
    }
    const table = parseTable(lines, index);
    if (table) {
      flush();
      out.push({ kind: 'table', table: table.table });
      index += table.consumed - 1;
      continue;
    }
    // A horizontal rule is a line, not the word "---": the model uses it to
    // close a section, so it becomes a quiet divider instead of three dashes.
    if (RULE.test(line)) {
      flush();
      out.push({ kind: 'hr' });
      continue;
    }
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    if (heading) {
      flush();
      out.push({ kind: 'h', text: heading[1] });
      continue;
    }
    // Mercury often writes a section label as a lone **Bold line** rather than
    // a Markdown heading; without this, the label and the sentence after it
    // became one run-on paragraph ("The call Check for...").
    const boldLine = line.match(/^\*\*([^*]+)\*\*$/);
    if (boldLine) {
      flush();
      out.push({ kind: 'h', text: boldLine[1] });
      continue;
    }
    // The agent sometimes writes "**The call** Do this" on one line. These are
    // section labels in its own brief, not the start of a sentence; split the
    // label from the sentence so it does not read as "The call Prioritize...".
    const label = line.match(
      /^\*{0,2}(the call|what to check|bottom line|verdict|the short version|what i would do)\*{0,2}\b[:\s]*(.*)$/i,
    );
    if (label) {
      flush();
      out.push({ kind: 'h', text: label[1] });
      if (label[2].trim()) paragraph.push(label[2].trim());
      continue;
    }
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      flush();
      out.push({ kind: 'li', text: bullet[1], marker: '•' });
      continue;
    }
    const numbered = line.match(/^(\d{1,2})[.)]\s+(.*)$/);
    if (numbered) {
      flush();
      out.push({ kind: 'li', text: numbered[2], marker: `${numbered[1]}.` });
      continue;
    }
    // A short answer written as "**Hüküm:** ..." on its own line is a bullet
    // in this app, even when the model forgot the hyphen.
    const labelled = line.match(/^\*{0,2}(Hüküm|Kontrol|Eksik|Verdict|Check|Gap)\*{0,2}\s*:\s*(.*)$/i);
    if (labelled) {
      flush();
      out.push({ kind: 'li', text: line, marker: '•' });
      continue;
    }
    if (line.startsWith('>')) {
      flush();
      out.push({ kind: 'quote', text: line.replace(/^>\s?/, '') });
      continue;
    }
    paragraph.push(line);
  }
  flush();
  return out;
}
