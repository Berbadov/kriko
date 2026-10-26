/**
 * The floating K, drawn small so the transparency choice is something the
 * reader sees before choosing it. It mirrors the native puck: a rounded glass
 * chip carrying the Kriko mark, over a few lines of "page" so the see-through
 * is visible.
 */

import { StyleSheet, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { LOGO_PATHS } from '../assets/logoPaths';
import { makeStyles, useColors } from '../theme/theme';

/** The mark is the first outline of the wordmark: the K, without the letters after it. */
const MARK = LOGO_PATHS.slice(0, LOGO_PATHS.indexOf('Z') + 1);
const MARK_BOX = (() => {
  const numbers = (MARK.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
  const xs = numbers.filter((_, index) => index % 2 === 0);
  const ys = numbers.filter((_, index) => index % 2 === 1);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  return { x: minX, y: minY, w: Math.max(...xs) - minX, h: Math.max(...ys) - minY };
})();

export function PuckPreview({ opacity }: { opacity: number }) {
  const color = useColors();
  const styles = useStyles();
  const level = Math.max(0.2, Math.min(1, opacity / 100));
  const aspect = MARK_BOX.w / MARK_BOX.h;
  return (
    <View style={styles.tile} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <View style={[styles.behind, { backgroundColor: color.ink3, width: 44 }]} />
      <View style={[styles.behind, { backgroundColor: color.ink3, width: 30 }]} />
      <View style={[styles.behind, { backgroundColor: color.ink3, width: 40 }]} />
      <View style={[styles.chip, { opacity: level }]}>
        <View style={styles.sheen} />
        <Svg
          width={18 * aspect}
          height={18}
          viewBox={`${MARK_BOX.x} ${MARK_BOX.y} ${MARK_BOX.w} ${MARK_BOX.h}`}
        >
          <Path d={MARK} fill={color.onAccent} fillRule="evenodd" />
        </Svg>
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
  chip: {
    position: 'absolute',
    right: 8,
    top: 14,
    width: 36,
    height: 36,
    borderRadius: 12,
    backgroundColor: color.accent,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  sheen: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: 0,
    height: 15,
    backgroundColor: 'rgba(255,255,255,0.22)',
  },
}));
