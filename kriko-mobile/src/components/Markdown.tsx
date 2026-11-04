/**
 * The small amount of Markdown a Kriko Agent answer uses, rendered natively.
 *
 * The block grammar lives in `src/engine/markdownTable.ts` (pure, so the offline
 * suite can prove it); this file only draws what it returns. The agent is told
 * to write short paragraphs, bullets and one bold phrase, and — when comparing
 * models or specifications — a compact GFM pipe table. A table gets a native
 * card: a raised header row, hairline row separators and a horizontal scroll
 * only when the columns are wider than the answer column.
 *
 * Every block shares one vertical step (4/8/12/16) and one body token, so a long
 * answer reads as one column rather than a stack of differently spaced runs.
 */

import { useMemo, useState } from 'react';
import { Linking, ScrollView, StyleSheet, Text, View, type TextStyle } from 'react-native';

import { parseMarkdownBlocks, type MarkdownTable } from '../engine/markdownTable';
import { motion } from '../theme/motion';
import { font, gap, radius } from '../theme/tokens';
import { makeStyles, useColors, useType } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { ChevronRightIcon } from './Icon';
import { MotionView } from './Motion';

type Piece = {
  text: string;
  bold?: boolean;
  code?: boolean;
  cite?: boolean;
  href?: string;
};

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[\d{1,2}\]|\[[^\]]+\]\(https?:\/\/[^)]+\))/g;

function piecesOf(text: string): Piece[] {
  const pieces: Piece[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0;
    if (index > last) pieces.push({ text: text.slice(last, index) });
    const value = match[0];
    if (value.startsWith('**')) {
      pieces.push({ text: value.slice(2, -2), bold: true });
    } else if (value.startsWith('`')) {
      pieces.push({ text: value.slice(1, -1), code: true });
    } else if (/^\[\d+\]$/.test(value)) {
      pieces.push({ text: value, cite: true });
    } else {
      const link = value.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
      if (link) pieces.push({ text: link[1], href: link[2] });
      else pieces.push({ text: value });
    }
    last = index + value.length;
  }
  if (last < text.length) pieces.push({ text: text.slice(last) });
  return pieces;
}

function Inline({ text }: { text: string }) {
  const styles = useStyles();
  const type = useType();
  return (
    <>
      {piecesOf(text).map((piece, index) => {
        if (piece.href) {
          return (
            <Text
              key={index}
              onPress={() => {
                Linking.openURL(piece.href as string).catch(() => {});
              }}
              style={styles.link}
            >
              {piece.text}
            </Text>
          );
        }
        if (piece.cite) {
          // A reference tag, not a stray number: the same blue as a link, on a
          // wash, so "[2]" reads as "this came from source 2".
          return (
            <Text key={index} style={[styles.cite, { fontSize: type.sectionLabel.fontSize }]}>
              {piece.text}
            </Text>
          );
        }
        if (piece.bold) {
          return (
            <Text key={index} style={styles.bold}>
              {piece.text}
            </Text>
          );
        }
        if (piece.code) {
          return (
            <Text key={index} style={[styles.code, { fontSize: type.bodyTight.fontSize }]}>
              {piece.text}
            </Text>
          );
        }
        return <Text key={index}>{piece.text}</Text>;
      })}
    </>
  );
}

/* ------------------------------------------------------------------ table -- */

/** Narrowest and widest a column may be before the table learns to scroll. */
const COL_MIN = 88;
const COL_MAX = 220;
/** Rough width of one body character; only used to size a column. */
const CHAR_W = 7.2;
/** Horizontal and vertical cell padding; wide enough to keep a row readable. */
const CELL_X = 10;
const CELL_Y = 9;

/**
 * A cell's visible length with its inline Markdown stripped, so `**bold**` does
 * not buy a column two extra characters of width.
 */
function visibleLength(cell: string): number {
  return cell
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[\d{1,2}\]/g, '12')
    .length;
}

/** Widths derived from the longest cell in each column, clamped to a readable band. */
function columnWidths(table: MarkdownTable): number[] {
  return table.header.map((_, column) => {
    let longest = visibleLength(table.header[column] ?? '');
    for (const row of table.rows) longest = Math.max(longest, visibleLength(row[column] ?? ''));
    const width = Math.round(longest * CHAR_W) + CELL_X * 2;
    return Math.min(COL_MAX, Math.max(COL_MIN, width));
  });
}

