/**
 * The pipe tables an answer draws: parsed as tables, never confused with a
 * thematic break, a bullet list or the paragraph that follows one.
 */

import assert from 'node:assert/strict';

import {
  parseMarkdownBlocks,
  parseTable,
  splitTableRow,
  type MarkdownBlock,
  type MarkdownTable,
} from '../src/engine/markdownTable';

/** A real GFM table: header, per-column alignment, inline markdown kept. */
function realTable(): void {
  const lines = [
    '| Model | Price | Verdict |',
    '|:--|--:|:--:|',
    '| **A-18** | `$99` | Good [2] |',
    '| B-22 | $120 | See [owners](https://example.com/owners) |',
  ];
  const parsed = parseTable(lines, 0);
  assert.ok(parsed, 'a header row above a delimiter row is a table');
  assert.deepEqual(parsed.table.header, ['Model', 'Price', 'Verdict']);
  assert.deepEqual(parsed.table.align, ['left', 'right', 'center']);
  assert.equal(parsed.consumed, 4, 'the whole block belongs to the table');
  assert.equal(parsed.table.rows.length, 2);
  assert.equal(parsed.table.rows[0][0], '**A-18**', 'inline bold stays in the cell');
  assert.equal(parsed.table.rows[0][1], '`$99`', 'inline code stays in the cell');
  assert.equal(parsed.table.rows[0][2], 'Good [2]', 'a citation stays in the cell');
  assert.equal(
    parsed.table.rows[1][2],
    'See [owners](https://example.com/owners)',
    'a link stays in the cell',
  );

  const blocks = parseMarkdownBlocks(`Here are the options:\n\n${lines.join('\n')}`);
  assert.deepEqual(blocks.map((block) => block.kind), ['p', 'table']);
  const table = blocks[1];
  if (table.kind !== 'table') assert.fail('the second block is the table');
  assert.deepEqual(table.table, parsed.table);
}

/** Missing outer pipes, escaped pipes, and GFM row padding/truncation. */
function tolerantRows(): void {
  const parsed = parseTable(['Model | Price', '--- | ---', 'A | 1', 'B \\| C | 2'], 0);
  assert.ok(parsed, 'outer pipes are optional');
  assert.deepEqual(parsed.table.header, ['Model', 'Price']);
  assert.deepEqual(parsed.table.align, ['left', 'left']);
  assert.deepEqual(parsed.table.rows, [['A', '1'], ['B | C', '2']], 'an escaped pipe is text');

  const short = parseTable(['| a | b | c |', '|---|---|---|', '| 1 |'], 0);
  assert.ok(short);
  assert.deepEqual(short.table.rows[0], ['1', '', ''], 'a short row is padded');

  const long = parseTable(['| a | b |', '|---|---|', '| 1 | 2 | 3 |'], 0);
  assert.ok(long);
  assert.deepEqual(long.table.rows[0], ['1', '2'], 'extra cells are dropped');

  assert.deepEqual(splitTableRow('| a | b |'), ['a', 'b']);
  assert.deepEqual(splitTableRow('a | b'), ['a', 'b']);
  assert.deepEqual(splitTableRow('| a \\| b | c |'), ['a | b', 'c']);
}

/** A rule, a bullet list and a mismatched delimiter are not tables. */
function notTables(): void {
  assert.equal(parseTable(['---'], 0), null, 'a bare rule is not a table');
  assert.equal(parseTable(['***'], 0), null);
  assert.equal(parseTable(['Text', '---'], 0), null, 'a paragraph over a rule is not a table');
  assert.equal(parseTable(['- one', '- two'], 0), null, 'a bullet list is not a table');
  const mismatched = parseTable(['| a | b |', 'not a delimiter'], 0);
  assert.equal(mismatched, null);
  const uneven = parseTable(['| a | b |', '|---|'], 0);
  assert.equal(uneven, null, 'the delimiter must have the header’s columns');

  const blocks = parseMarkdownBlocks('A line.\n\n---\n\n- one\n- two');
  assert.deepEqual(blocks.map((block) => block.kind), ['p', 'hr', 'li', 'li']);
}

/** A table ends at the first line without a pipe, so the next block flushes. */
function tableThenParagraph(): void {
  const source = 'Intro line.\n\n| A | B |\n|---|---|\n| 1 | 2 |\nAfter the table.';
  const blocks = parseMarkdownBlocks(source);
  assert.deepEqual(blocks.map((block) => block.kind), ['p', 'table', 'p']);
  const middle = blocks[1];
  if (middle.kind !== 'table') assert.fail('the middle block is a table');
  assert.deepEqual(middle.table.header, ['A', 'B']);
  assert.deepEqual(middle.table.rows, [['1', '2']]);
  const last = blocks[2];
  if (last.kind !== 'p') assert.fail('the table does not swallow the paragraph after it');
  assert.equal(last.text, 'After the table.');

  // A row without a pipe halfway through is the next block, not a one-cell row.
  const stops = parseMarkdownBlocks('| A | B |\n|---|---|\n| 1 | 2 |\nPlain after.');
  assert.deepEqual(stops.map((block) => block.kind), ['table', 'p']);
}

/** Text with no table parses exactly as it did before tables existed. */
function plainTextUnchanged(): void {
  const source = [
    'The chuck can wobble after heavy use.',
    '',
    'The call: Check the mount before buying.',
    '',
    '- point one',
    '- point two',
    '',
    '> a quote',
    '',
    '## Heading',
  ].join('\n');
  const expected: MarkdownBlock[] = [
    { kind: 'p', text: 'The chuck can wobble after heavy use.' },
    { kind: 'h', text: 'The call' },
    { kind: 'p', text: 'Check the mount before buying.' },
    { kind: 'li', text: 'point one', marker: '•' },
    { kind: 'li', text: 'point two', marker: '•' },
    { kind: 'quote', text: 'a quote' },
    { kind: 'h', text: 'Heading' },
  ];
  assert.deepEqual(parseMarkdownBlocks(source), expected);
  assert.deepEqual(parseMarkdownBlocks('Just one plain paragraph.'), [
    { kind: 'p', text: 'Just one plain paragraph.' },
  ]);
  assert.equal(parseTable(['Just one plain paragraph.'], 0), null);
}

/** Parse once and hand the table back, for the callers above. */
function tableOf(source: string): MarkdownTable {
  const parsed = parseTable(source.split('\n'), 0);
  assert.ok(parsed);
  return parsed.table;
}

function main(): void {
  realTable();
  tolerantRows();
  notTables();
  tableThenParagraph();
  plainTextUnchanged();
  // The helper above is exercised so a future reader sees its shape.
  assert.equal(tableOf('| A | B |\n|---|---|\n| 1 | 2 |').rows.length, 1);
  console.log('Markdown table checks passed.');
}

main();
