/**
 * Where the phone's assistant gesture lands.
 *
 * Holding the power or home button summons Kriko as the phone's assistant. The
 * assistant window answers at once and saves the screenshot Android hands it,
 * then opens this route (`kriko://assist?shot=<file>`). It starts a fresh chat,
 * reads the picture and sends it, so the reader watches their own screen being
 * checked. A scan the floating K could not deliver (Kriko's screen had been
 * closed) arrives the same way.
 */

import * as FileSystem from 'expo-file-system/legacy';
import { router, useLocalSearchParams, type Href } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, PanResponder, StyleSheet, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ProductCard } from '../components/ProductCard';
import { Button } from '../components/Primitives';
import { queueAssistantScan } from '../engine/assistflow';
import { AccessError, useStore } from '../engine/store';
import { discardFrame, keepThumbnail } from '../engine/thumbs';
import { tr } from '../i18n';
import { impact } from '../theme/feedback';
import { ShockWave } from '../components/Shock';
import { elevation, gap, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

type Params = { shot?: string; error?: string; mode?: string; site?: string };

export default function Assist() {
  const params = useLocalSearchParams<Params>();
  const { hydrated, access, readShot, enqueueScan } = useStore();
  const color = useColors();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const { height: screenHeight } = useWindowDimensions();

  // What the assistant is doing, in the order it does it. It cycles on a clock
  // because the reading is one network call with no steps to report; the words
  // are honest about the sequence, not about progress through it.
  const captions = ['Reading your screen', 'Finding the product', 'Checking what is known'];
  const [captionIndex, setCaptionIndex] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setCaptionIndex((index) => (index + 1) % captions.length), 2600);
    return () => clearInterval(id);
  }, [captions.length]);

  // One finger away: dragging the sheet down past a third of a thumb's reach, or
  // flicking it, cancels the reading and returns to the chat. The cleanup of the
  // reading effect below aborts the request when the route leaves.
  const [drag] = useState(() => new Animated.Value(0));
  const [pan] = useState(() => {
    const settle = () => Animated.spring(drag, { toValue: 0, stiffness: 320, damping: 30, mass: 1, useNativeDriver: false }).start();
    return PanResponder.create({
      onMoveShouldSetPanResponder: (_event, g) => g.dy > 8 && Math.abs(g.dy) > Math.abs(g.dx) * 1.5,
      onPanResponderMove: (_event, g) => drag.setValue(Math.max(0, g.dy)),
      onPanResponderRelease: (_event, g) => {
        if (g.dy > 110 || g.vy > 0.6) {
          Animated.timing(drag, { toValue: screenHeight, duration: 200, useNativeDriver: false })
            .start(() => router.replace('/' as Href));
        } else {
          settle();
        }
      },
      onPanResponderTerminate: settle,
    });
  });
  const shot = typeof params.shot === 'string' ? params.shot : '';
  // A failure belongs to the picture it happened to, so a second summoning with
  // a new picture starts without the last one's message.
  const [failed, setFailed] = useState<{ shot: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const handled = useRef('');
  const store = useRef({ readShot, enqueueScan });
  useEffect(() => {
    store.current = { readShot, enqueueScan };
  }, [readShot, enqueueScan]);
  useEffect(() => {
    // One firm tap as the assistant answers, so the summoning is felt as well as seen.
    if (shot) impact();
  }, [shot]);
  const missing = hydrated && access.kind !== 'none' && !shot;
  const failure = missing
    ? tr('Kriko did not receive a screenshot. In your phone’s assistant settings, turn on “Use screenshot”.')
    : failed && failed.shot === shot ? failed.message : '';

  useEffect(() => {
    if (!hydrated) return undefined;
    // Without a way to ask, the front door is the right place to land.
    if (access.kind === 'none') {
      router.replace('/' as Href);
      return undefined;
    }
    if (!shot || handled.current === shot) return undefined;
    handled.current = shot;
    const controller = new AbortController();
    let queued = false;
    void (async () => {
      let base64 = '';
      try {
        base64 = await FileSystem.readAsStringAsync(shot, { encoding: 'base64' });
      } catch {
        if (controller.signal.aborted) return;
        setFailed({ shot, message: tr('Kriko could not read the screenshot your phone sent. Try again.') });
        return;
      }
      try {
        queued = await queueAssistantScan({
          signal: controller.signal,
          read: () => store.current.readShot(base64, 'image/jpeg', controller.signal, shot),
          keep: () => keepThumbnail(shot),
          enqueue: (reading, kept) => store.current.enqueueScan(reading, kept, undefined, {
            researchMode: params.mode === 'site_reviews' ? 'site_reviews' : 'research',
            reviewSite: typeof params.site === 'string' ? params.site : undefined,
          }),
        });
        if (!queued) return;
        router.replace('/queue' as Href);
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof AccessError) {
          router.replace('/' as Href);
          return;
        }
        setFailed({ shot, message: error instanceof Error ? error.message : 'The page could not be read.' });
      } finally {
        if (queued) await discardFrame(shot);
      }
    })();
    return () => {
      controller.abort();
      if (!queued && handled.current === shot) handled.current = '';
    };
  }, [hydrated, access.kind, shot, params.mode, params.site, attempt]);

  const dim = drag.interpolate({ inputRange: [0, 360], outputRange: [1, 0.35], extrapolate: 'clamp' });
  return (
    <View style={styles.root}>
      <Animated.View
        {...pan.panHandlers}
        style={[styles.page, { paddingTop: insets.top + gap[6], opacity: dim, transform: [{ translateY: drag }] }]}
      >
        {shot ? <ProductCard imageUri={shot} scanning={!failure} /> : null}
        {failure ? (
          <View style={styles.text}>
            <Txt variant="cardTitle" tone="ink">Kriko could not finish</Txt>
            <Txt variant="body" tone="ink2">{failure}</Txt>
          </View>
        ) : (
          <View style={styles.status} accessibilityLiveRegion="polite">
            <View style={styles.statusMark}>
              <Txt variant="cardTitle" tone={color.onAccent} translate={false}>K</Txt>
            </View>
            <View style={styles.statusCopy}>
              <Txt variant="cardTitle" tone="ink">{captions[captionIndex]}</Txt>
              <Txt variant="bodyTight" tone="ink2">Research continues in the scan queue and is saved in History.</Txt>
            </View>
            <ActivityIndicator color={color.ink3} />
          </View>
        )}
        {failure ? (
          <View style={styles.text}>
            {shot ? <Button label="Try again" onPress={() => {
              handled.current = '';
              setFailed(null);
              setAttempt((value) => value + 1);
            }} /> : null}
            <Button label="Back to chat" variant="ghost" onPress={() => router.replace('/' as Href)} />
          </View>
        ) : (
          <View style={styles.dismiss}>
            <Txt variant="bodyTight" tone="ink3">Swipe down to cancel</Txt>
            <Button label="Cancel" variant="ghost" onPress={() => router.replace('/' as Href)} />
          </View>
        )}
      </Animated.View>
      {shot && !failure ? <ShockWave playKey={shot} /> : null}
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  root: { flex: 1, backgroundColor: color.ground },
  page: {
    flex: 1,
    backgroundColor: color.ground,
    paddingHorizontal: PAGE_X,
    gap: gap[4],
    alignItems: 'stretch',
  },
  text: { gap: 4 },
  // The status is a reading plate with a mark: glass over a still page would be
  // lit by the shock, so the words sit on the near-opaque surface instead.
  status: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[3],
    padding: gap[4],
    borderRadius: radius.xl,
    backgroundColor: color.plate,
    borderWidth: 1,
    borderColor: color.rim,
    ...elevation.float(color.shadow),
  },
  statusMark: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: color.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  statusCopy: { flex: 1, gap: 2 },
  dismiss: { marginTop: 'auto', paddingBottom: gap[6], gap: gap[2], alignItems: 'stretch' },
}));
