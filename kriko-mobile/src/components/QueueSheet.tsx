import { Image } from 'expo-image';
import { Linking, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import type { QueueJob } from '../engine/types';
import { tr } from '../i18n';
import { color, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { MotionView, ActivityDots } from './Motion';
import { Button } from './Primitives';
import { XIcon } from './Icon';
import { Markdown } from './Markdown';
import { StepLine } from './Message';

export function QueueSheet({
  visible,
  jobs,
  onClose,
  onCancel,
}: {
  visible: boolean;
  jobs: QueueJob[];
  onClose: () => void;
  onCancel: (id: string) => void;
}) {
  const activeCount = jobs.filter((job) => job.status === 'queued' || job.status === 'running').length;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.wrap}>
        <Pressable style={styles.scrim} onPress={onClose} accessibilityLabel={tr('Close queue')} />
        <View style={styles.sheet}>
          <View style={styles.grab} />
          <View style={styles.head}>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">Scan queue</Txt>
              <Txt variant="bodyTight" tone="ink3">
                {activeCount ? `${activeCount} ${activeCount === 1 ? 'product is' : 'products are'} moving` : 'Your recent product scans'}
              </Txt>
            </View>
            <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close queue')} style={styles.close}>
              <XIcon size={20} color={color.ink2} />
            </Pressable>
          </View>
          <ScrollView showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">
            <QueueList jobs={jobs} onCancel={onCancel} />
          </ScrollView>
          <Button label="Done" variant="quiet" onPress={onClose} />
        </View>
      </View>
    </Modal>
  );
}

/** Shared queue rows for the sheet and the full Queue tab. */
export function QueueList({ jobs, onCancel }: { jobs: QueueJob[]; onCancel: (id: string) => void }) {
  if (!jobs.length) {
    return (
      <MotionView delay={0} style={styles.empty}>
        <Txt variant="productTitle" tone="ink">One at a time is fine.</Txt>
        <Txt variant="body" tone="ink3">Products you scan while browsing will gather here, with their findings and sources.</Txt>
      </MotionView>
    );
  }

  return (
    <View style={styles.list}>
      {[...jobs].reverse().map((job, index) => {
        const title = [job.reading.brand, job.reading.product, job.reading.model].filter(Boolean).join(' ') || 'Product scan';
        const cancellable = job.status === 'queued' || job.status === 'running';
        const busyLabel = job.status === 'queued' ? 'Waiting' : 'Researching';
        const statusTone = job.status === 'error' ? 'risk' : job.status === 'done' ? 'accent' : 'muted';
        return (
          <MotionView key={job.id} delay={Math.min(index, 4) * 45} style={styles.job}>
            <View style={styles.jobHead}>
              {job.imageUri ? <Image source={{ uri: job.imageUri }} style={styles.thumb} contentFit="cover" /> : null}
              <View style={styles.jobTitle}>
                <Txt variant="rowTitle" tone="ink" numberOfLines={2}>{title}</Txt>
                <View style={styles.statusLine}>
                  {cancellable ? <ActivityDots color={color.accent} /> : null}
                  <Txt variant="monoSm" tone={statusTone} caps>
                    {cancellable ? busyLabel : job.status === 'done' ? 'Complete' : job.status === 'error' ? 'Could not finish' : 'Cancelled'}
                  </Txt>
                  {job.researchMode === 'site_reviews' && job.reviewSite ? (
                    <Txt variant="monoSm" tone="ink3" numberOfLines={1}>· {tr(job.reviewSite)}</Txt>
                  ) : null}
                </View>
              </View>
              {cancellable ? (
                <Pressable onPress={() => onCancel(job.id)} accessibilityRole="button" accessibilityLabel={`Cancel ${title}`} style={styles.cancel}>
                  <Txt variant="actionSmall" tone="risk">Cancel</Txt>
                </Pressable>
              ) : null}
            </View>
            {job.status === 'running' && !job.text ? (
              <View style={styles.waiting}><ActivityDots color={color.accent} /><Txt variant="bodyTight" tone="ink3">Gathering useful evidence…</Txt></View>
            ) : null}
            {cancellable && job.steps?.length ? (
              <View style={styles.steps}>{job.steps.slice(-2).map((step) => <StepLine key={step.id} step={step} />)}</View>
            ) : null}
            {job.text ? <View style={styles.answer}><Markdown text={job.text} /></View> : null}
            {job.error ? <Txt variant="bodyTight" tone="risk">{job.error}</Txt> : null}
            {job.sources.length ? (
              <View style={styles.sources}>
                <Txt variant="monoSm" tone="ink3" caps>{tr(`Sources · ${job.sources.length}`)}</Txt>
                {job.sources.slice(0, 4).map((source) => (
                  <Pressable key={`${job.id}-${source.n}`} onPress={() => Linking.openURL(source.url).catch(() => {})} accessibilityRole="link" accessibilityLabel={`Source ${source.n}: ${source.title}`} style={styles.sourceLink}>
                    <Txt variant="bodyTight" tone="ink2" numberOfLines={1}>{source.title || source.host}</Txt>
                    <Txt variant="monoSm" tone="ink3" numberOfLines={1}>{source.host}</Txt>
                  </Pressable>
                ))}
              </View>
            ) : null}
            {index !== jobs.length - 1 ? <View style={styles.rule} /> : null}
          </MotionView>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, justifyContent: 'flex-end' },
  scrim: { ...StyleSheet.absoluteFill, backgroundColor: color.scrim },
  sheet: { backgroundColor: color.ground, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl, paddingHorizontal: gap[4], paddingTop: gap[2], paddingBottom: 28, maxHeight: '92%', gap: gap[3] },
  grab: { width: 38, height: 4, borderRadius: 2, backgroundColor: color.edge, alignSelf: 'center' },
  head: { flexDirection: 'row', alignItems: 'center', gap: gap[3], paddingBottom: gap[2] },
  headText: { flex: 1, gap: 3 },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  list: { paddingBottom: gap[2] },
  empty: { gap: gap[2], paddingVertical: gap[6] },
  job: { gap: gap[3], paddingVertical: gap[3] },
  jobHead: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  thumb: { width: 48, height: 48, borderRadius: radius.m, backgroundColor: color.edgeSoft },
  jobTitle: { flex: 1, gap: 5 },
  statusLine: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  cancel: { minHeight: 44, minWidth: 48, alignItems: 'flex-end', justifyContent: 'center', paddingHorizontal: 4 },
  waiting: { flexDirection: 'row', alignItems: 'center', gap: gap[2], paddingLeft: 60 },
  steps: { gap: 2, paddingLeft: 60 },
  answer: { paddingLeft: 60 },
  sources: { gap: gap[2], paddingLeft: 60, paddingTop: gap[1] },
  sourceLink: { minHeight: 40, justifyContent: 'center', gap: 2 },
  rule: { height: StyleSheet.hairlineWidth, backgroundColor: color.edge, marginTop: gap[3] },
});
