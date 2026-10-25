/**
 * The floating K, drawn small so the transparency choice is something the
 * reader sees before choosing it. It mirrors the native puck: a page with a
 * folded corner, the K, and lines of text, over a few lines of "page" so the
 * see-through is visible.
 */

import { StyleSheet, View } from 'react-native';

import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

export function PuckPreview({ opacity }: { opacity: number }) {
  const color = useColors();
  const styles = useStyles();
  return (
    <View style={styles.tile} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <View style={[styles.behind, { backgroundColor: color.ink3, width: 44 }]} />
      <View style={[styles.behind, { backgroundColor: color.ink3, width: 30 }]} />
      <View style={[styles.behind, { backgroundColor: color.ink3, width: 40 }]} />
      <View style={[styles.page, { opacity: Math.max(0.2, Math.min(1, opacity / 100)) }]}>
        <View style={styles.fold} />
        <Txt variant="cardTitle" tone={color.onAccent} translate={false} style={styles.k}>K</Txt>
        <View style={styles.lines}>
          <View style={[styles.line, { width: 20 }]} />
          <View style={[styles.line, { width: 13 }]} />
        </View>
      </View>
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  tile: {
    width: 64,
    height: 72,
    borderRadius: 14,
    backgroundColor: color.inset,
    borderWidth: 1,
    borderColor: color.edge,
    overflow: 'hidden',
    justifyContent: 'center',
    paddingLeft: 8,
    gap: 7,
  },
  behind: { height: 4, borderRadius: 2, opacity: 0.55 },
  page: {
    position: 'absolute',
    right: 9,
    top: 9,
    width: 32,
    height: 44,
    borderRadius: 8,
    backgroundColor: color.accent,
    alignItems: 'center',
    paddingTop: 7,
    overflow: 'hidden',
  },
  fold: {
    position: 'absolute',
    right: 0,
    top: 0,
    width: 9,
    height: 9,
    backgroundColor: 'rgba(255,255,255,0.35)',
    borderBottomLeftRadius: 5,
  },
  k: { fontSize: 17, lineHeight: 21 },
  lines: { position: 'absolute', bottom: 7, gap: 3, alignItems: 'center' },
  line: { height: 2.5, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.7)' },
}));
