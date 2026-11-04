/**
 * The conversation's own weather: a slow, neutral LED drift field, full-bleed
 * behind the messages and the composer.
 *
 * It used to carry four coloured liquid patches as well. They are gone: the
 * reader asked for a background without coloured circles, and a colour that
 * moves behind a paragraph is the wrong thing to read over. What remains is one
 * field of small dots in the palette's own tertiary ink, so the glass surfaces
 * above it still have something to blur and the page still feels alive, while
 * the brightest dot never passes 0.10 opacity and answer text keeps the
 * contrast it was designed with.
 *
 * It draws nothing a finger can hit (`pointerEvents="none"`) and it costs one
 * 63-dot field of native-driver opacity, with no blur, no gradient and no
 * per-frame JavaScript. It stops when the route loses focus or the app is
 * backgrounded, and under reduced motion it renders the same dots as a still,
 * faint field.
 */

import { memo, useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';

import { useColors } from '../theme/theme';
import { MatrixLed } from './MatrixLed';

/** The brightest dot in the field; answer text must stay fully readable. */
const FIELD_INTENSITY = 0.1;
/** One drift cycle. Slow enough that the field never draws the eye. */
const FIELD_SPEED = 14000;

export type ChatBackgroundProps = {
  /** Stop the ambience without unmounting it (a modal, a paused screen). */
  paused?: boolean;
};

/**
 * A pointer-events-none, full-bleed background for the conversation. `memo`
 * keeps a streaming answer's re-renders from touching a single dot.
 */
export const ChatBackground = memo(function ChatBackground({ paused = false }: ChatBackgroundProps) {
  const palette = useColors();

  // A chat behind a sheet or another route should not keep drawing frames.
  const [focused, setFocused] = useState(true);
  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      return () => setFocused(false);
    }, []),
  );

  return (
    <View pointerEvents="none" style={styles.stage}>
      <View style={styles.field}>
        <MatrixLed
          rows={7}
          cols={9}
          mode="drift"
          dot={4}
          round
          fill
          color={palette.ink3}
          intensity={FIELD_INTENSITY}
          speed={FIELD_SPEED}
          paused={!focused || paused}
        />
      </View>
    </View>
  );
});

const styles = StyleSheet.create({
  stage: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, overflow: 'hidden' },
  field: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, paddingHorizontal: 12, paddingVertical: 18 },
});
