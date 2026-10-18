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
import { Txt } from '../theme/Txt';

export function Wordmark({ height = 22, tint = '#FFFFFF' }: { height?: number; tint?: string }) {
  const width = (height * LOGO_WIDTH) / LOGO_HEIGHT;
  return (
    <Svg width={width} height={height} viewBox={`0 0 ${LOGO_WIDTH} ${LOGO_HEIGHT}`}>
      <Path d={LOGO_PATHS} fill={tint} fillRule="evenodd" />
    </Svg>
  );
}

export function BetaPill() {
  return (
    <View style={styles.pill}>
      <Txt variant="beta" tone="#FFFFFF" style={styles.pillText}>
        Beta
      </Txt>
    </View>
  );
}

export function Logo({ tint = '#FFFFFF' }: { tint?: string }) {
  return (
    <View style={styles.row}>
      <Wordmark height={22} tint={tint} />
      <BetaPill />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  pill: {
    borderWidth: 1.5,
    borderColor: '#FFFFFF',
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
});
