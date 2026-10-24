/**
 * One turn, drawn as the reader met it: their words on the right, the answer on
 * the left, the work it did folded underneath, and the pages it read at the end.
 *
 * An answer that is still running says what it is doing; one that stopped keeps
 * its partial text and says so; one that had no page text says that too rather
 * than borrowing the confidence of a citation-shaped number.
 */

import * as Clipboard from 'expo-clipboard';
import { Image } from 'expo-image';
import { useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';

import { color, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';
import { tr } from '../i18n';
import type { AppAction, Message, Source, Step } from '../engine/types';
import {
  ChevronRightIcon,
  CopyIcon,
  GlobeIcon,
  InfoIcon,
  SearchIcon,
  SparkIcon,
} from './Icon';
import { Markdown } from './Markdown';
import { ActivityDots, MotionPressable, MotionView } from './Motion';

function clock(at: number): string {
  const date = new Date(at);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/* ---------------------------------------------------------------- steps -- */

function stepIcon(step: Step) {
  if (step.kind === 'error') return <InfoIcon size={12} color={color.risk} />;
  if (step.kind === 'fetch') return <GlobeIcon size={12} color={color.ink3} />;
  if (step.kind === 'note') return <SparkIcon size={12} color={color.ink3} />;
  return <SearchIcon size={12} color={color.ink3} />;
}

export function StepLine({ step }: { step: Step }) {
  return (
    <View style={styles.stepRow}>
      <View style={styles.stepIcon}>{stepIcon(step)}</View>
      <Txt
        variant="bodyTight"
        tone={step.kind === 'error' ? 'risk' : step.kind === 'note' ? 'ink3' : 'ink2'}
        style={styles.stepText}
      >
        {step.text}
      </Txt>
    </View>
  );
}

function LiveSteps({ steps }: { steps: Step[] }) {
  const recent = steps.slice(-3);
  return (
    <MotionView style={styles.liveCard}>
      <View style={styles.liveHead}>
        <ActivityDots color={color.accent} />
        <Txt variant="bodyTight" tone="ink">Checking the product</Txt>
        <Txt variant="monoSm" tone="ink4" style={styles.liveCount}>
          {steps.length ? `${steps.length} checks` : ''}
        </Txt>
      </View>
      {recent.map((step) => (
        <StepLine key={step.id} step={step} />
      ))}
    </MotionView>
  );
}

function Research({ steps }: { steps: Step[] }) {
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;
  const searches = steps.filter(
    (step) => step.kind === 'search' && step.text.startsWith('Searching'),
  ).length;
  const reads = steps.filter(
    (step) => step.kind === 'fetch' && step.text.startsWith('Reading'),
  ).length;
  const summary = [
    searches ? `${searches} search${searches === 1 ? '' : 'es'}` : '',
    reads ? `${reads} page${reads === 1 ? '' : 's'} read` : '',
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <View style={styles.research}>
      <MotionPressable
        onPress={() => setOpen((value) => !value)}
        accessibilityRole="button"
        accessibilityLabel={open ? 'Hide the research steps' : 'Show the research steps'}
        style={styles.researchHead}
      >
        <Txt variant="sectionLabel" tone="ink3">
          Research notes
        </Txt>
        <Txt variant="monoSm" tone="ink3" numberOfLines={1} style={styles.researchSummary}>
          {summary || `${steps.length} steps`}
        </Txt>
        <View style={open ? styles.chevronOpen : undefined}>
          <ChevronRightIcon size={14} color={color.ink4} />
        </View>
      </MotionPressable>
      {open ? (
        <MotionView style={styles.researchBody}>
          {steps.map((step) => (
            <StepLine key={step.id} step={step} />
          ))}
        </MotionView>
      ) : null}
    </View>
  );
}

/* -------------------------------------------------------------- sources -- */

function SourceRow({ source }: { source: Source }) {
  return (
    <MotionPressable
      onPress={() => {
        Linking.openURL(source.url).catch(() => {});
      }}
      accessibilityRole="link"
      accessibilityLabel={`Source ${source.n}: ${source.title}`}
      style={styles.sourceRow}
    >
      <Txt variant="monoSm" tone="ink4" style={styles.sourceNumber}>{source.n}</Txt>
      <View style={styles.sourceText}>
        <Txt variant="bodyTight" tone="ink2" numberOfLines={2}>
          {source.title}
        </Txt>
        <Txt variant="monoSm" tone="ink4" numberOfLines={1}>
          {source.host}
        </Txt>
      </View>
    </MotionPressable>
  );
}

function Sources({
  sources,
  unverified,
  onOpen,
}: {
  sources: Source[];
  unverified?: boolean;
  onOpen?: () => void;
}) {
  const [all, setAll] = useState(false);
  if (!sources.length) return null;
  const shown = all ? sources : sources.slice(0, 4);
  return (
    <View style={styles.sources}>
      <View style={styles.sourcesHead}>
        <Txt variant="sectionLabel" tone="ink3">
          {tr(`Sources · ${sources.length}`)}
        </Txt>
        <View style={styles.sourceActions}>
          {unverified ? (
            <Txt variant="monoSm" tone="warn" caps>
              Titles only
            </Txt>
          ) : null}
          {onOpen ? (
            <MotionPressable onPress={onOpen} hitSlop={6} accessibilityRole="button" accessibilityLabel="Open all sources">
              <Txt variant="monoSm" tone="fill">
                All
              </Txt>
            </MotionPressable>
          ) : null}
        </View>
      </View>
      {shown.map((source, index) => (
        <MotionView key={source.url} delay={120 + index * 55} style={styles.sourceReveal}>
          <SourceRow source={source} />
        </MotionView>
      ))}
      {sources.length > 4 ? (
        <MotionPressable onPress={() => setAll((value) => !value)} hitSlop={6}>
          <Txt variant="monoSm" tone="fill">
            {all ? 'Show fewer' : `Show all ${sources.length}`}
          </Txt>
        </MotionPressable>
      ) : null}
    </View>
  );
}

/* --------------------------------------------------------------- answer -- */

function CopyAnswer({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <MotionPressable
      onPress={async () => {
        await Clipboard.setStringAsync(text).catch(() => {});
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      }}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel="Copy the answer"
      style={styles.copy}
    >
      <CopyIcon size={14} color={copied ? color.ok : color.ink4} />
      <Txt variant="monoSm" tone={copied ? 'ok' : 'ink4'}>
        {copied ? 'Copied' : 'Copy'}
      </Txt>
    </MotionPressable>
  );
}

function UserMessage({ message }: { message: Message }) {
  const reading = message.reading;
  const label = reading
    ? [reading.brand, reading.product].filter(Boolean).join(' ')
    : '';
  return (
    <View style={styles.userRow}>
      <View style={styles.userBubble}>
        {message.imageUri ? (
          <Image source={{ uri: message.imageUri }} style={styles.thumb} contentFit="cover" />
        ) : null}
        {message.text ? (
          <Txt variant="rowText" tone="ink" style={styles.userText}>
            {message.text}
          </Txt>
        ) : null}
        {label ? (
          <Txt variant="monoSm" tone="ink2" numberOfLines={2}>
            {label}
            {reading?.price ? ` · ${reading.price}` : ''}
          </Txt>
        ) : null}
      </View>
      <Txt variant="monoSm" tone="ink4" style={styles.time}>
        {clock(message.createdAt)}
      </Txt>
    </View>
  );
}

function Actions({ actions, onAction }: {
  actions: AppAction[];
  onAction?: (action: AppAction) => void;
}) {
  return (
    <View style={styles.actions}>
      {actions.map((action) => (
        <View key={action.id} style={styles.actionCard}>
          <View style={styles.actionText}>
            <Txt variant="bodyTight" tone="ink">
              {action.title}
            </Txt>
            {action.detail ? (
              <Txt variant="monoSm" tone="ink3" numberOfLines={2}>
                {action.detail}
              </Txt>
            ) : null}
          </View>
          {action.kind === 'open' && action.status !== 'failed' ? (
            <MotionPressable
              onPress={() => onAction?.(action)}
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel={action.title}
              style={styles.actionButton}
            >
              <Txt variant="monoSm" tone="fill">
                Open
              </Txt>
            </MotionPressable>
          ) : (
            <Txt variant="monoSm" tone="ink4" caps>
              {action.status === 'done' ? 'Saved' : action.status === 'proposed' ? 'Needs a press' : 'Not done'}
            </Txt>
          )}
        </View>
      ))}
    </View>
  );
}

export function MessageRow({
  message,
  onOpenSources,
  onAction,
}: {
  message: Message;
  onOpenSources?: () => void;
  onAction?: (action: AppAction) => void;
}) {
  if (message.role === 'user') {
    return (
      <MotionView style={styles.userStage}>
        <UserMessage message={message} />
      </MotionView>
    );
  }

  const running = Boolean(message.pending);
  const hasText = message.text.trim().length > 0;

  return (
    <MotionView delay={40} style={styles.agentStage}>
      <View style={styles.agentRow}>
      <View style={styles.agentHead}>
        <Txt variant="sectionLabel" tone="accent" style={styles.agentLabel}>
          Kriko&apos;s read
        </Txt>
        <Txt variant="monoSm" tone="ink4">
          {running ? 'In progress' : clock(message.createdAt)}
        </Txt>
      </View>

      {running ? <LiveSteps steps={message.steps ?? []} /> : null}

      {hasText ? (
        <MotionView delay={70} style={styles.answer}>
          <Markdown text={message.text} />
          {!running ? (
            <View style={styles.answerFoot}>
              {message.stopped ? (
                <Txt variant="monoSm" tone="ink4" caps>
                  Stopped
                </Txt>
              ) : (
                <CopyAnswer text={message.text} />
              )}
              {message.unverified ? (
                <Txt variant="monoSm" tone="warn" caps>
                  No page text
                </Txt>
              ) : null}
            </View>
          ) : null}
        </MotionView>
      ) : running ? (
        <Txt variant="body" tone="ink3">
          Looking for evidence…
        </Txt>
      ) : null}

      {!running && message.steps?.length ? <Research steps={message.steps} /> : null}

      {message.error ? (
        <MotionView delay={100} style={styles.errorCard}>
          <InfoIcon size={16} color={color.risk} />
          <Txt variant="body" tone="risk" style={styles.errorText}>
            {message.error}
          </Txt>
        </MotionView>
      ) : null}

      {!running ? (
        <Sources
          sources={message.sources ?? []}
          unverified={message.unverified}
          onOpen={onOpenSources}
        />
      ) : null}

      {!running && message.actions?.length ? (
        <Actions actions={message.actions} onAction={onAction} />
      ) : null}
      </View>
    </MotionView>
  );
}

const styles = StyleSheet.create({
  userStage: { alignItems: 'flex-end', marginTop: gap[3] },
  userRow: { alignItems: 'flex-end', gap: 3, maxWidth: 360, alignSelf: 'flex-end' },
  userBubble: {
    maxWidth: '94%',
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edgeSoft,
    borderRadius: 16,
    borderBottomRightRadius: 5,
    paddingHorizontal: 14,
    paddingVertical: 12,
    gap: gap[2],
  },
  userText: { fontSize: 15.5, lineHeight: 23 },
  thumb: {
    width: 168,
    height: 118,
    borderRadius: radius.m,
    backgroundColor: color.inset,
  },
  time: { paddingRight: 4 },
  agentStage: { marginTop: gap[5] },
  agentRow: { gap: gap[3] },
  agentHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingTop: 9,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edge,
  },
  agentLabel: { flex: 1 },
  sourceActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  answer: { gap: gap[2] },
  answerFoot: { flexDirection: 'row', alignItems: 'center', gap: gap[3], paddingTop: 2 },
  copy: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  liveCard: { borderLeftWidth: 2, borderLeftColor: color.edgeStrong, paddingLeft: 11, gap: 6 },
  liveHead: { flexDirection: 'row', alignItems: 'center', gap: 9, minHeight: 20 },
  liveCount: { marginLeft: 'auto' },
  stepRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  stepIcon: { width: 15, paddingTop: 3, alignItems: 'center' },
  stepText: { flex: 1, lineHeight: 20 },
  research: { gap: 5, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: color.edge, paddingTop: 10 },
  researchHead: { flexDirection: 'row', alignItems: 'center', gap: gap[2], minHeight: 34 },
  researchSummary: { flex: 1 },
  chevronOpen: { transform: [{ rotate: '90deg' }] },
  researchBody: {
    gap: 7,
    paddingLeft: 3,
    paddingTop: 5,
    paddingBottom: 7,
  },
  sources: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edge,
    paddingTop: gap[3],
    gap: 2,
  },
  sourcesHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 30 },
  sourceReveal: { width: '100%' },
  sourceRow: { minHeight: 46, flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 5,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: color.edgeSoft },
  sourceNumber: { width: 19, textAlign: 'left', letterSpacing: 0.2 },
  sourceText: { flex: 1, gap: 1 },
  errorCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: gap[2],
    backgroundColor: color.riskWash,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.riskWash,
    padding: 12,
  },
  errorText: { flex: 1, lineHeight: 19 },
  actions: { gap: gap[2], paddingTop: 2 },
  actionCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[2],
    borderWidth: 0,
    borderColor: color.edge,
    backgroundColor: 'transparent',
    borderRadius: 0,
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 0,
    paddingVertical: 11,
  },
  actionText: { flex: 1, gap: 2 },
  actionButton: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.s,
    backgroundColor: color.accentSoft,
  },
  pressed: { opacity: 0.7 },
});
