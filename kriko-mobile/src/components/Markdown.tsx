/**
 * The small amount of Markdown a Kriko Agent answer uses, rendered natively.
 *
 * The agent is told to write short paragraphs, bullets and one bold phrase; a
 * full Markdown engine would be a dependency for headings and tables nobody is
 * allowed to send. Links open in the browser; citations are styled in place and
 * the numbered source list sits under the answer.
 */

import { Linking, StyleSheet, Text, View } from 'react-native';

import { color, font, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { MotionView } from './Motion';

type Block =
  | { kind: 'p'; text: string }
  | { kind: 'h'; text: string }
  | { kind: 'li'; text: string; marker: string }
  | { kind: 'quote'; text: string };

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
          return (
            <Text key={index} style={styles.cite}>
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
            <Text key={index} style={styles.code}>
              {piece.text}
            </Text>
          );
        }
        return <Text key={index}>{piece.text}</Text>;
      })}
    </>
  );
}

export function Markdown({ text }: { text: string }) {
  const blocks = blocksOf(text);
  return (
    <View style={styles.stack}>
      {blocks.map((block, index) => {
        if (block.kind === 'h') {
          return (
            <MotionView key={index} delay={Math.min(index * 55, 220)} style={styles.block}>
              <Txt variant="cardTitle" tone="ink" style={styles.heading}>
                {block.text}
              </Txt>
            </MotionView>
          );
        }
        if (block.kind === 'quote') {
          return (
            <MotionView key={index} delay={Math.min(index * 55, 220)} style={styles.block}>
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
            <MotionView key={index} delay={Math.min(index * 55, 220)} style={styles.block}>
              <View style={styles.bullet}>
                <Txt variant="body" tone="accent" style={styles.marker}>
                  {block.marker}
                </Txt>
                <Txt variant="body" tone="ink2" style={styles.bulletText}>
                  <Inline text={block.text} />
                </Txt>
              </View>
            </MotionView>
          );
        }
        return (
          <MotionView key={index} delay={Math.min(index * 55, 220)} style={styles.block}>
            <Txt variant="body" tone="ink2" style={styles.paragraph}>
              <Inline text={block.text} />
            </Txt>
          </MotionView>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 11 },
  block: { width: '100%' },
  paragraph: { fontSize: 16, lineHeight: 25 },
  heading: { fontFamily: font.editorial, fontSize: 19, lineHeight: 25, marginTop: 5, letterSpacing: -0.15 },
  bullet: { flexDirection: 'row', gap: 10, paddingRight: 4 },
  marker: { width: 13, textAlign: 'left', lineHeight: 25 },
  bulletText: { flex: 1, fontSize: 16, lineHeight: 25 },
  bold: { fontFamily: font.semibold, color: color.ink },
  code: { fontFamily: font.mono, fontSize: 13.5, color: color.fill },
  cite: { color: color.fill, fontFamily: font.semibold, fontSize: 12 },
  link: { color: color.fill, textDecorationLine: 'underline' },
  quote: {
    borderLeftWidth: 2,
    borderLeftColor: color.edgeStrong,
    paddingLeft: gap[3],
    paddingVertical: 5,
    borderRadius: radius.s,
  },
});
