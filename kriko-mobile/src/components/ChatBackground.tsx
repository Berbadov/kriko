/**
 * The conversation's own weather: a cloud of dust, full-bleed behind the
 * messages and the composer.
 *
 * It used to be a 63-dot LED field. It is the dust now, the same grain as
 * the desktop app's home: on the home screen it banks at the edges and opens
 * round the scan button, behind a conversation it thins to a third so answer
 * text keeps its contrast, and while a page is read a band of light passes
 * down through it.
 *
 * It draws nothing a finger can hit, stops when the route loses focus or the
 * app is backgrounded, and under reduced motion it is one still frame.
 */

import { memo, useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';

import { DustCanvas } from '../dust/DustCanvas';
import { cloud, reading as readingScene } from '../dust/engine';

export type ChatBackgroundProps = {
  /** Stop the ambience without unmounting it (a modal, a paused screen). */
  paused?: boolean;
  /** The home screen: brighter, and open round the scan button. */
  lively?: boolean;
  /** A page is being read: a band of light passes down through the dust. */
  reading?: boolean;
  /** Change the key to throw the dust out from a point, as a press does. */
  burst?: { key: number; x: number; y: number };
};

/** The home's cloud opens where the scan button sits. */
const HOME = cloud({ x: 0.5, y: 0.44, r: 0.2 });
/** Behind a conversation the banks stay at the edges, away from the reading column. */
const THREAD = cloud({ x: 0.5, y: 0.5, r: 0.42 });

export const ChatBackground = memo(function ChatBackground({ paused = false, lively = false, reading = false, burst }: ChatBackgroundProps) {
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
      <DustCanvas
        scene={reading ? readingScene : lively ? HOME : THREAD}
        reading={reading}
        strength={lively || reading ? 1 : 0.35}
        calm={!lively && !reading}
        cap={lively ? 7000 : 4000}
        paused={!focused || paused}
        burst={burst}
      />
    </View>
  );
});

const styles = StyleSheet.create({
  stage: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, overflow: 'hidden' },
});
