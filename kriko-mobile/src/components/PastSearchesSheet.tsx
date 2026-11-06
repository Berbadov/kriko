/**
 * Past searches, kept one press away from the composer.
 *
 * The phone already remembers what the reader researched (the catalog in
 * `src/engine/memory.ts`); this is the way back into it from an open chat and
 * from the sheet. A chip fills the composer with the remembered question and
 * never sends it: the reader still owns the press.
 *
 * The playful cue is the colored icon tile each row carries — a blue wash for a
 * chat, an amber wash for a scan, a green wash for "see all" — drawn from the
 * palette so every theme keeps its own colour, with no gradient.
 */

import { ScrollView, StyleSheet, View } from 'react-native';

import type { CatalogEntry } from '../engine/memory';
import { plainPreview } from '../engine/preview';
import { tr } from '../i18n';
import { gap, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { AnimatedSheet } from './AnimatedSheet';
import { Divider } from './Chrome';
import { ChevronRightIcon, ClockIcon, HistoryIcon, ScanIcon, SearchIcon, XIcon } from './Icon';
import { MotionPressable, MotionView } from './Motion';

/** A translucent version of a palette colour, for the colored tiles. */
function wash(hex: string, alpha: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) return hex;
  const value = Number.parseInt(match[1], 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

/**
 * What a past search fills the composer with: the product it was about and the
 * question asked, or the question alone when they are the same words.
 */
export function pastSearchText(entry: CatalogEntry): string {
  const title = entry.title.replace(/\s+/g, ' ').trim();
  const question = entry.question.replace(/\s+/g, ' ').trim();
  if (title && question) {
    return title.toLocaleLowerCase() === question.toLocaleLowerCase() ? question : `${title}: ${question}`;
  }
  return question || title;
}

/** "2 min ago", "yesterday" — the same wording as History, translated by `Txt`. */
export function pastTime(at: number): string {
  if (!Number.isFinite(at) || at <= 0) return 'date unknown';
  const minutes = Math.max(0, Math.round((Date.now() - at) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}

/** The colored square that names a remembered row's kind. */
function KindTile({ kind, size }: { kind: CatalogEntry['kind']; size: number }) {
  const color = useColors();
  const styles = useStyles();
  const scan = kind === 'scan';
  const icon = Math.round(size * 0.5);
  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[
        styles.tile,
        { width: size, height: size, borderRadius: radius.m },
        scan ? { backgroundColor: wash(color.warn, 0.16) } : { backgroundColor: color.accentSoft },
      ]}
    >
      {scan ? <ScanIcon size={icon} color={color.warn} /> : <SearchIcon size={icon} color={color.accentHi} />}
    </View>
  );
}

/**
 * The slim row above the composer: up to three remembered searches and a way to
 * the whole list. The list scrolls sideways, so a long title never squeezes the
 * chips into unreadable stubs.
 */
export function PastSearchRow({
  entries,
  onPick,
  onSeeAll,
}: {
  entries: CatalogEntry[];
  onPick: (entry: CatalogEntry) => void;
  onSeeAll: () => void;
}) {
  const color = useColors();
  const styles = useStyles();
  if (!entries.length) return null;
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      accessibilityLabel={tr('Past searches')}
      contentContainerStyle={styles.chips}
    >
      {entries.map((entry) => (
        <MotionPressable
          key={entry.key}
          onPress={() => onPick(entry)}
          accessibilityRole="button"
          accessibilityLabel={`${tr('Use past search')}: ${pastSearchText(entry)}`}
          accessibilityHint={tr('Fills the composer without sending.')}
          style={styles.chip}
        >
          <KindTile kind={entry.kind} size={24} />
          <Txt variant="bodyTight" tone="ink" numberOfLines={1} style={styles.chipTitle}>
            {entry.title || entry.question}
          </Txt>
          <Txt variant="monoSm" tone="ink3" numberOfLines={1}>
            {pastTime(entry.updatedAt)}
          </Txt>
        </MotionPressable>
      ))}
      <MotionPressable
        onPress={onSeeAll}
        accessibilityRole="button"
        accessibilityLabel={tr('See all past searches')}
        style={[styles.chip, styles.seeAll]}
      >
        <View style={[styles.tile, styles.seeAllTile, { width: 24, height: 24, borderRadius: radius.m }]}>
          <HistoryIcon size={13} color={color.ok} />
        </View>
        <Txt variant="actionSmall" tone="ink2">See all</Txt>
      </MotionPressable>
    </ScrollView>
  );
}

/**
 * Every remembered row, with its question, time and source count. Picking one
 * hands it back to the composer and closes the sheet.
 */
export function PastSearchesSheet({
  visible,
  entries,
  onClose,
  onPick,
}: {
  visible: boolean;
  entries: CatalogEntry[];
  onClose: () => void;
  onPick: (entry: CatalogEntry) => void;
}) {
  const color = useColors();
  const styles = useStyles();
  return (
    <AnimatedSheet visible={visible} onClose={onClose} style={styles.panel}>
      {(dismiss) => (
        <View style={styles.content}>
          <View style={styles.head}>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">Past searches</Txt>
              <Txt variant="bodyTight" tone="ink3">Tap one to put it back in the composer.</Txt>
            </View>
            <MotionPressable
              onPress={dismiss}
              hitSlop={10}
              accessibilityRole="button"
              accessibilityLabel={tr('Close')}
              style={styles.close}
            >
              <XIcon size={20} color={color.ink2} />
            </MotionPressable>
          </View>

          {entries.length ? (
            <ScrollView
              style={styles.list}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
              contentContainerStyle={styles.rows}
            >
              {entries.map((entry, index) => {
                const question = plainPreview(entry.question);
                return (
                  <MotionView key={entry.key} delay={Math.min(index, 6) * 30} style={styles.rowWrap}>
                    <MotionPressable
                      onPress={() => {
                        onPick(entry);
                        dismiss();
                      }}
                      accessibilityRole="button"
                      accessibilityLabel={`${tr('Use past search')}: ${pastSearchText(entry)}`}
                      accessibilityHint={tr('Fills the composer without sending.')}
                      style={styles.row}
                    >
                      <KindTile kind={entry.kind} size={40} />
                      <View style={styles.rowText}>
                        <Txt variant="rowTitle" tone="ink" numberOfLines={1}>
                          {entry.title || entry.question}
                        </Txt>
                        {question ? (
                          <Txt variant="bodyTight" tone="ink3" numberOfLines={2}>{question}</Txt>
                        ) : null}
                        <View style={styles.meta}>
                          <ClockIcon size={12} color={color.ink3} />
                          <Txt variant="monoSm" tone="ink3">{pastTime(entry.updatedAt)}</Txt>
                          {entry.sources.length ? (
                            <>
                              <Txt variant="monoSm" tone="ink4">·</Txt>
                              <Txt variant="monoSm" tone="ink3">{`Sources · ${entry.sources.length}`}</Txt>
                            </>
                          ) : null}
                        </View>
                      </View>
                      <ChevronRightIcon size={16} color={color.ink3} />
                    </MotionPressable>
                    {index < entries.length - 1 ? <Divider /> : null}
                  </MotionView>
                );
              })}
            </ScrollView>
          ) : (
            <View style={styles.empty}>
              <View style={styles.emptyTile}>
                <HistoryIcon size={22} color={color.ink3} />
              </View>
              <Txt variant="rowTitle" tone="ink" style={styles.emptyTitle}>No past searches yet.</Txt>
              <Txt variant="bodyTight" tone="ink3" style={styles.emptyText}>
                Products you scan or ask about in a chat show up here.
              </Txt>
            </View>
          )}
        </View>
      )}
    </AnimatedSheet>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  chips: { gap: gap[2], paddingVertical: 2, paddingRight: gap[1] },
  chip: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.surface,
  },
  chipTitle: { maxWidth: 150 },
  seeAll: { backgroundColor: color.inset, borderColor: color.edgeSoft },
  tile: { alignItems: 'center', justifyContent: 'center' },
  seeAllTile: { backgroundColor: wash(color.ok, 0.14) },

  panel: { maxHeight: '92%' },
  content: { gap: gap[3], flexShrink: 1 },
  head: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  headText: { flex: 1, gap: 2 },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  list: { flexShrink: 1 },
  rows: { paddingBottom: gap[2] },
  rowWrap: {},
  row: { minHeight: 64, flexDirection: 'row', alignItems: 'center', gap: gap[3], paddingVertical: gap[2] },
  rowText: { flex: 1, gap: 3 },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 5, minHeight: 18 },
  empty: { alignItems: 'center', gap: gap[2], paddingVertical: gap[6] },
  emptyTile: {
    width: 52,
    height: 52,
    borderRadius: radius.l,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.inset,
    borderWidth: 1,
    borderColor: color.edgeSoft,
  },
  emptyTitle: { textAlign: 'center' },
  emptyText: { textAlign: 'center', maxWidth: 280 },
}));
