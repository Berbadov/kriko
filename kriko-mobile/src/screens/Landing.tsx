/** The scan-first home screen shown before a conversation begins. */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { plainPreview } from '../engine/preview';
import type { QueueJob } from '../engine/types';
import { tr } from '../i18n';
import { press } from '../theme/feedback';
import { font, gap, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { MotionPressable, MotionView } from '../components/Motion';
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
        <View style={styles.headingRow}>
          <Txt variant="headline" tone="ink" accessibilityRole="header" style={styles.headline}>
            Check before you buy.
          </Txt>
          <MotionPressable onPress={() => setGuideVisible(true)} accessibilityRole="button"
            accessibilityLabel={tr('How Kriko works')} style={styles.helpButton}>
            <InfoIcon size={19} color={color.ink2} />
          </MotionPressable>
        </View>
        <Txt variant="heroSub" tone="ink2" style={styles.subtitle}>
          Scan a product to see the details and sources behind it.
        </Txt>
      </MotionView>

      <MotionView delay={80} style={styles.actions}>
        <MotionPressable onPress={() => { press(); onScan(); }} accessibilityRole="button"
          accessibilityLabel={tr('Scan a product')} style={styles.scanButton}>
          <View style={styles.scanIcon}><ScanIcon size={20} color={color.onAccent} strokeWidth={1.8} /></View>
          <View style={styles.scanCopy}>
            <Txt variant="action" tone={color.onAccent} style={styles.scanTitle}>Scan a product</Txt>
            <Txt variant="bodyTight" tone="rgba(255,255,255,0.78)" style={styles.scanSub}>Read the page open on your phone</Txt>
          </View>
          <ChevronRightIcon size={19} color="rgba(255,255,255,0.82)" />
        </MotionPressable>

        <MotionPressable onPress={onPick} accessibilityRole="button"
          accessibilityLabel={tr('Choose a screenshot')} style={styles.pickRow}>
          <ImageIcon2 size={18} color={color.ink2} />
          <Txt variant="rowText" tone="ink" style={styles.pickLabel}>Choose a screenshot instead</Txt>
          <ChevronRightIcon size={17} color={color.ink3} />
        </MotionPressable>
      </MotionView>

      {recent.length ? (
        <MotionView delay={160} style={styles.recentBlock}>
          <View style={styles.sectionHeading}>
            <Txt variant="sectionLabel" tone="ink3">Recently scanned</Txt><View style={styles.rule} />
          </View>
          {recent.map((job) => {
            const title = [job.reading.brand, job.reading.product, job.reading.model].filter(Boolean).join(' ') || 'Product scan';
            return <MotionPressable key={job.id} onPress={() => onOpenScan(job.id)} accessibilityRole="button"
              accessibilityLabel={tr(`Open scan result for ${title}`)} style={styles.recentRow}>
              <View style={styles.recentText}>
                <Txt variant="rowTitle" tone="ink" numberOfLines={1}>{title}</Txt>
                <Txt variant="bodyTight" tone="ink3" numberOfLines={1}>{plainPreview(job.text) || job.error || job.reading.note || 'Open the saved scan'}</Txt>
              </View>
              <ChevronRightIcon size={17} color={color.ink3} />
            </MotionPressable>;
          })}
        </MotionView>
      ) : null}

      {guideVisible ? <FirstRunGuide onComplete={completeGuide} onSkip={completeGuide} /> : null}
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  root: { flexGrow: 1, paddingHorizontal: PAGE_X, paddingTop: 24, paddingBottom: 30, gap: gap[5] },
  intro: { gap: 8, alignItems: 'flex-start' },
  headingRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  headline: { fontFamily: font.editorial, letterSpacing: -1.05, maxWidth: 310, flex: 1 },
  helpButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill },
  subtitle: { maxWidth: 330, lineHeight: 23 },
  actions: { gap: gap[1] },
  scanButton: { minHeight: 78, borderRadius: radius.l, paddingHorizontal: 15, paddingVertical: 13, backgroundColor: color.accent, flexDirection: 'row', alignItems: 'center', gap: 12 },
  scanIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: 'rgba(255,255,255,0.15)', alignItems: 'center', justifyContent: 'center' },
  scanCopy: { flex: 1, gap: 3 }, scanTitle: { textTransform: 'none', fontSize: 16 }, scanSub: { fontSize: 12.5, lineHeight: 17 },
  pickRow: { minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: color.edge },
  pickLabel: { flex: 1 }, sectionHeading: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 4 },
  rule: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: color.edge }, recentBlock: { gap: 4 },
  recentRow: { minHeight: 56, flexDirection: 'row', alignItems: 'center', gap: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: color.edge, paddingVertical: 8 },
  recentText: { flex: 1, gap: 2 },
}));
