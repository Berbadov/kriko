import { router, useLocalSearchParams } from 'expo-router';
import { Linking, Pressable, StyleSheet, View } from 'react-native';

import { Divider, HeaderAction, Hero, Page } from '../../components/Chrome';
import { MotionView } from '../../components/Motion';
import { BackIcon, GlobeIcon, InfoIcon } from '../../components/Icon';
import { SectionLabel } from '../../components/Primitives';
import { useStore } from '../../engine/store';
import { tr } from '../../i18n';
import type { Source } from '../../engine/types';
import { color, gap, PAGE_X } from '../../theme/tokens';
import { Txt } from '../../theme/Txt';

function when(at: number): string {
  if (!Number.isFinite(at) || at <= 0) return 'time unknown';
  const date = new Date(at);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export default function Sources() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { threads } = useStore();
  const thread = threads.find((row) => row.id === id);
  const answers = (thread?.messages ?? []).filter((message) => message.role === 'assistant' && (message.sources?.length ?? 0) > 0);

  return (
    <Page artHeight={0} actions={<HeaderAction label="Back" onPress={() => router.back()}><BackIcon size={21} color={color.ink} /></HeaderAction>}>
      <Hero crumb="kriko / sources" title="Sources" subtitle={thread ? thread.title : 'The pages behind this chat.'} />
      <View style={styles.body}>
        {answers.length ? answers.map((answer, index) => (
          <MotionView key={answer.id} delay={Math.min(index, 4) * 55} style={styles.group}>
            <View style={styles.groupHead}>
              <SectionLabel>{tr(`${index === 0 ? 'Latest answer' : `Answer ${answers.length - index}`}`)}</SectionLabel>
              <Txt variant="monoSm" tone="ink3">{when(answer.createdAt)}</Txt>
            </View>
            {(answer.sources ?? []).map((source, sourceIndex) => (
              <View key={source.url}>
                <SourceRow source={source} />
                {sourceIndex < (answer.sources?.length ?? 0) - 1 ? <Divider inset={34} /> : null}
              </View>
            ))}
          </MotionView>
        )) : (
          <MotionView delay={50} style={styles.empty}>
            <InfoIcon size={18} color={color.accent} />
            <View style={styles.emptyText}>
              <Txt variant="productTitle" tone="ink">No sources yet.</Txt>
              <Txt variant="bodyTight" tone="ink3">Ask a question and the pages Kriko reads will appear here.</Txt>
            </View>
          </MotionView>
        )}
      </View>
    </Page>
  );
}

function SourceRow({ source }: { source: Source }) {
  return (
    <Pressable onPress={() => Linking.openURL(source.url).catch(() => {})} accessibilityRole="link" accessibilityLabel={`Source ${source.n}: ${source.title}`} style={({ pressed }) => [styles.row, pressed && styles.pressed]}>
      <View style={styles.number}><Txt variant="monoSm" tone="accent">{String(source.n).padStart(2, '0')}</Txt></View>
      <View style={styles.text}>
        <Txt variant="rowTitle" tone="ink" numberOfLines={2}>{source.title}</Txt>
        <View style={styles.hostRow}>
          <GlobeIcon size={13} color={color.ink3} />
          <Txt variant="monoSm" tone="ink3" numberOfLines={1}>{source.host}</Txt>
        </View>
      </View>
      <Txt variant="actionSmall" tone="accent">Open</Txt>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: PAGE_X, gap: gap[5], paddingBottom: 44 },
  group: { gap: gap[2] },
  groupHead: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', paddingBottom: gap[1] },
  row: { minHeight: 66, flexDirection: 'row', alignItems: 'center', gap: gap[2], paddingVertical: gap[2] },
  number: { width: 30, height: 30, borderRadius: 15, backgroundColor: color.accentSoft, alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1, gap: 4 },
  hostRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  empty: { flexDirection: 'row', alignItems: 'flex-start', gap: gap[3], paddingVertical: gap[5] },
  emptyText: { flex: 1, gap: gap[2] },
  pressed: { opacity: 0.65 },
});
