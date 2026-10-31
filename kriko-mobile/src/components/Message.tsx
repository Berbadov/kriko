/**
 * One turn, drawn as the reader met it: their words on the right, the answer on
 * the left, the work it did folded underneath, and the pages it read at the end.
 *
 * An answer that is still running says what it is doing; one that stopped keeps
 * its partial text and says so; one that had no page text says that too rather
 * than borrowing the confidence of a citation-shaped number.
 */

import * as Clipboard from 'expo-clipboard';
import { useEffect, useState } from 'react';
import { Animated, AppState, Easing, Linking, StyleSheet, View } from 'react-native';

import { motion } from '../theme/motion';
import type { Colors } from '../theme/palettes';
import { gap, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { tr } from '../i18n';
import { SCREENSHOT_QUESTION } from '../engine/prompt';
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
import { AnimatedDisclosure, DisclosureChevron } from './AnimatedDisclosure';
import { MotionPressable, MotionView, useReducedMotion } from './Motion';
import { ProductCard, ProductSearchCards } from './ProductCard';
import { useSmoothText } from './useSmoothText';

function clock(at: number): string {
  const date = new Date(at);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/* ---------------------------------------------------------------- steps -- */

function stepIcon(step: Step, color: Colors) {
  if (step.kind === 'error') return <InfoIcon size={12} color={color.risk} />;
  if (step.kind === 'fetch') return <GlobeIcon size={12} color={color.ink3} />;
  if (step.kind === 'note') return <SparkIcon size={12} color={color.ink3} />;
  return <SearchIcon size={12} color={color.ink3} />;
}

export function StepLine({ step }: { step: Step }) {
  const color = useColors();
  const styles = useStyles();
  return (
    <MotionView duration={motion.duration.standard} rise={6} style={styles.stepRow}>
      <View style={styles.stepIcon}>{stepIcon(step, color)}</View>
      <Txt
        variant="bodyTight"
        tone={step.kind === 'error' ? 'risk' : step.kind === 'note' ? 'ink3' : 'ink2'}
        style={styles.stepText}
      >
        {step.text}
      </Txt>
    </MotionView>
  );
}

function ResearchIndicator() {
  const color = useColors();
  const reduced = useReducedMotion();
  const [travel] = useState(() => new Animated.Value(0));
  useEffect(() => {
    travel.stopAnimation(); travel.setValue(0.5);
    if (reduced !== false) return;
    const motion = Animated.loop(Animated.timing(travel, {
      toValue: 1, duration: 1750, easing: Easing.linear, useNativeDriver: true, isInteraction: false,
    }));
    travel.setValue(0);
    if (AppState.currentState === 'active') motion.start();
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') motion.start(); else motion.stop();
    });
    return () => { subscription.remove(); motion.stop(); };
  }, [reduced, travel]);
  return <View importantForAccessibility="no-hide-descendants" style={{ width: 42, height: 24, overflow: 'hidden' }}>
    {[0, 1, 2].map((index) => <Animated.View key={index} style={{ position: 'absolute', top: 3, width: 13, height: 18,
      borderRadius: 3, borderWidth: 1, borderColor: color.accentHi, backgroundColor: color.surface,
      opacity: travel.interpolate({ inputRange: [0, 0.3, 0.75, 1], outputRange: [0.1, 0.9 - index * 0.16, 0.7, 0.1] }),
      transform: [{ translateX: travel.interpolate({ inputRange: [0, 1], outputRange: [-14 + index * 10, 14 + index * 10] }) },
        { translateY: travel.interpolate({ inputRange: [0, 0.5, 1], outputRange: [index, -index, index] }) }] }}>
      <View style={{ height: 1, marginHorizontal: 2, marginTop: 5, backgroundColor: color.accentSoft }} />
      <View style={{ height: 1, marginHorizontal: 2, marginTop: 3, backgroundColor: color.accentSoft }} />
    </Animated.View>)}
  </View>;
}

