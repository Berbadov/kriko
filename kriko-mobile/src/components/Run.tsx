/**
 * The pieces of a run: the step list, the sources, and the claim cards.
 *
 * A step is one line of work with a mono detail line and a state on the right.
 * A claim is the unit this product is actually about: a statement, and whether
 * the sources back it or dispute it.
 */

import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { color, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import type { Claim, RunStep, Source } from '../engine/types';
import { CheckCircleIcon, CheckIcon, ClockIcon, FileIcon, SearchIcon, ShieldIcon } from './Icon';
import { Card, Chip } from './Primitives';

/** The 4-bar mark above "Try asking" in the reference. */
export function BarChart({ width = 56 }: { width?: number }) {
  const bars = [
    { h: 34, color: '#0A1C74' },
    { h: 52, color: '#1A48D8' },
    { h: 68, color: '#2862FF' },
    { h: 86, color: '#A8C0FF' },
  ];
  return (
    <View style={[styles.chart, { height: 86, width }]}>
      {bars.map((bar, i) => (
        <View
          key={i}
          style={{
            width: (width - 9) / 4,
            height: bar.h,
            backgroundColor: bar.color,
          }}
        />
      ))}
    </View>
  );
}

function StepIcon({ step }: { step: RunStep }) {
  const tint = step.state === 'queued' ? color.ink4 : color.ink;
  if (step.state === 'live') {
    return (
      <View style={styles.stepTile}>
        <ActivityIndicator size="small" color={color.ink} />
      </View>
    );
  }
  if (step.state === 'done') {
    return (
      <View style={styles.stepTile}>
        <CheckCircleIcon size={19} color={tint} />
      </View>
    );
  }
  return (
    <View style={styles.stepTile}>
      {step.id === 'read' ? (
        <FileIcon size={19} color={tint} />
      ) : step.id === 'search' ? (
        <SearchIcon size={19} color={tint} />
      ) : (
        <ClockIcon size={19} color={tint} />
      )}
    </View>
  );
}

export function StepRow({ step, last }: { step: RunStep; last?: boolean }) {
  const stateLabel = step.state === 'done' ? 'Done' : step.state === 'live' ? 'Live' : 'Queued';
  return (
    <View>
      <View style={styles.step}>
        <StepIcon step={step} />
        <View style={styles.stepText}>
          <Txt variant="stepTitle" tone={step.state === 'queued' ? 'ink3' : 'ink'}>
            {step.title}
          </Txt>
          <Txt variant="stepMeta" tone="ink3" numberOfLines={1} style={styles.stepMeta}>
            {step.meta}
          </Txt>
        </View>
        <Txt variant="stepMeta" tone={step.state === 'live' ? 'ink2' : 'ink3'}>
          {stateLabel}
        </Txt>
      </View>
      {last ? null : <View style={styles.gap} />}
    </View>
  );
}

export function SourceRow({ label, sources }: { label: string; sources: Source[] }) {
  return (
    <View style={styles.sourcesWrap}>
      <Txt variant="rowText" tone="ink">
        {label}
      </Txt>
      <View style={styles.sources}>
        {sources.map((source) => (
          <View key={source.n} style={styles.sourceChip}>
            <Txt variant="stepMeta" tone="ink2">
              {source.n}. {source.label}
            </Txt>
          </View>
        ))}
      </View>
    </View>
  );
}

export function ClaimCard({ claim }: { claim: Claim }) {
  return (
    <Card style={styles.claim}>
      <View style={styles.claimHead}>
        <Txt variant="claimTitle" tone="ink" style={styles.claimTitle}>
          {claim.title}
        </Txt>
        {claim.status === 'backed' ? (
          <Chip label="Backed" icon={<CheckIcon size={13} color={color.ink} strokeWidth={2} />} />
        ) : (
          <Chip label="Disputed" tone="accent" />
        )}
      </View>
      <Txt variant="body" tone="ink2">
        {claim.body}
      </Txt>
    </Card>
  );
}

/** The mono line that reports what was written to the product file. */
export function WrittenLine({ text }: { text: string }) {
  return (
    <View style={styles.written}>
      <Txt variant="metaMono" tone="ink2">
        {text}
      </Txt>
    </View>
  );
}

/** The statement of what stays on the phone. */
export function PrivacyNote({ title, body }: { title: string; body: string }) {
  return (
    <Card style={styles.privacy}>
      <ShieldIcon size={20} color={color.ink} />
      <View style={styles.privacyText}>
        <Txt variant="rowTitle" tone="ink">
          {title}
        </Txt>
        <Txt variant="body" tone="ink2" style={styles.privacyBody}>
          {body}
        </Txt>
      </View>
    </Card>
  );
}

export function ClaimSkeleton() {
  return (
    <Card style={styles.claim}>
      <View style={styles.skeletonHead}>
        <View style={styles.skeletonBar} />
        <View style={[styles.skeletonBar, styles.skeletonBarShort]} />
      </View>
      <View style={styles.skeletonBar} />
    </Card>
  );
}

const styles = StyleSheet.create({
  chart: { flexDirection: 'row', alignItems: 'flex-end', gap: 3 },
  step: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  stepTile: {
    width: 38,
    height: 38,
    borderRadius: 11,
    backgroundColor: color.inset,
    borderWidth: 1,
    borderColor: color.edgeSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepText: { flex: 1 },
  stepMeta: { marginTop: 3 },
  gap: { height: 10 },
  sourcesWrap: { gap: gap[3] },
  sources: { flexDirection: 'row', flexWrap: 'wrap', gap: gap[2] },
  sourceChip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.raise,
  },
  claim: { gap: gap[3], paddingVertical: 14 },
  claimHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: gap[3] },
  claimTitle: { flex: 1 },
  written: {
    borderWidth: 1,
    borderColor: color.edge,
    borderRadius: radius.l,
    backgroundColor: color.inset,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  privacy: { flexDirection: 'row', gap: gap[3], paddingVertical: 15 },
  privacyText: { flex: 1, gap: 3 },
  privacyBody: { marginTop: 1 },
  skeletonHead: { flexDirection: 'row', justifyContent: 'space-between' },
  skeletonBar: { height: 12, borderRadius: 6, backgroundColor: color.raise, width: '60%' },
  skeletonBarShort: { width: 70 },
});
