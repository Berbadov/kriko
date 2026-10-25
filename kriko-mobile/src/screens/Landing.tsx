/** The scan-first home screen shown before a conversation begins. */

import { StyleSheet, View } from 'react-native';

import type { QueueJob } from '../engine/types';
import { tr } from '../i18n';
import { press, tap } from '../theme/feedback';
import { font, gap, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { MotionPressable, MotionView } from '../components/Motion';
import { ChevronRightIcon, ImageIcon2, ScanIcon, SearchIcon } from '../components/Icon';

const SUGGESTIONS = [
  'What do owners report about the Bosch GSB 600?',
  'Are used Galaxy Buds2 Pro worth $90?',
] as const;

export function Landing({
  onSuggestion,
  onScan,
  onPick,
  recentScans,
  onOpenScan,
}: {
  onSuggestion: (text: string) => void;
  onScan: () => void;
  onPick: () => void;
  recentScans: QueueJob[];
  onOpenScan: (id: string) => void;
}) {
  const color = useColors();
  const styles = useStyles();
  const recent = recentScans.slice(-2).reverse();

  return (
    <View style={styles.root}>
      <MotionView style={styles.intro}>
        <Txt variant="crumb" tone="ink3" style={styles.eyebrow}>
          BUY WITH A CLEARER PICTURE
        </Txt>
        <Txt variant="headline" tone="ink" accessibilityRole="header" style={styles.headline}>
          Take a closer look.
        </Txt>
        <Txt variant="heroSub" tone="ink2" style={styles.subtitle}>
          Scan a listing or ask a question. Kriko checks the details against independent sources.
        </Txt>
      </MotionView>

      <MotionView delay={80} style={styles.actions}>
        <MotionPressable
          onPress={() => {
            press();
            onScan();
          }}
          accessibilityRole="button"
          accessibilityLabel={tr('Scan a product')}
          style={styles.scanButton}
        >
          <View style={styles.scanIcon}>
            <ScanIcon size={20} color={color.onAccent} strokeWidth={1.8} />
          </View>
          <View style={styles.scanCopy}>
            <Txt variant="action" tone={color.onAccent} style={styles.scanTitle}>
              Scan a product
            </Txt>
            <Txt variant="bodyTight" tone="rgba(255,255,255,0.78)" style={styles.scanSub}>
              Read the page open on your phone
            </Txt>
          </View>
          <ChevronRightIcon size={19} color="rgba(255,255,255,0.82)" />
        </MotionPressable>

        <MotionPressable
          onPress={onPick}
          accessibilityRole="button"
          accessibilityLabel={tr('Choose a screenshot')}
          style={styles.pickRow}
        >
          <ImageIcon2 size={18} color={color.ink2} />
          <Txt variant="rowText" tone="ink" style={styles.pickLabel}>
            Choose a screenshot instead
          </Txt>
          <ChevronRightIcon size={17} color={color.ink3} />
        </MotionPressable>
      </MotionView>

      <MotionView delay={160} style={styles.suggestionsBlock}>
        <View style={styles.sectionHeading}>
          <Txt variant="sectionLabel" tone="ink3">Or start with a question</Txt>
          <View style={styles.rule} />
        </View>
        {SUGGESTIONS.map((text, index) => (
          <MotionPressable
            key={text}
            onPress={() => {
              tap();
              onSuggestion(text);
            }}
            accessibilityRole="button"
            accessibilityLabel={text}
            style={styles.suggestion}
          >
            <SearchIcon size={15} color={color.ink3} />
            <Txt variant="bodyTight" tone="ink" style={styles.suggestionText}>{text}</Txt>
            <Txt variant="monoSm" tone="ink4">0{index + 1}</Txt>
          </MotionPressable>
        ))}
      </MotionView>

      {recent.length ? (
        <MotionView delay={240} style={styles.recentBlock}>
          <View style={styles.sectionHeading}>
            <Txt variant="sectionLabel" tone="ink3">Recently scanned</Txt>
            <View style={styles.rule} />
          </View>
          {recent.map((job) => {
            const title = [job.reading.brand, job.reading.product, job.reading.model]
              .filter(Boolean)
              .join(' ') || 'Product scan';
            return (
              <MotionPressable
                key={job.id}
                onPress={() => onOpenScan(job.id)}
                accessibilityRole="button"
                accessibilityLabel={tr(`Open scan result for ${title}`)}
                style={styles.recentRow}
              >
                <View style={styles.recentText}>
                  <Txt variant="rowTitle" tone="ink" numberOfLines={1}>{title}</Txt>
                  <Txt variant="bodyTight" tone="ink3" numberOfLines={1}>
                    {job.text || job.error || job.reading.note || 'Open the saved scan'}
                  </Txt>
                </View>
                <ChevronRightIcon size={17} color={color.ink3} />
              </MotionPressable>
            );
          })}
        </MotionView>
      ) : null}

      <MotionView delay={320} style={styles.footerNote}>
        <View style={styles.footerDot} />
        <Txt variant="monoSm" tone="ink3">Evidence first. Clear about what is missing.</Txt>
      </MotionView>
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  root: {
    flexGrow: 1,
    paddingHorizontal: PAGE_X,
    paddingTop: 24,
    paddingBottom: 30,
    gap: gap[5],
  },
  intro: { gap: 8, alignItems: 'flex-start' },
  eyebrow: { letterSpacing: 1.05, marginBottom: 3 },
  headline: {
    fontFamily: font.editorial,
    letterSpacing: -1.05,
    maxWidth: 330,
  },
  subtitle: { maxWidth: 330, lineHeight: 23 },
  actions: { gap: gap[1] },
  scanButton: {
    minHeight: 78,
    borderRadius: radius.l,
    paddingHorizontal: 15,
    paddingVertical: 13,
    backgroundColor: color.accent,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  scanIcon: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.15)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  scanCopy: { flex: 1, gap: 3 },
  scanTitle: { textTransform: 'none', fontSize: 16 },
  scanSub: { fontSize: 12.5, lineHeight: 17 },
  pickRow: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: color.edge,
  },
  pickLabel: { flex: 1 },
  suggestionsBlock: { gap: 4 },
  sectionHeading: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 4 },
  rule: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: color.edge },
  suggestion: {
    minHeight: 46,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: color.edge,
    paddingHorizontal: 4,
  },
  suggestionText: { flex: 1 },
  recentBlock: { gap: 4 },
  recentRow: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: color.edge,
    paddingVertical: 8,
  },
  recentText: { flex: 1, gap: 2 },
  footerNote: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingTop: 2 },
  footerDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: color.accent },
}));
