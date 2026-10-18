/**
 * Chat: ask for a product, or share a screenshot of one.
 *
 * The suggestion rows are the four ways in — a plain question, a comparison, a
 * question about a model, and a screenshot. Asking anything creates a run and
 * moves to it.
 */

import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, View } from 'react-native';

import { Hero, Page, HeaderAction } from '../components/Chrome';
import { Composer, ReaderState } from '../components/Composer';
import { HistoryIcon, ImageIcon2, SearchIcon, SlidersIcon } from '../components/Icon';
import { BarChart } from '../components/Run';
import { Card, Chip, SectionLabel } from '../components/Primitives';
import { useStore } from '../engine/store';
import { color, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';

const SUGGESTIONS = [
  { id: 'a', icon: 'search' as const, text: 'Wireless earbuds with noise canceling' },
  { id: 'b', icon: 'search' as const, text: 'Which Galaxy Buds have wireless charging?' },
  { id: 'c', icon: 'image' as const, text: 'What product is in this screenshot?' },
];

export default function Chat() {
  const { ask, threads, readerReady, web, setWeb, setPendingShot, viewOf } = useStore();
  const [draft, setDraft] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);

  const startQuestion = (question: string) => {
    const thread = ask({ query: question, kind: 'text', web });
    setDraft('');
    router.push(`/product/${thread.id}`);
  };

  /**
   * A screenshot is not searched until the reader's reading of it is confirmed,
   * so this stages the image and hands off to the check screen.
   */
  const reviewScreenshot = (uri: string | null) => {
    setPendingShot(uri);
    router.push('/check');
  };

  const pickScreenshot = async () => {
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert(
          'Photo access is off',
          'Kriko can work from the sample screenshot that ships with the app instead.',
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Use the sample', onPress: () => reviewScreenshot(null) },
          ],
        );
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        quality: 1,
      });
      if (result.canceled || !result.assets?.[0]) return;
      reviewScreenshot(result.assets[0].uri);
    } catch {
      // No photo library on this device: fall back to the bundled sample.
      reviewScreenshot(null);
    }
  };

  const onSuggestion = (id: string) => {
    if (id === 'c') {
      pickScreenshot();
      return;
    }
    startQuestion(SUGGESTIONS.find((s) => s.id === id)!.text);
  };

  const recent = threads.slice(0, historyOpen ? 10 : 3);

  return (
    <Page
      artHeight={230}
      actions={
        <>
          <HeaderAction label="History" onPress={() => setHistoryOpen((v) => !v)}>
            <HistoryIcon size={21} color="#FFFFFF" />
          </HeaderAction>
          <HeaderAction label="Settings" onPress={() => router.push('/setup')}>
            <SlidersIcon size={21} color="#FFFFFF" />
          </HeaderAction>
        </>
      }
      footer={
        <>
          <ReaderState phase={readerReady ? 'ready' : 'blocked'} />
          <Composer
            value={draft}
            onChangeText={setDraft}
            placeholder="Describe a product…"
            onSend={() => draft.trim() && startQuestion(draft.trim())}
            onScreenshot={pickScreenshot}
            web={web}
            onToggleWeb={() => setWeb(!web)}
            disabled={!readerReady}
            lockedNote="The reader is not installed on this phone yet. It finishes downloading on the set up screen."
          />
        </>
      }
    >
      <Hero
        crumb="kriko / chat"
        title="Chat"
        subtitle="Ask for a product, or share a screenshot of one."
      />

      <View style={styles.body}>
        <BarChart />

        <View style={styles.suggestions}>
          <SectionLabel>Try asking</SectionLabel>
          {SUGGESTIONS.map((suggestion) => (
            <Pressable
              key={suggestion.id}
              onPress={() => onSuggestion(suggestion.id)}
              accessibilityRole="button"
              accessibilityLabel={suggestion.text}
              style={({ pressed }) => [styles.suggestion, pressed && styles.pressed]}
            >
              {suggestion.icon === 'search' ? (
                <SearchIcon size={21} color={color.ink} />
              ) : (
                <ImageIcon2 size={21} color={color.ink} />
              )}
              <Txt variant="rowText" tone="ink" style={styles.suggestionText}>
                {suggestion.text}
              </Txt>
            </Pressable>
          ))}
        </View>

        {recent.length > 0 ? (
          <View style={styles.history}>
            <View style={styles.historyHead}>
              <SectionLabel>History</SectionLabel>
              {threads.length > 3 ? (
                <Pressable onPress={() => setHistoryOpen((v) => !v)} hitSlop={8}>
                  <Txt variant="crumb" tone="ink3">
                    {historyOpen ? 'Show less' : `All ${threads.length}`}
                  </Txt>
                </Pressable>
              ) : null}
            </View>
            {recent.map((thread) => {
              const view = viewOf(thread);
              return (
                <Pressable
                  key={thread.id}
                  onPress={() => router.push(`/product/${thread.id}`)}
                  accessibilityRole="button"
                  style={({ pressed }) => [styles.historyRow, pressed && styles.pressed]}
                >
                  <View style={styles.historyText}>
                    <Txt variant="rowText" tone="ink" numberOfLines={1}>
                      {thread.title}
                    </Txt>
                    <Txt variant="stepMeta" tone="ink3">{thread.file}</Txt>
                  </View>
                  {view.status === 'done' ? (
                    <Chip label={`${view.claims.length} claims`} size="sm" />
                  ) : view.status === 'stopped' ? (
                    <Chip label="Stopped" size="sm" />
                  ) : (
                    <Chip label={`${view.progress}%`} size="sm" tone="accent" />
                  )}
                </Pressable>
              );
            })}
          </View>
        ) : (
          <View style={styles.hint}>
            <Card tone="inset" style={styles.hintCard}>
              <Txt variant="body" tone="ink3">
                Nothing asked yet. A question searches the web, reads the pages, and writes a
                product file next to the answer.
              </Txt>
            </Card>
          </View>
        )}
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: 16, paddingTop: 4, gap: gap[6] },
  suggestions: { gap: 10 },
  suggestion: {
    minHeight: 50,
    borderRadius: radius.l,
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.surface,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    paddingHorizontal: 14,
    paddingVertical: 11,
  },
  suggestionText: { flex: 1 },
  pressed: { opacity: 0.75 },
  history: { gap: gap[3] },
  historyHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  historyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[3],
    minHeight: 52,
  },
  historyText: { flex: 1, gap: 3 },
  hint: { gap: gap[3] },
  hintCard: { paddingVertical: 14 },
});
