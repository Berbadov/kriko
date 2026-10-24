import { Alert, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { useStore } from '../engine/store';
import type { QueueJob } from '../engine/types';
import { tr } from '../i18n';
import { color, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { ActivityDots, MotionView } from './Motion';
import { PlusIcon, TrashIcon, XIcon } from './Icon';
import { Divider } from './Chrome';
import { Button, Chip, SectionLabel } from './Primitives';

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

function scanTitle(job: QueueJob): string {
  return [job.reading.brand, job.reading.product, job.reading.model].filter(Boolean).join(' ') || 'Product scan';
}

export function HistorySheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const { threads, queueJobs, activeId, openThread, openScanResult, newChat, deleteThread } = useStore();
  const scanThreadIds = new Set(queueJobs.flatMap((job) => job.threadId ? [job.threadId] : []));
  const conversations = threads.filter((thread) => !scanThreadIds.has(thread.id));

  const remove = (id: string, title: string) => {
    Alert.alert(tr('Delete this chat?'), tr(`“${title}” and its sources are removed from this phone.`), [
      { text: tr('Keep'), style: 'cancel' },
      { text: tr('Delete'), style: 'destructive', onPress: () => deleteThread(id) },
    ]);
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.wrap}>
        <Pressable style={styles.scrim} onPress={onClose} accessibilityLabel={tr('Close history')} />
        <View style={styles.sheet}>
          <View style={styles.grab} />
          <View style={styles.head}>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">History</Txt>
              <Txt variant="bodyTight" tone="ink3">Your chats and product scans.</Txt>
            </View>
            <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close history')} style={styles.close}>
              <XIcon size={20} color={color.ink2} />
            </Pressable>
          </View>

          <Button label="New conversation" variant="quiet" icon={<PlusIcon size={17} color={color.ink} />} onPress={() => { newChat(); onClose(); }} />

          <ScrollView style={styles.scroll} contentContainerStyle={styles.list} showsVerticalScrollIndicator={false}>
            {conversations.length ? (
              <MotionView delay={0} style={styles.section}>
                <SectionLabel>Conversations</SectionLabel>
                {conversations.map((thread, index) => {
                  const active = thread.id === activeId;
                  const count = thread.messages.filter((message) => message.role === 'user').length;
                  const last = [...thread.messages].reverse().find((message) => message.role === 'user');
                  return (
                    <MotionView key={thread.id} delay={Math.min(index, 4) * 35} style={styles.rowWrap}>
                      <View style={styles.rowLine}>
                        <Pressable onPress={() => { openThread(thread.id); onClose(); }} style={({ pressed }) => [styles.row, pressed && styles.pressed]} accessibilityRole="button" accessibilityLabel={`Open ${thread.title}`}>
                          <View style={styles.rowText}>
                            <View style={styles.titleLine}>
                              <Txt variant="rowTitle" tone="ink" numberOfLines={1} style={styles.title}>{thread.title}</Txt>
                              {active ? <Chip label="Open" tone="accent" size="sm" /> : null}
                            </View>
                            {last ? <Txt variant="bodyTight" tone="ink3" numberOfLines={1}>{last.text}</Txt> : null}
                            <Txt variant="monoSm" tone="ink3">{count} {count === 1 ? 'question' : 'questions'} · {ago(thread.updatedAt)}</Txt>
                          </View>
                        </Pressable>
                        <Pressable onPress={() => remove(thread.id, thread.title)} accessibilityRole="button" accessibilityLabel={`Delete ${thread.title}`} style={styles.delete}>
                          <TrashIcon size={16} color={color.ink3} />
                        </Pressable>
                      </View>
                      {index < conversations.length - 1 ? <Divider /> : null}
                    </MotionView>
                  );
                })}
              </MotionView>
            ) : null}

            {queueJobs.length ? (
              <MotionView delay={80} style={styles.section}>
                <SectionLabel>Scanned products</SectionLabel>
                {[...queueJobs].reverse().map((job, index, all) => {
                  const linked = Boolean(job.threadId);
                  const busy = job.status === 'queued' || job.status === 'running';
                  const summary = job.text || job.error || job.reading.note || job.question;
                  return (
                    <MotionView key={job.id} delay={Math.min(index, 4) * 35} style={styles.rowWrap}>
                      <Pressable onPress={() => { if (linked) { openScanResult(job.id); onClose(); } }} disabled={!linked} style={({ pressed }) => [styles.row, pressed && styles.pressed]} accessibilityRole={linked ? 'button' : undefined} accessibilityLabel={linked ? `Open scan result for ${scanTitle(job)}` : undefined}>
                        <View style={styles.rowText}>
                          <View style={styles.titleLine}>
                            <Txt variant="rowTitle" tone="ink" numberOfLines={1} style={styles.title}>{scanTitle(job)}</Txt>
                            {busy ? <ActivityDots color={color.accent} /> : <Chip label={job.status} tone={job.status === 'error' ? 'risk' : job.status === 'done' ? 'ok' : 'neutral'} size="sm" />}
                          </View>
                          <Txt variant="bodyTight" tone={job.status === 'error' ? 'risk' : 'muted'} numberOfLines={2}>{summary}</Txt>
                          <Txt variant="monoSm" tone="ink3">{ago(job.updatedAt)}{linked ? ' · open result' : ''}</Txt>
                        </View>
                      </Pressable>
                      {index < all.length - 1 ? <Divider /> : null}
                    </MotionView>
                  );
                })}
              </MotionView>
            ) : null}

            {!conversations.length && !queueJobs.length ? (
              <View style={styles.empty}>
                <Txt variant="productTitle" tone="ink">Nothing saved yet.</Txt>
                <Txt variant="bodyTight" tone="ink3">Your chats and scans will stay here.</Txt>
              </View>
            ) : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, justifyContent: 'flex-end' },
  scrim: { ...StyleSheet.absoluteFill, backgroundColor: color.scrim },
  sheet: { backgroundColor: color.ground, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl, paddingHorizontal: gap[4], paddingTop: gap[2], paddingBottom: 28, maxHeight: '88%', gap: gap[3] },
  grab: { width: 38, height: 4, borderRadius: 2, backgroundColor: color.edge, alignSelf: 'center' },
  head: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  headText: { flex: 1, gap: 2 },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  scroll: { flexGrow: 0 },
  list: { gap: gap[4], paddingBottom: gap[2] },
  section: { gap: gap[2] },
  rowWrap: { gap: gap[1] },
  rowLine: { flexDirection: 'row', alignItems: 'center' },
  row: { flex: 1, minHeight: 68, flexDirection: 'row', alignItems: 'center', paddingVertical: gap[2] },
  rowText: { flex: 1, gap: 4 },
  titleLine: { minHeight: 30, flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  title: { flex: 1 },
  delete: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  empty: { gap: gap[2], paddingVertical: gap[5] },
  pressed: { opacity: 0.65 },
});