function MarkdownTableView({ table }: { table: MarkdownTable }) {
  const styles = useStyles();
  const color = useColors();
  const type = useType();
  const widths = useMemo(() => columnWidths(table), [table]);
  const total = useMemo(() => widths.reduce((sum, width) => sum + width, 0), [widths]);
  const [available, setAvailable] = useState(0);
  const scrolls = available > 0 && total > available + 1;
  // The header reads a touch lighter than the body: semibold, same size.
  const text: TextStyle = { fontSize: Math.max(11, (type.bodyTight.fontSize ?? 14.5) - 0.5) };

  const card = (
    <View style={styles.tableCard}>
      <View style={styles.tableHeader}>
        {table.header.map((cell, column) => (
          <View key={column} style={[styles.tableCell, { width: widths[column] }]}>
            <Txt
              variant="bodyTight"
              tone="ink"
              style={[styles.tableHeadText, text, { textAlign: table.align[column] }]}
            >
              <Inline text={cell} />
            </Txt>
          </View>
        ))}
      </View>
      {table.rows.map((row, rowIndex) => (
        <View key={rowIndex} style={styles.tableRow}>
          {row.map((cell, column) => (
            <View key={column} style={[styles.tableCell, { width: widths[column] }]}>
              <Txt
                variant="bodyTight"
                tone="ink"
                style={[styles.tableBodyText, text, { textAlign: table.align[column] }]}
              >
                <Inline text={cell} />
              </Txt>
            </View>
          ))}
        </View>
      ))}
    </View>
  );

  return (
    <View style={styles.tableWrap} onLayout={(event) => setAvailable(event.nativeEvent.layout.width)}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} bounces={false} scrollEnabled={scrolls}>
        {card}
      </ScrollView>
      {scrolls ? (
        <View style={styles.tableCue} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
          <Txt variant="monoSm" tone="ink3">Swipe sideways for the rest</Txt>
          <ChevronRightIcon size={11} color={color.ink3} />
        </View>
      ) : null}
    </View>
  );
}

/* --------------------------------------------------------------- markdown -- */

/**
 * `streaming` is an answer still being drawn: each new block eases in at once
 * and shallowly, instead of waiting its turn by position like a finished one.
 */
export function Markdown({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const styles = useStyles();
  const blocks = useMemo(() => parseMarkdownBlocks(text), [text]);
  const reveal = (index: number) => streaming
    ? { delay: 0, duration: motion.duration.standard, rise: 6 }
    : { delay: Math.min(index * 55, 220) };
  return (
    <View style={styles.stack}>
      {blocks.map((block, index) => {
        if (block.kind === 'hr') {
          return (
            <MotionView key={index} {...reveal(index)} style={styles.block}>
              <View style={styles.rule} />
            </MotionView>
          );
        }
        if (block.kind === 'h') {
          return (
            <MotionView key={index} {...reveal(index)} style={styles.block}>
              <Txt variant="heading" tone="ink" style={styles.heading}>
                {block.text}
              </Txt>
            </MotionView>
          );
        }
        if (block.kind === 'quote') {
          return (
            <MotionView key={index} {...reveal(index)} style={styles.block}>
              <View style={styles.quote}>
                <Txt variant="body" tone="ink2">
                  <Inline text={block.text} />
                </Txt>
              </View>
            </MotionView>
          );
        }
        if (block.kind === 'table') {
          return (
            <MotionView key={index} {...reveal(index)} style={styles.block}>
              <MarkdownTableView table={block.table} />
            </MotionView>
          );
        }
        if (block.kind === 'li') {
          return (
            <MotionView key={index} {...reveal(index)} style={styles.block}>
              <View style={styles.bullet}>
                <Txt variant="body" tone="accent" style={styles.marker}>
                  {block.marker}
                </Txt>
                <Txt variant="body" tone="ink" style={styles.bulletText}>
                  <Inline text={block.text} />
                </Txt>
              </View>
            </MotionView>
          );
        }
        return (
          <MotionView key={index} {...reveal(index)} style={styles.block}>
            <Txt variant="body" tone="ink" style={styles.paragraph}>
              <Inline text={block.text} />
            </Txt>
          </MotionView>
        );
      })}
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  stack: { gap: gap[3] },
  block: { width: '100%' },
  paragraph: {},
  heading: { marginTop: gap[1] },
  marker: { width: gap[4] + gap[1], textAlign: 'left' },
  bullet: { flexDirection: 'row', gap: gap[2], paddingRight: gap[1] },
  bulletText: { flex: 1 },
  bold: { fontFamily: font.semibold, color: color.ink },
  code: {
    fontFamily: font.mono,
    color: color.fill,
    backgroundColor: color.inset,
    borderRadius: 4,
    paddingHorizontal: gap[1],
  },
  // A citation is a target as well as a mark: a bold number on a soft chip, wide
  // enough to see and to tap beside the sentence it supports.
  cite: {
    color: color.fill,
    fontFamily: font.bold,
    backgroundColor: color.accentSoft,
    borderRadius: 7,
    paddingHorizontal: 6,
  },
  link: { color: color.fill, textDecorationLine: 'underline' },
  quote: {
    borderLeftWidth: 3,
    borderLeftColor: color.edgeStrong,
    paddingLeft: gap[3],
    paddingVertical: gap[1],
  },
  rule: { height: StyleSheet.hairlineWidth, backgroundColor: color.edgeStrong, marginVertical: gap[1] },
  tableWrap: { width: '100%' },
  tableCard: {
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.surface,
    overflow: 'hidden',
  },
  tableHeader: {
    flexDirection: 'row',
    backgroundColor: color.raise,
  },
  tableRow: {
    flexDirection: 'row',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edge,
  },
  tableCell: {
    paddingHorizontal: CELL_X,
    paddingVertical: CELL_Y,
  },
  tableHeadText: { fontFamily: font.semibold },
  tableBodyText: {},
  tableCue: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingTop: gap[1],
    paddingLeft: 2,
  },
}));
