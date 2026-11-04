/**
 * Soft colour that lives behind the page, so the glass above it has something
 * to frost. Three radial washes in the brand hue; nothing here takes a touch.
 */

import { StyleSheet, useWindowDimensions } from 'react-native';
import Svg, { Circle, Defs, RadialGradient, Stop } from 'react-native-svg';

import { useTheme } from '../theme/theme';

export function Aurora() {
  const { width, height } = useWindowDimensions();
  const { dark, color } = useTheme();
  const peak = dark ? 0.34 : 0.22;
  const orbs = [
    { id: 'a', x: width * 0.05, y: height * 0.12, r: width * 0.85, hue: color.accent, o: peak },
    { id: 'b', x: width * 1.0, y: height * 0.5, r: width * 0.8, hue: color.accentHi, o: peak * 0.8 },
    { id: 'c', x: width * 0.2, y: height * 0.95, r: width * 0.9, hue: color.accent, o: peak * 0.9 },
  ];
  return (
    <Svg style={StyleSheet.absoluteFill} width={width} height={height} pointerEvents="none">
      <Defs>
        {orbs.map((orb) => (
          <RadialGradient key={orb.id} id={orb.id} cx="50%" cy="50%" r="50%">
            <Stop offset="0" stopColor={orb.hue} stopOpacity={orb.o} />
            <Stop offset="1" stopColor={orb.hue} stopOpacity={0} />
          </RadialGradient>
        ))}
      </Defs>
      {orbs.map((orb) => (
        <Circle key={orb.id} cx={orb.x} cy={orb.y} r={orb.r} fill={`url(#${orb.id})`} />
      ))}
    </Svg>
  );
}
