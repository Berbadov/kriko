/**
 * One turn, drawn as the reader met it: their words on the right, the answer on
 * the left, the work it did folded underneath, and the pages it read at the end.
 *
 * An answer that is still running says what it is doing; one that stopped keeps
 * its partial text and says so; one that had no page text says that too rather
 * than borrowing the confidence of a citation-shaped number.
 *
 * Everything here sits on one 4/8/12/16 spacing scale and one type rhythm; every
 * control is at least 44 points tall so a thumb can hit it while reading.
 */

import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';

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
import { MatrixLed } from './MatrixLed';
import { MotionPressable, MotionView } from './Motion';
import { ProductCard, ProductSearchCards } from './ProductCard';
import { useSmoothText } from './useSmoothText';

/** The smallest tappable box; a row or button shorter than this is too small. */
const TARGET = 44;
/** The numbered tile beside a source row. */
const SOURCE_TILE = 22;
/** A source row's resting height; a two-line title may grow past it. */
const SOURCE_ROW = 52;

function clock(at: number): string {
  const date = new Date(at);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/* ---------------------------------------------------------------- steps -- */

function stepIcon(step: Step, color: Colors) {
  if (step.kind === 'error') return <InfoIcon size={14} color={color.risk} />;
  if (step.kind === 'fetch') return <GlobeIcon size={14} color={color.ink3} />;
  if (step.kind === 'note') return <SparkIcon size={14} color={color.ink3} />;
  return <SearchIcon size={14} color={color.ink3} />;
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

/**
 * The answer is being worked on: a dot-matrix sweep beside the phase it is in.
 * The LED is the app's live signal now — the old three-card ribbon was a second
 * animation for the same fact.
 */
function LiveSteps({ steps, answering }: { steps: Step[]; answering: boolean }) {
  const color = useColors();
  const styles = useStyles();
  const visible = steps.filter((step) => !step.text.startsWith('diagnostic:'));
  const latest = visible[visible.length - 1];
  const phase = answering || /Writing the answer|moving to the answer/.test(latest?.text ?? '')
    ? 'Writing the answer…'
    : latest?.kind === 'fetch' ? 'Reading sources…'
      : latest?.kind === 'search' ? 'Finding sources…' : 'Reviewing sources…';
  return <MotionView style={styles.liveCard}>
    <View style={styles.liveHead}>
      <MatrixLed
        rows={3}
        cols={7}
        mode="scan"
        dot={3}
        gap={3}
        color={color.accentHi}
        intensity={0.95}
        speed={1500}
      />
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
        <Txt variant="metaMono" tone="ink4" numberOfLines={1} style={styles.researchSummary}>
          {summary || `${steps.length} steps`}
        </Txt>
        <DisclosureChevron open={open}>
          <ChevronRightIcon size={16} color={color.ink4} />
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
            return <Txt key={step.id} variant="metaMono" tone="ink4">{`Tokens · ${prompt} input · ${completion} output · ${total} total`}</Txt>;
          })}
      </AnimatedDisclosure>
    </View>
  );
}

/* -------------------------------------------------------------- sources -- */

