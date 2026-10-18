/**
 * A product run: the question, the work, and the claims that come out.
 *
 * The screen is the same one in both states. While the run is live it shows the
 * steps and the progress; when the file is written the same slot fills with the
 * claims and the sources behind them.
 */

import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { shotSource } from '../../assets/shots';
import { HeaderAction, Page } from '../../components/Chrome';
import { Composer, ReaderState } from '../../components/Composer';
import { HistoryIcon, SlidersIcon, SearchIcon } from '../../components/Icon';
import { Button, Card, Chip, ProgressBar } from '../../components/Primitives';
import { ClaimCard, SourceRow, StepRow, WrittenLine } from '../../components/Run';
import { useStore, useThread } from '../../engine/store';
import { color, gap, radius } from '../../theme/tokens';
import { Txt } from '../../theme/Txt';

export default function Product() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const thread = useThread(id);
  const { ask, stopRun, readerReady, web, setWeb } = useStore();
  const [followUp, setFollowUp] = useState('');

  useEffect(() => {
    if (!thread) router.replace('/chat');
  }, [thread]);

  if (!thread) return <Page>{null}</Page>;

  const running = thread.status === 'searching';
  const stopped = thread.status === 'stopped';
  const done = thread.status === 'done';
  const meta = thread.sources.length
    ? `${thread.sources.length} source${thread.sources.length === 1 ? '' : 's'} so far`
    : 'looking for sources';

  const sendFollowUp = () => {
    const question = followUp.trim();
    if (!question) return;
    setFollowUp('');
    const next = ask({ query: question, kind: 'text', web });
    router.push(`/product/${next.id}`);
  };

  return (
    <Page
      artHeight={0}
      actions={
        <>
          <HeaderAction label="History" onPress={() => router.push('/chat')}>
            <HistoryIcon size={21} color="#FFFFFF" />
          </HeaderAction>
          <HeaderAction label="Settings" onPress={() => router.push('/settings')}>
            <SlidersIcon size={21} color="#FFFFFF" />
          </HeaderAction>
        </>
      }
      footer={
        <>
          <ReaderState phase={running ? 'working' : 'ready'} />
          <Composer
            value={running ? 'Kriko is working…' : followUp}
            onChangeText={setFollowUp}
            placeholder={running ? 'Kriko is working…' : 'Ask a follow-up…'}
            onSend={sendFollowUp}
            onScreenshot={() => router.replace('/check')}
            web={web}
            onToggleWeb={() => setWeb(!web)}
            busy={running}
            onStop={() => stopRun(thread.id)}
            disabled={!readerReady}
            lockedNote="The reader is not installed on this phone. Open set up to install it."
          />
        </>
      }
    >
      <View style={styles.headBlock}>
        <Txt variant="crumb" tone="ink3" numberOfLines={1} style={styles.fileLine}>
          Product search · {thread.file}
        </Txt>
        <Txt variant="productTitle" tone="ink" numberOfLines={2}>
          {thread.title}
        </Txt>
      </View>

      <View style={styles.body}>
        <View style={styles.userRow}>
          <View style={styles.bubble}>
            {thread.kind === 'screenshot' ? (
              <View style={styles.bubbleTag}>
                <Image source={shotSource(thread.imageUri)} style={styles.bubbleThumb} contentFit="cover" />
                <Txt variant="mono" tone="#FFFFFF">
                  screenshot
                </Txt>
              </View>
            ) : null}
            <Txt variant="rowText" tone="#FFFFFF">
              {thread.kind === 'screenshot' ? 'Find this product' : thread.query}
            </Txt>
          </View>
        </View>

        <View style={styles.answerHead}>
          <Txt variant="cardTitle" tone="ink">
            Kriko
          </Txt>
          {running ? (
            <Chip label="Reading" icon={<SearchIcon size={13} color={color.ink} />} />
          ) : stopped ? (
            <Chip label="Stopped" />
          ) : (
            <Chip label="Done" icon={<SearchIcon size={13} color={color.ink} />} />
          )}
        </View>

        {running ? (
          <Txt variant="body" tone="ink2">
            Searching the web and reading the pages. The product file fills in as claims are found.
          </Txt>
        ) : stopped ? (
          <Txt variant="body" tone="ink2">
            Stopped before the product file was written. The sources that were read stay in the
            history.
          </Txt>
        ) : (
          <Txt variant="body" tone="ink2">
            {thread.summary}
          </Txt>
        )}

        {!done ? (
          <View style={styles.steps}>
            {thread.steps.map((step, index) => (
              <Card key={step.id} style={styles.stepCard}>
                <StepRow step={step} last={index === thread.steps.length - 1} />
              </Card>
            ))}
            <View style={styles.progressBlock}>
              <ProgressBar value={thread.progress / 100} height={5} />
              <Txt variant="stepMeta" tone="ink3">
                {thread.progress}% · {thread.progressLabel}
              </Txt>
            </View>
          </View>
        ) : null}

        {!done ? (
          <SourceRow label={meta} sources={thread.sources} />
        ) : (
          <View style={styles.claims}>
            {thread.claims.map((claim) => (
              <ClaimCard key={claim.id} claim={claim} />
            ))}
            <WrittenLine text={`Wrote ${thread.written} claims to ${thread.file}`} />
            <SourceRow label={`Sources · ${thread.sources.length}`} sources={thread.sources} />
          </View>
        )}

        {stopped ? (
          <Card style={styles.stoppedCard}>
            <Txt variant="body" tone="ink2">
              {thread.sources.length} source{thread.sources.length === 1 ? '' : 's'} were read before
              you stopped the run.
            </Txt>
            <Button
              label="Run again"
              variant="ghost"
              onPress={() => {
                const next = ask({ query: thread.query, kind: thread.kind, imageUri: thread.imageUri, web: thread.web });
                router.replace(`/product/${next.id}`);
              }}
            />
          </Card>
        ) : null}

        {done ? (
          <Pressable onPress={() => router.push('/chat')} style={styles.backLink} hitSlop={8}>
            <Txt variant="sectionLabel" tone="ink2">
              Back to chat
            </Txt>
          </Pressable>
        ) : null}
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  headBlock: {
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 14,
    gap: 4,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: color.edge,
  },
  fileLine: { fontSize: 13 },
  body: { paddingHorizontal: 16, paddingTop: 16, gap: gap[4] },
  userRow: { alignItems: 'flex-end' },
  bubble: {
    maxWidth: '86%',
    backgroundColor: color.accentDeep,
    borderRadius: radius.xl,
    borderTopRightRadius: radius.s,
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: gap[2],
  },
  bubbleTag: { flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  bubbleThumb: { width: 22, height: 22, borderRadius: 5 },
  answerHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  steps: { gap: gap[2] },
  stepCard: { padding: 12 },
  progressBlock: { gap: gap[2], marginTop: 2 },
  claims: { gap: gap[3] },
  stoppedCard: { gap: gap[3] },
  backLink: { alignItems: 'center', paddingVertical: 8 },
});
