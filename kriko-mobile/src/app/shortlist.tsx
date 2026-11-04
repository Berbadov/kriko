import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Divider, HeaderAction, Hero, Page } from '../components/Chrome';
import { MotionPressable, MotionView } from '../components/Motion';
import { BackIcon, CheckCircleIcon, ClockIcon, PlusIcon, TrashIcon } from '../components/Icon';
import { Button, Chip, ProgressBar, SectionLabel, Segmented } from '../components/Primitives';
import { buildCatalog } from '../engine/memory';
import { loadPriceWatches, type PriceWatch } from '../engine/priceTracking';
import {
  addShortlistItem,
  currentPrice,
  DEFAULT_WEIGHTS,
  loadShortlist,
  matchWatch,
  priceDropStatus,
  rankShortlist,
  removeFromShortlist,
  WEIGHT_LEVELS,
  type DecisionWeights,
  type RankReason,
  type ShortlistItem,
  type WeightLevel,
} from '../engine/shortlist';
import { useStore } from '../engine/store';
import { tr } from '../i18n';
import { gap, PAGE_X } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

function ago(at: number): string {
  if (!Number.isFinite(at) || at <= 0) return 'date unknown';
  const minutes = Math.max(0, Math.round((Date.now() - at) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}

function reasonLabel(reason: RankReason): string {
  if (reason === 'price') return tr('lowest price');
  if (reason === 'evidence') return tr('most sources');
  return tr('added most recently');
}

const WEIGHT_OPTIONS: { value: WeightLevel; label: string }[] = WEIGHT_LEVELS.map((value) => ({
  value,
  label: value === 'low' ? 'Low' : value === 'standard' ? 'Standard' : 'High',
}));

export default function Shortlist() {
  const { threads, queueJobs, activeThread, openThread } = useStore();
  const color = useColors();
  const styles = useStyles();
  const [items, setItems] = useState<ShortlistItem[]>([]);
  const [watches, setWatches] = useState<PriceWatch[]>([]);
  const [weights, setWeights] = useState<DecisionWeights>(DEFAULT_WEIGHTS);

  useEffect(() => {
    let mounted = true;
    loadShortlist().then((rows) => { if (mounted) setItems(rows); });
    loadPriceWatches().then((rows) => { if (mounted) setWatches(rows); });
    return () => { mounted = false; };
  }, []);

  const catalog = useMemo(() => buildCatalog(threads, queueJobs), [threads, queueJobs]);
  const ranked = useMemo(() => rankShortlist(items, catalog, watches, weights), [items, catalog, watches, weights]);
  const onList = useMemo(() => new Set(items.map((item) => item.key)), [items]);
  const addable = useMemo(() => catalog.filter((entry) => !onList.has(entry.key)), [catalog, onList]);

  const open = (id: string) => { openThread(id); router.replace('/'); };
  const add = (entry: (typeof catalog)[number]) => {
    const watch = matchWatch({ title: entry.title }, watches);
    void addShortlistItem({
      key: entry.key,
      title: entry.title,
      threadId: entry.threadId,
      savedPrice: watch?.lastPrice ?? null,
      currency: watch?.currency,
    }).then(setItems);
  };
  const remove = (id: string) => { void removeFromShortlist(id).then(setItems); };
  const setWeight = (key: keyof DecisionWeights) => (value: WeightLevel) => setWeights((current) => ({ ...current, [key]: value }));

  const weightRow = (key: keyof DecisionWeights, label: string) => (
    <View key={key} style={styles.weightRow}>
      <Txt variant="bodyTight" tone="ink" style={styles.weightLabel}>{label}</Txt>
      <Segmented options={WEIGHT_OPTIONS} value={weights[key]} onChange={setWeight(key)} />
    </View>
  );

  return (
    <Page artHeight={0} actions={<HeaderAction label="Back" onPress={() => router.back()}><BackIcon size={21} color={color.ink} /></HeaderAction>}>
      <Hero crumb="kriko / your shortlist" title="Shortlist" subtitle="The products you are deciding between, with the price drops Kriko has seen." />

      <View style={styles.body}>
        {ranked.length >= 2 ? (
          <MotionView delay={40} style={styles.section}>
            <View style={styles.sectionHead}>
              <SectionLabel>Help me decide</SectionLabel>
              <Txt variant="monoSm" tone="ink3" caps>{ranked.length}</Txt>
            </View>
            <Txt variant="bodyTight" tone="ink3" style={styles.weightsHint}>What matters most</Txt>
            <View style={styles.weights}>
              {weightRow('price', 'Price')}
              {weightRow('evidence', 'Evidence')}
              {weightRow('recency', 'Recency')}
            </View>
            {ranked.map((row, index) => (
              <MotionView key={row.item.id} delay={60 + Math.min(index, 4) * 35} style={styles.rankWrap}>
                <View style={styles.rowLine}>
                  <MotionPressable
                    onPress={() => row.item.threadId && open(row.item.threadId)}
                    disabled={!row.item.threadId}
                    accessibilityRole={row.item.threadId ? 'button' : undefined}
                    accessibilityLabel={row.item.threadId ? `Open the chat about ${row.item.title}` : undefined}
                    style={styles.row}
                  >
                    <View style={styles.rowText}>
                      <View style={styles.titleLine}>
                        <Txt variant="rowTitle" tone="ink" numberOfLines={1} style={styles.title}>{row.item.title}</Txt>
                        {index === 0 ? <Chip label="#1 pick" tone="accent" size="sm" /> : null}
                      </View>
                      <ProgressBar value={row.score} />
                      {row.reasons.length ? (
                        <Txt variant="monoSm" tone="ink3">{row.reasons.map(reasonLabel).join(' · ')}</Txt>
                      ) : null}
                    </View>
                  </MotionPressable>
                </View>
                {index < ranked.length - 1 ? <Divider inset={0} /> : null}
              </MotionView>
            ))}
          </MotionView>
        ) : null}

        <MotionView delay={60} style={styles.section}>
          <View style={styles.sectionHead}>
            <SectionLabel>On your shortlist</SectionLabel>
            <Txt variant="monoSm" tone="ink3" caps>{items.length}</Txt>
          </View>
          {!items.length ? (
            <View style={styles.empty}>
              <Txt variant="productTitle" tone="ink">Nothing on your shortlist yet.</Txt>
              <Txt variant="body" tone="ink3">Add the products you are deciding between from the list below.</Txt>
            </View>
          ) : null}
          {items.map((item, index) => {
            const watch = matchWatch(item, watches);
            const drop = priceDropStatus(item, watch);
            const known = currentPrice(item, watch);
            const chip = drop.kind === 'drop'
              ? { label: tr(`Price dropped ${drop.percent}%`), tone: 'ok' as const }
              : watch
                ? { label: 'Watched', tone: 'neutral' as const }
                : { label: 'No price yet', tone: 'neutral' as const };
            const active = Boolean(item.threadId) && item.threadId === activeThread?.id;
            return (
              <MotionView key={item.id} delay={80 + Math.min(index, 4) * 35} style={styles.rowWrap}>
                <View style={styles.rowLine}>
                  <MotionPressable
                    onPress={() => item.threadId && open(item.threadId)}
                    disabled={!item.threadId}
                    accessibilityRole={item.threadId ? 'button' : undefined}
                    accessibilityLabel={item.threadId ? `Open the chat about ${item.title}` : undefined}
                    style={styles.row}
                  >
                    <View style={styles.rowText}>
                      <View style={styles.titleLine}>
                        <Txt variant="rowTitle" tone="ink" numberOfLines={1} style={styles.title}>{item.title}</Txt>
                        {active ? <Chip label="Open" tone="accent" size="sm" /> : <Chip label={chip.label} tone={chip.tone} size="sm" />}
                      </View>
                      <View style={styles.meta}>
                        <ClockIcon size={13} color={color.ink3} />
                        <Txt variant="monoSm" tone="ink3">{ago(item.addedAt)}{known.price ? ` · ${known.currency} ${known.price}` : ''}</Txt>
                      </View>
                    </View>
                  </MotionPressable>
                  <MotionPressable onPress={() => remove(item.id)} accessibilityRole="button" accessibilityLabel={`Remove ${item.title}`} style={styles.delete}>
                    <TrashIcon size={16} color={color.ink3} />
                  </MotionPressable>
                </View>
                {index < items.length - 1 ? <Divider inset={0} /> : null}
              </MotionView>
            );
          })}
        </MotionView>

        <MotionView delay={110} style={styles.section}>
          <View style={styles.sectionHead}>
            <SectionLabel>Add from what Kriko remembers</SectionLabel>
            <Txt variant="monoSm" tone="ink3" caps>{addable.length}</Txt>
          </View>
          {!addable.length ? (
            <View style={styles.empty}>
              <Txt variant="productTitle" tone="ink">No remembered products yet.</Txt>
              <Txt variant="body" tone="ink3">Ask or scan a product first, and it appears here.</Txt>
            </View>
          ) : null}
          {addable.map((entry, index) => (
            <MotionView key={entry.key} delay={130 + Math.min(index, 4) * 35} style={styles.rowWrap}>
              <View style={styles.rowLine}>
                <View style={[styles.row, styles.rowText]}>
                  <View style={styles.titleLine}>
                    <Txt variant="rowTitle" tone="ink" numberOfLines={1} style={styles.title}>{entry.title}</Txt>
                    <CheckCircleIcon size={15} color={color.ink3} />
                  </View>
                </View>
                <Button label="Add" variant="quiet" icon={<PlusIcon size={15} color={color.ink} />} onPress={() => add(entry)} />
              </View>
              {index < addable.length - 1 ? <Divider inset={0} /> : null}
            </MotionView>
          ))}
        </MotionView>
      </View>
    </Page>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  body: { paddingHorizontal: PAGE_X, gap: gap[5], paddingBottom: 44 },
  empty: { gap: gap[2], paddingVertical: gap[5] },
  section: { gap: gap[2] },
  sectionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingBottom: gap[1] },
  weightsHint: { paddingBottom: gap[1] },
  weights: { gap: gap[2], paddingBottom: gap[2] },
  weightRow: { flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  weightLabel: { width: 84 },
  rowWrap: { gap: gap[1] },
  rankWrap: { gap: gap[1] },
  rowLine: { flexDirection: 'row', alignItems: 'center', gap: gap[1] },
  row: { minHeight: 68, flexDirection: 'row', alignItems: 'center', gap: gap[2], paddingVertical: gap[2], flex: 1 },
  rowText: { flex: 1, gap: 4 },
  titleLine: { minHeight: 32, flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  title: { flex: 1 },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 20 },
  delete: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
}));