function SourceRow({ source }: { source: Source }) {
  const color = useColors();
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
      <View style={styles.sourceTile}>
        <Txt variant="actionSmall" tone="fill">{source.n}</Txt>
      </View>
      <View style={styles.sourceText}>
        <Txt variant="rowTitle" tone="ink" numberOfLines={2} translate={false}>
          {source.title}
        </Txt>
        <Txt variant="metaMono" tone="ink3" numberOfLines={1} translate={false}>
          {source.host}
        </Txt>
      </View>
      <ChevronRightIcon size={16} color={color.ink4} />
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
  const color = useColors();
  const styles = useStyles();
  const [all, setAll] = useState(false);
  if (!sources.length) return null;
  // One expand affordance only: the count in the header opens the rest of the
  // list in place. "All" is a different press — it opens the Sources page.
  const expandable = sources.length > 2;
  const shown = all ? sources : sources.slice(0, 2);
  const head = (
    <>
      <Txt variant="sectionLabel" tone="ink3">
        {tr(`Sources · ${sources.length}`)}
      </Txt>
      {expandable ? (
        <DisclosureChevron open={all}>
          <ChevronRightIcon size={14} color={color.ink4} />
        </DisclosureChevron>
      ) : null}
    </>
  );
  return (
    <View style={styles.sources}>
      <View style={styles.sourcesHead}>
        {expandable ? (
          <MotionPressable
            onPress={() => setAll((value) => !value)}
            accessibilityRole="button"
            accessibilityState={{ expanded: all }}
            accessibilityLabel={tr(all ? 'Show fewer sources' : `Show all ${sources.length} sources`)}
            style={styles.sourceToggle}
          >
            {head}
          </MotionPressable>
        ) : (
          <View style={styles.sourceToggle}>{head}</View>
        )}
        <View style={styles.sourceActions}>
          {unverified ? (
            <Txt variant="actionSmall" tone="warn" caps>
              Titles only
            </Txt>
          ) : null}
          {onOpen ? <MotionPressable onPress={onOpen} accessibilityRole="button" accessibilityLabel={tr('Open all sources')} style={styles.sourceAll}><Txt variant="action" tone="fill">All</Txt></MotionPressable> : null}
        </View>
      </View>
      {shown.map((source, index) => (
        <MotionView key={source.url} delay={120 + index * 55} style={styles.sourceReveal}>
          <SourceRow source={source} />
        </MotionView>
      ))}
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
      accessibilityRole="button"
      accessibilityLabel={tr(copied ? 'Copied' : 'Copy the answer')}
      style={styles.copy}
    >
      <CopyIcon size={16} color={copied ? color.ok : color.ink3} />
      <Txt variant="actionSmall" tone={copied ? 'ok' : 'ink3'}>
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
          <Txt variant="body" tone="ink">
            {message.text}
          </Txt>
        </View>
      ) : null}
      <Txt variant="metaMono" tone="ink4" style={styles.time}>
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
              <Txt variant="metaMono" tone="ink3" numberOfLines={2}>
                {action.detail}
              </Txt>
            ) : null}
          </View>
          {action.kind === 'open' && action.status !== 'failed' ? (
            <MotionPressable
              onPress={() => onAction?.(action)}
              accessibilityRole="button"
              accessibilityLabel={tr(action.title)}
              style={styles.actionButton}
            >
              <Txt variant="action" tone="fill">
                Open
              </Txt>
            </MotionPressable>
          ) : (
            <Txt variant="actionSmall" tone="ink4" caps>
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
        {running ? (
          <MatrixLed
            rows={5}
            cols={5}
            mode="glyph"
            dot={2}
            gap={2}
            color={color.accentHi}
            intensity={0.85}
            speed={2200}
          />
        ) : null}
        <Txt variant="sectionLabel" tone="accent" style={styles.agentLabel}>
          Kriko
        </Txt>
        <Txt variant="metaMono" tone="ink4">
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
                <Txt variant="actionSmall" tone="ink4" caps>
                  Stopped
                </Txt>
              ) : (
                <CopyAnswer text={message.text} />
              )}
              {message.unverified ? (
                <Txt variant="actionSmall" tone="warn" caps>
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
          <InfoIcon size={18} color={color.risk} />
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
  /* A turn: the reader's on the right, the answer on the left, one gap apart. */
  userStage: { alignItems: 'flex-end', marginTop: gap[3] },
  userRow: { alignItems: 'flex-end', gap: gap[2], maxWidth: '92%', alignSelf: 'flex-end' },
  userRowWide: { alignSelf: 'stretch', maxWidth: '100%' },
  userBubble: {
    backgroundColor: color.raise,
    borderWidth: 1,
    borderColor: color.rim,
    borderRadius: radius.l,
    paddingHorizontal: gap[4],
    paddingVertical: gap[3],
  },
  time: { paddingRight: gap[1] },

  agentStage: { marginTop: gap[4] },
  agentRow: { gap: gap[2] },
  agentHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[2],
    paddingTop: gap[3],
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edge,
  },
  agentLabel: { flex: 1 },

  /* The running answer. */
  liveCard: { borderLeftWidth: 2, borderLeftColor: color.edgeStrong, paddingLeft: gap[3], gap: gap[2] },
  liveHead: { flexDirection: 'row', alignItems: 'center', gap: gap[2], minHeight: 24 },
  liveCount: { marginLeft: 'auto' },

  /* Research: one fold, closed by default, separated from the answer above it. */
  research: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edge,
    paddingTop: gap[4],
    gap: gap[2],
  },
  researchHead: { flexDirection: 'row', alignItems: 'center', gap: gap[2], minHeight: TARGET },
  researchSummary: { flex: 1 },
  researchBody: { gap: gap[2], paddingTop: gap[2], paddingBottom: gap[1] },
  stepRow: { flexDirection: 'row', gap: gap[2], alignItems: 'flex-start' },
  stepIcon: { width: 16, paddingTop: 2, alignItems: 'center' },
  stepText: { flex: 1 },

  /* Sources: one row per page, a numbered tile, the title then the host. */
  sources: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edge,
    paddingTop: gap[4],
    gap: gap[1],
  },
  sourcesHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: TARGET, gap: gap[2] },
  sourceToggle: { flex: 1, minHeight: TARGET, flexDirection: 'row', alignItems: 'center', gap: gap[1], paddingRight: gap[2] },
  sourceActions: { flexDirection: 'row', alignItems: 'center', gap: gap[1] },
  sourceAll: { minHeight: TARGET, minWidth: TARGET, alignItems: 'center', justifyContent: 'center', paddingHorizontal: gap[2] },
  sourceReveal: { width: '100%' },
  sourceRow: {
    minHeight: SOURCE_ROW,
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[3],
    paddingVertical: gap[1],
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: color.edgeSoft,
  },
  sourceTile: {
    width: SOURCE_TILE,
    height: SOURCE_TILE,
    borderRadius: 6,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.accentWash,
  },
  sourceText: { flex: 1, gap: 2 },

  /* The answer's own foot: copy, and why the answer is thin when it is. */
  // The reading plate: running text sits on a near-opaque surface, never on raw
  // glass or the moving field behind it, so contrast does not depend on what is
  // scrolled underneath. The rim is the one bright edge the glass catches.
  answer: {
    gap: gap[3],
    padding: gap[4],
    borderRadius: radius.l,
    backgroundColor: color.plate,
    borderWidth: 1,
    borderColor: color.rim,
  },
  answerFoot: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: gap[3] },
  copy: { minHeight: TARGET, flexDirection: 'row', alignItems: 'center', gap: gap[2], paddingRight: gap[2] },

  errorCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: gap[2],
    backgroundColor: color.riskWash,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.riskWash,
    padding: gap[4],
  },
  errorText: { flex: 1 },

  actions: { gap: gap[2], paddingTop: gap[1] },
  actionCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[2],
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.edge,
    paddingVertical: gap[3],
  },
  actionText: { flex: 1, gap: gap[1] },
  actionButton: {
    minHeight: TARGET,
    paddingHorizontal: gap[3],
    borderRadius: radius.s,
    backgroundColor: color.accentSoft,
    justifyContent: 'center',
  },
}));
