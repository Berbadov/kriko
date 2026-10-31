/**
 * The small amount of Markdown a Kriko Agent answer uses, rendered natively.
 *
 * The agent is told to write short paragraphs, bullets and one bold phrase; a
 * full Markdown engine would be a dependency for headings and tables nobody is
 * allowed to send. Links open in the browser; citations are styled in place and
 * the numbered source list sits under the answer.
 *
 * Every block shares one vertical step (4/8/12/16) and one body token, so a long
 * answer reads as one column rather than a stack of differently spaced runs.
 */

import { useMemo } from 'react';
import { Linking, StyleSheet, Text, View } from 'react-native';

import { motion } from '../theme/motion';
import { font, gap } from '../theme/tokens';
import { makeStyles, useType } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { MotionView } from './Motion';

type Block =
  | { kind: 'p'; text: string }
  | { kind: 'h'; text: string }
  | { kind: 'li'; text: string; marker: string }
  | { kind: 'quote'; text: string }
  | { kind: 'hr' };

/** A thematic break: `---`, `***`, `___` or spaced variants of them. */
const RULE = /^([-*_])(?:\s*\1){2,}$/;

function blocksOf(source: string): Block[] {
  const lines = source.replace(/\r/g, '').split('\n');
  const out: Block[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    if (!paragraph.length) return;
    out.push({ kind: 'p', text: paragraph.join(' ') });
    paragraph = [];
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flush();
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

/**
 * `streaming` is an answer still being drawn: each new block eases in at once
 * and shallowly, instead of waiting its turn by position like a finished one.
 */
export function Markdown({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const styles = useStyles();
  const blocks = useMemo(() => blocksOf(text), [text]);
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
  cite: {
    color: color.fill,
    fontFamily: font.semibold,
    backgroundColor: color.accentWash,
    borderRadius: 4,
    paddingHorizontal: 3,
  },
  link: { color: color.fill, textDecorationLine: 'underline' },
  quote: {
    borderLeftWidth: 2,
    borderLeftColor: color.edgeStrong,
    paddingLeft: gap[3],
    paddingVertical: gap[1],
  },
  rule: { height: StyleSheet.hairlineWidth, backgroundColor: color.edgeStrong, marginVertical: gap[1] },
}));
