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
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ProductCard } from '../components/ProductCard';
import { Button } from '../components/Primitives';
import { SCREENSHOT_QUESTION } from '../engine/prompt';
import { AccessError, useStore } from '../engine/store';
import { discardFrame, keepThumbnail } from '../engine/thumbs';
import { tr } from '../i18n';
import { gap, PAGE_X } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

type Params = { shot?: string; error?: string; mode?: string; site?: string };

export default function Assist() {
  const params = useLocalSearchParams<Params>();
  const { hydrated, access, newChat, readShot, send, enqueueScan } = useStore();
  const color = useColors();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const shot = typeof params.shot === 'string' ? params.shot : '';
  // A failure belongs to the picture it happened to, so a second summoning with
  // a new picture starts without the last one's message.
  const [failed, setFailed] = useState<{ shot: string; message: string } | null>(null);
  const handled = useRef('');
  const store = useRef({ newChat, readShot, send, enqueueScan });
  useEffect(() => {
    store.current = { newChat, readShot, send, enqueueScan };
  }, [newChat, readShot, send, enqueueScan]);
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
    void (async () => {
      let base64 = '';
      try {
        base64 = await FileSystem.readAsStringAsync(shot, { encoding: 'base64' });
      } catch {
        setFailed({ shot, message: tr('Kriko could not read the screenshot your phone sent. Try again.') });
        return;
      }
      try {
        const reading = await store.current.readShot(base64, 'image/jpeg', controller.signal, shot);
        const kept = await keepThumbnail(shot);
        if (params.mode === 'site_reviews') {
          store.current.enqueueScan(reading, kept, undefined, {
            researchMode: 'site_reviews', reviewSite: typeof params.site === 'string' ? params.site : undefined,
          });
          router.replace('/queue' as Href);
          return;
        }
        // Every open of the assistant starts clean: this scan is its own chat.
        store.current.newChat();
        router.replace('/' as Href);
        await store.current.send(SCREENSHOT_QUESTION, { reading, imageUri: kept });
      } catch (error) {
        if (error instanceof AccessError) {
          router.replace('/' as Href);
          return;
        }
        setFailed({ shot, message: error instanceof Error ? error.message : 'The page could not be read.' });
      } finally {
        await discardFrame(shot);
      }
    })();
    return () => controller.abort();
  }, [hydrated, access.kind, shot, params.mode, params.site]);

  return (
    <View style={[styles.page, { paddingTop: insets.top + gap[6] }]}>
      {shot ? <ProductCard imageUri={shot} scanning={!failure} /> : null}
      <View style={styles.text}>
        <Txt variant="rowTitle" tone="ink">{failure ? 'Kriko could not finish' : 'Reading your screen'}</Txt>
        <Txt variant="bodyTight" tone="ink3">
          {failure || 'Kriko is checking the page you were on. The answer opens in a new chat.'}
        </Txt>
      </View>
      {failure ? (
        <Button label="Back to chat" variant="ghost" onPress={() => router.replace('/' as Href)} />
      ) : (
        <ActivityIndicator color={color.ink3} />
      )}
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: color.ground,
    paddingHorizontal: PAGE_X,
    gap: gap[4],
    alignItems: 'stretch',
  },
  text: { gap: 4 },
}));