function LiveSteps({ steps, answering }: { steps: Step[]; answering: boolean }) {
  const styles = useStyles();
  const visible = steps.filter((step) => !step.text.startsWith('diagnostic:'));
  const latest = visible[visible.length - 1];
  const phase = answering || /Writing the answer|moving to the answer/.test(latest?.text ?? '')
    ? 'Writing the answer…'
    : latest?.kind === 'fetch' ? 'Reading sources…'
      : latest?.kind === 'search' ? 'Finding sources…' : 'Reviewing sources…';
  return <MotionView style={styles.liveCard}>
    <View style={styles.liveHead}>
      <ResearchIndicator />
      <Txt variant="bodyTight" tone="ink" numberOfLines={1} style={styles.liveCount}>{tr(phase)}</Txt>
    </View>
  </MotionView>;
}

function Research({ steps, showDiagnostics = false }: { steps: Step[]; showDiagnostics?: boolean }) {
  const color = useColors();
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  const visibleSteps = steps.filter((step) => !step.text.startsWith('diagnostic:'));
  const diagnostics = showDiagnostics ? steps.filter((step) => step.text.startsWith('diagnostic:tokens:')) : [];
  if (!visibleSteps.length && !diagnostics.length) return null;
  const searches = visibleSteps.filter(
    (step) => step.kind === 'search' && step.text.startsWith('Searching'),
  ).length;
  const reads = visibleSteps.filter(
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
        accessibilityLabel={tr(open ? 'Hide the research steps' : 'Show the research steps')}
        accessibilityState={{ expanded: open }}
        style={styles.researchHead}
      >
        <Txt variant="sectionLabel" tone="ink3">Research</Txt>
        <Txt variant="monoSm" tone="ink3" numberOfLines={1} style={styles.researchSummary}>
          {summary || `${steps.length} steps`}
        </Txt>
        <DisclosureChevron open={open}>
          <ChevronRightIcon size={14} color={color.ink4} />
        </DisclosureChevron>
      </MotionPressable>
      <AnimatedDisclosure open={open} style={styles.researchBody}>
          {visibleSteps.map((step) => (
            <StepLine key={step.id} step={step} />
          ))}
          {diagnostics.map((step) => {
            const fields = step.text.split(':');
            const prompt = fields[2] ?? '0';
            const completion = fields[3] ?? '0';
            const total = fields[4] ?? '0';
            return <Txt key={step.id} variant="monoSm" tone="ink4">{`Tokens · ${prompt} input · ${completion} output · ${total} total`}</Txt>;
          })}
      </AnimatedDisclosure>
    </View>
  );
}

/* -------------------------------------------------------------- sources -- */

