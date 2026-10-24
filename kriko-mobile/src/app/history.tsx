import { router } from 'expo-router';
import { Alert, Pressable, StyleSheet, View } from 'react-native';

import { Divider, HeaderAction, Hero, Page } from '../components/Chrome';
import { ActivityDots, MotionView } from '../components/Motion';
import { BackIcon, ClockIcon, PlusIcon, TrashIcon } from '../components/Icon';
import { Button, Chip, SectionLabel } from '../components/Primitives';
import { useStore } from '../engine/store';
import type { QueueJob } from '../engine/types';
import { tr } from '../i18n';
import { color, gap, PAGE_X } from '../theme/tokens';
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

function scanTitle(job: QueueJob): string {
  return [job.reading.brand, job.reading.product, job.reading.model].filter(Boolean).join(' ') || 'Product scan';
}

export default function History() {
  const { threads, queueJobs, activeThread, openThread, openScanResult, newChat, deleteThread } = useStore();
  const scanThreadIds = new Set(queueJobs.flatMap((job) => job.threadId ? [job.threadId] : []));
  const conversations = threads.filter((thread) => !scanThreadIds.has(thread.id));

  const start = () => { newChat(); router.replace('/'); };
  const open = (id: string) => { openThread(id); router.replace('/'); };
  const openScan = (id: string) => { openScanResult(id); router.replace('/'); };
  const remove = (id: string, title: string) => {
    Alert.alert(tr('Delete this chat?'), tr(`“${title}” and its sources are removed from this phone.`), [
      { text: tr('Keep'), style: 'cancel' },
      { text: tr('Delete'), style: 'destructive', onPress: () => deleteThread(id) },
    ]);
  };

  return (
    <Page artHeight={0} actions={<HeaderAction label="Back" onPress={() => router.back()}><BackIcon size={21} color={color.ink} /></HeaderAction>}>
      <Hero crumb="kriko / your shelf" title="History" subtitle="The questions you asked, and what the scans found." />

      <View style={styles.body}>
        <MotionView delay={0} style={styles.start}>
          <Button label="New conversation" icon={<PlusIcon size={17} color="#FFFFFF" />} onPress={start} />
        </MotionView>

        {!conversations.length && !queueJobs.length ? (
          <MotionView delay={60} style={styles.empty}>
            <Txt variant="productTitle" tone="ink">A clear page.</Txt>
            <Txt variant="body" tone="ink3">Your conversations and product scans will appear here as you use Kriko.</Txt>
          </MotionView>
        ) : null}

        {conversations.length ? (
          <MotionView delay={60} style={styles.section}>
            <View style={styles.sectionHead}>
              <SectionLabel>Conversations</SectionLabel>
              <Txt variant="monoSm" tone="ink3" caps>{conversations.length}</Txt>
            </View>
            {conversations.map((thread, index) => {
              const asked = thread.messages.filter((message) => message.role === 'user').length;
              const last = [...thread.messages].reverse().find((message) => message.role === 'user');
              const active = thread.id === activeThread?.id;
              return (
                <MotionView key={thread.id} delay={80 + Math.min(index, 4) * 35} style={styles.rowWrap}>
                  <View style={styles.rowLine}>
                    <Pressable onPress={() => open(thread.id)} accessibilityRole="button" accessibilityLabel={`Open ${thread.title}`} style={({ pressed }) => [styles.row, pressed && styles.pressed]}>
                      <View style={styles.rowText}>
                        <View style={styles.titleLine}>
                          <Txt variant="rowTitle" tone="ink" numberOfLines={1} style={styles.title}>{thread.title}</Txt>
                          {active ? <Chip label="Open" tone="accent" size="sm" /> : null}
                        </View>
                        {last ? <Txt variant="bodyTight" tone="ink3" numberOfLines={2}>{last.text}</Txt> : null}
                        <View style={styles.meta}>
                          <ClockIcon size={13} color={color.ink3} />
                          <Txt variant="monoSm" tone="ink3">{ago(thread.updatedAt)} · {tr(`${asked} question${asked === 1 ? '' : 's'}`)}</Txt>
                        </View>
                      </View>
                    </Pressable>
                    <Pressable onPress={() => remove(thread.id, thread.title)} accessibilityRole="button" accessibilityLabel={`Delete ${thread.title}`} style={styles.delete}>
                      <TrashIcon size={16} color={color.ink3} />
                    </Pressable>
                  </View>
                  {index < conversations.length - 1 ? <Divider inset={0} /> : null}
                </MotionView>
              );
            })}
          </MotionView>
        ) : null}

        {queueJobs.length ? (
          <MotionView delay={130} style={styles.section}>
            <View style={styles.sectionHead}>
              <SectionLabel>Scanned products</SectionLabel>
              <Txt variant="monoSm" tone="ink3" caps>{queueJobs.length}</Txt>
            </View>
            {[...queueJobs].reverse().map((job, index, all) => {
              const linked = Boolean(job.threadId);
              const summary = job.text || job.error || job.reading.note || job.question;
              const busy = job.status === 'queued' || job.status === 'running';
              return (
                <MotionView key={job.id} delay={150 + Math.min(index, 4) * 35} style={styles.rowWrap}>
                  <Pressable onPress={() => linked && openScan(job.id)} disabled={!linked} accessibilityRole={linked ? 'button' : undefined} accessibilityLabel={linked ? `Open scan result for ${scanTitle(job)}` : undefined} style={({ pressed }) => [styles.row, pressed && styles.pressed]}>
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
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: PAGE_X, gap: gap[5], paddingBottom: 44 },
  start: { alignSelf: 'flex-start' },
  empty: { gap: gap[2], paddingVertical: gap[5] },
  section: { gap: gap[2] },
  sectionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingBottom: gap[1] },
  rowWrap: { gap: gap[1] },
  rowLine: { flexDirection: 'row', alignItems: 'center', gap: gap[1] },
  row: { minHeight: 68, flexDirection: 'row', alignItems: 'center', gap: gap[2], paddingVertical: gap[2] },
  rowText: { flex: 1, gap: 4 },
  titleLine: { minHeight: 32, flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  title: { flex: 1 },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 20 },
  delete: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  pressed: { opacity: 0.65 },
});
