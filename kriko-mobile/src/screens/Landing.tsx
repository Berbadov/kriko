/** The scan-first home screen shown before a conversation begins. */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { plainPreview } from '../engine/preview';
import type { QueueJob } from '../engine/types';
import { tr } from '../i18n';
import { press } from '../theme/feedback';
import { elevation, gap, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { MotionPressable, MotionView } from '../components/Motion';
import { PulseRing } from '../components/Shock';
import { ChevronRightIcon, ImageIcon2, InfoIcon, ScanIcon } from '../components/Icon';
import { FirstRunGuide } from '../components/FirstRunGuide';

const GUIDE_KEY = 'kriko:first-run-guide:complete:v1';

export function Landing({
  onScan,
  onPick,
  recentScans,
  onOpenScan,
}: {
  onScan: () => void;
  onPick: () => void;
  recentScans: QueueJob[];
  onOpenScan: (id: string) => void;
}) {
  const color = useColors();
  const styles = useStyles();
  const recent = recentScans.slice(-2).reverse();
  const [guideVisible, setGuideVisible] = useState(false);

  useEffect(() => {
    let mounted = true;
    void AsyncStorage.getItem(GUIDE_KEY).then((done) => {
      if (mounted && !done) setGuideVisible(true);
    }).catch(() => {
      if (mounted) setGuideVisible(true);
    });
    return () => { mounted = false; };
  }, []);

  const completeGuide = () => {
    setGuideVisible(false);
    void AsyncStorage.setItem(GUIDE_KEY, '1').catch(() => {});
  };

  return (
    <View style={styles.root}>
      <MotionView style={styles.intro}>
        <Txt variant="headline" tone="ink" accessibilityRole="header" style={styles.headline}>
          Check before you buy.
        </Txt>
      </MotionView>

      <MotionView delay={80} style={styles.orbRow}>
        <MotionPressable onPress={onPick} accessibilityRole="button"
          accessibilityLabel={tr('Choose a screenshot')} style={styles.sideButton}>
          <ImageIcon2 size={22} color={color.ink} />
        </MotionPressable>

        <View style={styles.orbBox}>
          <PulseRing color={color.edgeStrong} radius={ORB / 2} />
          <PulseRing color={color.edgeStrong} radius={ORB / 2} delay={1600} />
          <MotionPressable onPress={() => { press(); onScan(); }} accessibilityRole="button"
            accessibilityLabel={tr('Scan a product')} style={styles.orb}>
            <ScanIcon size={48} color={color.ink} strokeWidth={1.5} />
          </MotionPressable>
        </View>

        <MotionPressable onPress={() => setGuideVisible(true)} accessibilityRole="button"
          accessibilityLabel={tr('How Kriko works')} style={styles.sideButton}>
          <InfoIcon size={22} color={color.ink} />
        </MotionPressable>
      </MotionView>

      <MotionView delay={140}>
        <Txt variant="cardTitle" tone="ink" style={styles.orbLabel}>Scan a product</Txt>
      </MotionView>

      {recent.length ? (
        <MotionView delay={200} style={styles.recentBlock}>
          <Txt variant="sectionLabel" tone="ink2">Recently scanned</Txt>
          {recent.map((job) => {
            const title = [job.reading.brand, job.reading.product, job.reading.model].filter(Boolean).join(' ') || 'Product scan';
            return <MotionPressable key={job.id} onPress={() => onOpenScan(job.id)} accessibilityRole="button"
              accessibilityLabel={tr(`Open scan result for ${title}`)} style={styles.recentRow}>
              <View style={styles.recentText}>
                <Txt variant="rowTitle" tone="ink" numberOfLines={1}>{title}</Txt>
                <Txt variant="bodyTight" tone="ink2" numberOfLines={1}>{plainPreview(job.text) || job.error || job.reading.note || 'Open the saved scan'}</Txt>
              </View>
              <ChevronRightIcon size={20} color={color.ink2} />
            </MotionPressable>;
          })}
        </MotionView>
      ) : null}

      {guideVisible ? <FirstRunGuide onComplete={completeGuide} onSkip={completeGuide} /> : null}
    </View>
  );
}

/** The scan orb's diameter. Large on purpose: it is the one thing this screen is for. */
const ORB = 150;

const useStyles = makeStyles((color) => StyleSheet.create({
  root: { flexGrow: 1, paddingHorizontal: PAGE_X, paddingTop: 24, paddingBottom: 30, gap: gap[5] },
  intro: { alignItems: 'flex-start' },
  // Wide enough for "Check before" and no wider, so the line breaks after the
  // verb phrase instead of leaving "buy." alone on the second line.
  headline: { maxWidth: 270 },
  // The screen carries two things: the headline, and one large place to press.
  orbRow: { marginTop: gap[6], flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 30 },
  orbBox: { width: ORB, height: ORB },
  orb: {
    width: ORB,
    height: ORB,
    borderRadius: ORB / 2,
    backgroundColor: color.raise,
    borderWidth: 1.5,
    borderColor: color.rim,
    alignItems: 'center',
    justifyContent: 'center',
    ...elevation.float(color.shadow),
  },
  sideButton: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: color.raise,
    borderWidth: 1,
    borderColor: color.rim,
    alignItems: 'center',
    justifyContent: 'center',
    ...elevation.card(color.shadow),
  },
  orbLabel: { textAlign: 'center' },
  recentBlock: { gap: gap[2], marginTop: gap[3] },
  recentRow: {
    minHeight: 64,
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[3],
    paddingHorizontal: gap[4],
    paddingVertical: gap[3],
    borderRadius: radius.l,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rim,
    ...elevation.card(color.shadow),
  },
  recentText: { flex: 1, gap: 2 },
}));
