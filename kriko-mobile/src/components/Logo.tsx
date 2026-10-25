/**
 * The KRIKO wordmark and the BETA pill.
 *
 * The wordmark is not type: it is the outline traced from the brand artwork by
 * `tools/trace_logo.py`, which is why the chamfered K, R and O come out exact
 * at any size. See `src/assets/logoPaths.ts`.
 */

import { StyleSheet, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { LOGO_HEIGHT, LOGO_PATHS, LOGO_WIDTH } from '../assets/logoPaths';
import { font, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

export function Wordmark({ height = 22, tint }: { height?: number; tint?: string }) {
  const color = useColors();
  const width = (height * LOGO_WIDTH) / LOGO_HEIGHT;
  return (
    <Svg width={width} height={height} viewBox={`0 0 ${LOGO_WIDTH} ${LOGO_HEIGHT}`}>
      <Path d={LOGO_PATHS} fill={tint ?? color.ink} fillRule="evenodd" />
    </Svg>
  );
}

export function BetaPill() {
  const color = useColors();
  const styles = useStyles();
  return (
    <View style={styles.pill}>
      <Txt variant="beta" tone={color.ink} style={styles.pillText}>
        Beta
      </Txt>
    </View>
  );
}

export function Logo({ tint }: { tint?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.row}>
      <Wordmark height={22} tint={tint} />
      <BetaPill />
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  pill: {
    borderWidth: 1.5,
    borderColor: color.ink,
    borderRadius: radius.pill,
    paddingHorizontal: 9,
    paddingVertical: 3,
  },
  pillText: {
    fontFamily: font.bold,
    letterSpacing: 1.8,
    fontSize: 11,
    lineHeight: 14,
  },
}));
