/**
 * The page that was scanned, as the desktop shows a listing: a small picture
 * beside the product's name, its price and the site it was read from.
 *
 * The picture is the scan's own thumbnail. While the answer is still being
 * written a light sweeps down it, so the reader sees the scan is working; with
 * reduced motion the picture simply sits there. Tapping it opens it full size.
 */

import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { useEffect, useState } from 'react';
import { Animated, Easing, Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { readingTitle } from '../engine/prompt';
import type { Reading } from '../engine/types';
import { tr } from '../i18n';
import { gap, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { GlobeIcon, ScanIcon, XIcon } from './Icon';
import { MotionPressable, MotionView, useReducedMotion } from './Motion';

const PICTURE_W = 68;
const PICTURE_H = 92;
const SWEEP_H = 26;

/** "used" → "Used"; the model's `unknown` is not worth a word. */
function conditionWord(condition: string | undefined): string {
  if (!condition || condition === 'unknown') return '';
  return condition.charAt(0).toUpperCase() + condition.slice(1);
}

export function ProductCard({
  reading,
  imageUri,
  scanning = false,
}: {
  reading?: Reading;
  imageUri?: string;
  /** The answer for this page is still being written. */
  scanning?: boolean;
}) {
  const color = useColors();
  const styles = useStyles();
  const reduced = useReducedMotion();
  const [viewing, setViewing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [sweep] = useState(() => new Animated.Value(0));
  const picture = imageUri && !failed ? imageUri : '';
  const animate = scanning && Boolean(picture) && reduced === false;

  useEffect(() => {
    sweep.stopAnimation();
    sweep.setValue(0);
    if (!animate) return;
    const loop = Animated.loop(
      Animated.timing(sweep, {
        toValue: 1,
        duration: 1500,
        easing: Easing.inOut(Easing.quad),
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [animate, sweep]);

  const title = reading ? readingTitle(reading, true) : '';
  const meta = [reading?.price, conditionWord(reading?.condition)].filter(Boolean).join(' · ');
  const site = reading?.site?.trim() ?? '';

  return (
    <MotionView style={styles.card}>
      <MotionPressable
        onPress={() => { if (picture) setViewing(true); }}
        disabled={!picture}
        accessibilityRole="imagebutton"
        accessibilityLabel={tr('Open the scanned picture')}
        style={[styles.picture, scanning && picture ? styles.pictureLive : null]}
      >
        {picture ? (
          <Image
            source={{ uri: picture }}
            style={StyleSheet.absoluteFill}
            contentFit="cover"
            contentPosition={{ top: 0, left: '50%' }}
            transition={180}
            onError={() => setFailed(true)}
          />
        ) : (
          <ScanIcon size={22} color={color.ink3} />
        )}
        {animate ? (
          <Animated.View
            pointerEvents="none"
            style={[
              styles.sweep,
              {
                transform: [{
                  translateY: sweep.interpolate({
                    inputRange: [0, 1],
                    outputRange: [-SWEEP_H, PICTURE_H],
                  }),
                }],
              },
            ]}
          >
            <LinearGradient
              colors={['transparent', color.accentHi, 'transparent']}
              locations={[0, 0.85, 1]}
              style={StyleSheet.absoluteFill}
            />
            <View style={[styles.sweepLine, { backgroundColor: color.accentHi }]} />
          </Animated.View>
        ) : null}
      </MotionPressable>

      <View style={styles.info}>
        <Txt variant="sectionLabel" tone="ink3" caps>{tr('Scanned page')}</Txt>
        <Txt variant="cardTitle" tone="ink" numberOfLines={2}>
          {title || tr('Product scan')}
        </Txt>
        {meta ? <Txt variant="monoSm" tone="ink2" numberOfLines={1} translate={false}>{meta}</Txt> : null}
        {site ? (
          <View style={styles.siteRow}>
            <GlobeIcon size={12} color={color.ink3} />
            <Txt variant="monoSm" tone="ink3" numberOfLines={1} translate={false} style={styles.site}>{site}</Txt>
          </View>
        ) : null}
        {scanning ? (
          <Txt variant="monoSm" tone="accentHi" numberOfLines={1}>{tr('Checking this page')}</Txt>
        ) : null}
      </View>

      {viewing && picture ? <PictureViewer uri={picture} onClose={() => setViewing(false)} /> : null}
    </MotionView>
  );
}

/** The picture at full size over a dark scrim; a tap anywhere closes it. */
function PictureViewer({ uri, onClose }: { uri: string; onClose: () => void }) {
  const color = useColors();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable
        style={styles.viewer}
        onPress={onClose}
        accessibilityRole="button"
        accessibilityLabel={tr('Close the picture')}
      >
        <Image source={{ uri }} style={styles.viewerImage} contentFit="contain" transition={160} />
        <View style={[styles.viewerClose, { top: insets.top + 10 }]}>
          <XIcon size={20} color={color.onAccent} />
        </View>
      </Pressable>
    </Modal>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  card: {
    alignSelf: 'stretch',
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[3],
    padding: 10,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.surface,
  },
  picture: {
    width: PICTURE_W,
    height: PICTURE_H,
    borderRadius: 10,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.inset,
    borderWidth: 1,
    borderColor: color.edgeSoft,
  },
  pictureLive: { borderColor: color.accent },
  sweep: { position: 'absolute', left: 0, right: 0, top: 0, height: SWEEP_H, opacity: 0.55 },
  sweepLine: { position: 'absolute', left: 0, right: 0, bottom: 4, height: 1.5, opacity: 0.9 },
  info: { flex: 1, gap: 3 },
  siteRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  site: { flex: 1 },
  viewer: { flex: 1, backgroundColor: color.scrim, alignItems: 'center', justifyContent: 'center' },
  viewerImage: { width: '100%', height: '100%' },
  viewerClose: {
    position: 'absolute',
    right: 16,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
  },
}));
