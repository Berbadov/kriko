/**
 * History in two separate shelves: what you asked in chat, and what a screen
 * read or scan found. They are different kinds of work, so they never share a
 * list; a segmented switch moves between them.
 *
 * Used by the swipe-in drawer on Home and by the History screen.
 */

import { MessageSquare } from 'lucide-react-native';
import { useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';

import { readingTitle } from '../engine/prompt';
import { useStore } from '../engine/store';
import type { QueueJob } from '../engine/types';
import { tr } from '../i18n';
import { gap, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { TrashIcon } from './Icon';
import { ActivityDots, MotionPressable, MotionView } from './Motion';
import { ProductTile, readingIcon } from './ProductIcon';

export function ago(at: number): string {
  if (!Number.isFinite(at) || at <= 0) return 'date unknown';
  const minutes = Math.max(0, Math.round((Date.now() - at) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}

export function scanTitle(job: QueueJob): string {
  return readingTitle(job.reading, true) || 'Product scan';
}

type Shelf = 'chats' | 'scans';

export function HistoryLists({ onOpen, initial = 'chats' }: { onOpen: () => void; initial?: Shelf }) {
  const { threads, queueJobs, activeThread, openThread, openScanResult, deleteThread } = useStore();
  const color = useColors();
  const styles = useStyles();
  const [shelf, setShelf] = useState<Shelf>(initial);

  // A scan's own conversation belongs on the scans shelf, not in chats.
  const scanThreadIds = new Set(queueJobs.flatMap((job) => (job.threadId ? [job.threadId] : [])));
  const chats = threads.filter((thread) => !scanThreadIds.has(thread.id));
  const scans = [...queueJobs].reverse();

  const remove = (id: string, title: string) => {
    Alert.alert(tr('Delete this chat?'), tr(`“${title}” and its sources are removed from this phone.`), [
      { text: tr('Keep'), style: 'cancel' },
      { text: tr('Delete'), style: 'destructive', onPress: () => deleteThread(id) },
    ]);
  };

  const tab = (id: Shelf, label: string, count: number) => {
    const on = shelf === id;
    return (
      <MotionPressable
        key={id}
        onPress={() => setShelf(id)}
        accessibilityRole="tab"
        accessibilityState={{ selected: on }}
        accessibilityLabel={tr(label)}
        style={[styles.tab, on && styles.tabOn]}
      >
        <Txt variant="actionSmall" tone={on ? 'ink' : 'ink3'}>{label}</Txt>
        <Txt variant="monoSm" tone={on ? 'accent' : 'ink4'}>{count}</Txt>
      </MotionPressable>
    );
  };

  return (
    <View style={styles.root}>
      <View style={styles.tabs}>
        {tab('chats', 'Chats', chats.length)}
        {tab('scans', 'Screen reads', scans.length)}
      </View>

      {shelf === 'chats' ? (
        chats.length ? chats.map((thread, index) => {
          const asked = thread.messages.filter((message) => message.role === 'user').length;
          const last = [...thread.messages].reverse().find((message) => message.role === 'user');
          const active = thread.id === activeThread?.id;
          return (
            <MotionView key={thread.id} delay={Math.min(index, 5) * 30} style={styles.rowLine}>
              <MotionPressable
                onPress={() => { openThread(thread.id); onOpen(); }}
                accessibilityRole="button"
                accessibilityLabel={`Open ${thread.title}`}
                style={[styles.row, active && styles.rowActive]}
              >
                <View style={[styles.glyph, { backgroundColor: active ? color.accentSoft : color.raise }]}>
                  <MessageSquare size={17} color={active ? color.accent : color.ink2} strokeWidth={1.7} />
                </View>
                <View style={styles.text}>
                  <Txt variant="rowTitle" tone="ink" numberOfLines={1}>{thread.title}</Txt>
                  {last ? <Txt variant="bodyTight" tone="ink3" numberOfLines={1}>{last.text}</Txt> : null}
                  <Txt variant="monoSm" tone="ink4">
                    {ago(thread.updatedAt)} · {tr(`${asked} question${asked === 1 ? '' : 's'}`)}
                  </Txt>
                </View>
              </MotionPressable>
              <MotionPressable
                onPress={() => remove(thread.id, thread.title)}
                accessibilityRole="button"
                accessibilityLabel={`Delete ${thread.title}`}
                style={styles.delete}
              >
                <TrashIcon size={16} color={color.ink3} />
              </MotionPressable>
            </MotionView>
          );
        }) : (
          <View style={styles.empty}>
            <Txt variant="productTitle" tone="ink">No chats yet.</Txt>
            <Txt variant="bodyTight" tone="ink3">Questions you ask stay here, on this phone.</Txt>
          </View>
        )
      ) : scans.length ? scans.map((job, index) => {
        const linked = Boolean(job.threadId);
        const busy = job.status === 'queued' || job.status === 'running';
        const summary = job.text || job.error || job.reading.note || job.question;
        const active = linked && job.threadId === activeThread?.id;
        return (
          <MotionView key={`${job.id}-${job.status}`} delay={Math.min(index, 5) * 30}>
            <MotionPressable
              onPress={() => { if (linked) { openScanResult(job.id); onOpen(); } }}
              disabled={!linked}
              accessibilityRole={linked ? 'button' : undefined}
              accessibilityLabel={linked ? `Open scan result for ${scanTitle(job)}` : undefined}
              style={[styles.row, active && styles.rowActive]}
            >
              <ProductTile icon={readingIcon(job.reading)} size={42} active={active} />
              <View style={styles.text}>
                <View style={styles.titleLine}>
                  <Txt variant="rowTitle" tone="ink" numberOfLines={1} style={styles.title}>{scanTitle(job)}</Txt>
                  {busy ? <ActivityDots color={color.accent} /> : null}
                </View>
                <Txt variant="bodyTight" tone={job.status === 'error' ? 'risk' : 'ink3'} numberOfLines={2}>{summary}</Txt>
                <Txt variant="monoSm" tone="ink4">{ago(job.updatedAt)}{job.status === 'error' ? ' · failed' : ''}</Txt>
              </View>
            </MotionPressable>
          </MotionView>
        );
      }) : (
        <View style={styles.empty}>
          <Txt variant="productTitle" tone="ink">No screen reads yet.</Txt>
          <Txt variant="bodyTight" tone="ink3">Scan a listing and its findings are kept here, apart from your chats.</Txt>
        </View>
      )}
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  root: { gap: gap[2] },
  tabs: {
    flexDirection: 'row',
    padding: 4,
    gap: 4,
    borderRadius: radius.pill,
    backgroundColor: color.inset,
    marginBottom: gap[1],
  },
  tab: {
    flex: 1,
    minHeight: 40,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    borderRadius: radius.pill,
  },
  tabOn: { backgroundColor: color.raise },
  rowLine: { flexDirection: 'row', alignItems: 'center' },
  row: {
    flex: 1,
    minHeight: 68,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: radius.l,
  },
  rowActive: { backgroundColor: color.accentWash },
  glyph: { width: 42, height: 42, borderRadius: radius.m, alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1, gap: 3 },
  titleLine: { flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  title: { flex: 1 },
  delete: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: radius.m },
  empty: { gap: gap[2], paddingVertical: gap[5], paddingHorizontal: 6 },
}));