function SourceRow({ source }: { source: Source }) {
  const styles = useStyles();
  return (
    <MotionPressable
      onPress={() => {
        Linking.openURL(source.url).catch(() => {});
      }}
      accessibilityRole="link"
      accessibilityLabel={tr(`Source ${source.n}: ${source.title}`)}
      style={styles.sourceRow}
    >
      <Txt variant="monoSm" tone="ink4" style={styles.sourceNumber}>{source.n}</Txt>
      <View style={styles.sourceText}>
      <Txt variant="bodyTight" tone="ink2" numberOfLines={1}>
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
  const styles = useStyles();
  const [all, setAll] = useState(false);
  if (!sources.length) return null;
  const shown = all ? sources : sources.slice(0, 2);
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
          {onOpen ? <MotionPressable onPress={onOpen} hitSlop={6} accessibilityRole="button" accessibilityLabel={tr('Open all sources')} style={styles.sourceAll}><Txt variant="monoSm" tone="fill">All</Txt></MotionPressable> : null}
        </View>
      </View>
      {shown.map((source, index) => (
        <MotionView key={source.url} delay={120 + index * 55} style={styles.sourceReveal}>
          <SourceRow source={source} />
        </MotionView>
      ))}
      {sources.length > 2 ? (
        <MotionPressable onPress={() => setAll((value) => !value)} accessibilityRole="button" accessibilityState={{ expanded: all }} accessibilityLabel={tr(all ? 'Show fewer sources' : `Show all ${sources.length} sources`)} style={styles.sourceExpand}>
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
  const color = useColors();
  const styles = useStyles();
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
      accessibilityLabel={tr(copied ? 'Copied' : 'Copy the answer')}
      style={styles.copy}
    >
      <CopyIcon size={14} color={copied ? color.ok : color.ink4} />
      <Txt variant="monoSm" tone={copied ? 'ok' : 'ink4'}>
        {copied ? 'Copied' : 'Copy'}
      </Txt>
    </MotionPressable>
  );
}

function UserMessage({ message, scanning }: { message: Message; scanning?: boolean }) {
  const styles = useStyles();
  const hasPicture = Boolean(message.imageUri || message.reading);
  // A scan with no words of the reader's own carries the app's stock question;
  // the card already says what was asked about, so the bubble would only repeat it.
  const stock = hasPicture && message.text.trim() === SCREENSHOT_QUESTION;
  return (
    <View style={[styles.userRow, hasPicture ? styles.userRowWide : null]}>
      {hasPicture ? (
        <ProductCard reading={message.reading} imageUri={message.imageUri} scanning={scanning} />
      ) : null}
      {message.text && !stock ? (
        <View style={styles.userBubble}>
          <Txt variant="rowText" tone="ink" style={styles.userText}>
            {message.text}
          </Txt>
        </View>
      ) : null}
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
  const styles = useStyles();
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
              accessibilityLabel={tr(action.title)}
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
  scanning,
  onOpenSources,
  onAction,
  showDiagnostics = false,
  onCheckMerchant,
}: {
  message: Message;
  /** This is the scan whose answer is still being written. */
  scanning?: boolean;
  onOpenSources?: () => void;
  onAction?: (action: AppAction) => void;
  /** Show provider-reported usage counts. Defaults off. */
  showDiagnostics?: boolean;
  onCheckMerchant?: (source: Source) => void;
}) {
  const color = useColors();
  const styles = useStyles();
  const running = Boolean(message.pending);
  // The answer is drawn at a steady pace, not in the chunks the network sent.
  const drawn = useSmoothText(message.role === 'assistant' ? message.text : '', running);
  if (message.role === 'user') {
    return (
      <MotionView style={styles.userStage}>
        <UserMessage message={message} scanning={scanning} />
      </MotionView>
    );
  }

  const hasText = message.text.trim().length > 0;
  // What belongs under the answer waits until the answer has finished drawing.
  const done = drawn.settled;

  return (
    <MotionView delay={40} style={styles.agentStage}>
      <View style={styles.agentRow}>
      <View style={styles.agentHead}>
        <Txt variant="sectionLabel" tone="accent" style={styles.agentLabel}>
          Kriko
        </Txt>
        <Txt variant="monoSm" tone="ink4">
          {running ? 'In progress' : clock(message.createdAt)}
        </Txt>
      </View>

      {running ? <LiveSteps steps={message.steps ?? []} answering={hasText} /> : null}

      {hasText ? (
        <MotionView delay={70} style={styles.answer}>
          <Markdown text={drawn.text} streaming={!done} />
          {done ? (
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

      {done && message.steps?.length ? <Research steps={message.steps} showDiagnostics={showDiagnostics} /> : null}

      {message.error ? (
        <MotionView delay={100} style={styles.errorCard}>
          <InfoIcon size={16} color={color.risk} />
          <Txt variant="body" tone="risk" style={styles.errorText}>
            {message.error}
          </Txt>
        </MotionView>
      ) : null}

      {done ? (
        <ProductSearchCards sources={message.sources ?? []} onCheckMerchant={onCheckMerchant} />
      ) : null}

      {done ? (
        <Sources
          sources={message.sources ?? []}
          unverified={message.unverified}
          onOpen={onOpenSources}
        />
      ) : null}

      {done && message.actions?.length ? (
        <Actions actions={message.actions} onAction={onAction} />
      ) : null}
      </View>
    </MotionView>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  userStage: { alignItems: 'flex-end', marginTop: gap[3] },
  userRow: { alignItems: 'flex-end', gap: 3, maxWidth: 360, alignSelf: 'flex-end' },
  userRowWide: { alignSelf: 'stretch', maxWidth: 440, gap: gap[2] },
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
  userText: {},
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
  sourceAll: { minHeight: 44, minWidth: 44, alignItems: 'center', justifyContent: 'center' },
  sourceExpand: { minHeight: 44, justifyContent: 'center' },
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
}));
