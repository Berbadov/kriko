/**
 * Settings: the reader, what may leave the phone, and this device's history.
 *
 * Reached from the sliders in the app bar, on every screen that has one.
 */

import { router } from 'expo-router';
import { Alert, StyleSheet, View } from 'react-native';

import { Hero, HeaderAction, Page } from '../components/Chrome';
import { BackIcon, HashIcon, ResetIcon, TrashIcon } from '../components/Icon';
import { Button, Card, Chip, Row, Tile, Toggle } from '../components/Primitives';
import { PrivacyNote, WrittenLine } from '../components/Run';
import { useStore } from '../engine/store';
import { color, gap } from '../theme/tokens';
import { Txt } from '../theme/Txt';

export default function Settings() {
  const {
    reader,
    readerReady,
    readerBusy,
    readerProgress,
    reinstallReader,
    web,
    setWeb,
    threads,
    clearHistory,
    removeThread,
  } = useStore();

  const confirmReset = () => {
    Alert.alert(
      'Reinstall the reader?',
      'The reader is removed from this phone and downloaded again. Your history stays.',
      [
        { text: 'Keep it', style: 'cancel' },
        { text: 'Reinstall', style: 'destructive', onPress: reinstallReader },
      ],
    );
  };

  const confirmClear = () => {
    Alert.alert('Clear history?', `This removes ${threads.length} saved runs from this phone.`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Clear', style: 'destructive', onPress: clearHistory },
    ]);
  };

  return (
    <Page
      artHeight={200}
      actions={
        <HeaderAction label="Back" onPress={() => router.back()}>
          <BackIcon size={21} color="#FFFFFF" />
        </HeaderAction>
      }
    >
      <Hero crumb="kriko / settings" title="Settings" subtitle="This phone holds everything." />

      <View style={styles.body}>
        <Card style={styles.card}>
          <View style={styles.readerRow}>
            <Tile>
              <HashIcon size={19} color={color.ink} />
            </Tile>
            <View style={styles.readerText}>
              <Txt variant="cardTitle" tone="ink">
                Reader
              </Txt>
              <Txt variant="mono" tone="ink3" caps numberOfLines={1}>
                [{reader.modelId}] · [{reader.modelSize}]
              </Txt>
            </View>
            <Chip
              label={readerReady ? 'Ready' : readerBusy ? `${Math.round(readerProgress * 100)}%` : 'Missing'}
              tone={readerReady ? 'ok' : 'neutral'}
            />
          </View>
          <Button
            label="Reinstall reader"
            variant="ghost"
            icon={<ResetIcon size={18} color={color.ink} />}
            onPress={confirmReset}
          />
        </Card>

        <Card style={styles.card}>
          <Row
            title="Research with the web"
            subtitle={
              <Txt variant="body" tone="ink3" style={styles.rowBody}>
                Off keeps a search to the catalogs already on this phone.
              </Txt>
            }
            trailing={<Toggle value={web} onChange={() => setWeb(!web)} />}
          />
          <WrittenLine text="Searches send a product name and model number. Nothing else." />
        </Card>

        <PrivacyNote
          title="What leaves this phone"
          body="Screenshots are read here and never uploaded. A search sends only a product name and model number."
        />

        {threads.length > 0 ? (
          <Card style={styles.card}>
            <View style={styles.historyHead}>
              <Txt variant="cardTitle" tone="ink">
                History
              </Txt>
              <Chip label={threads.length === 1 ? '1 run' : `${threads.length} runs`} size="sm" />
            </View>
            {threads.slice(0, 6).map((thread) => (
              <View key={thread.id} style={styles.historyRow}>
                <View style={styles.historyText}>
                  <Txt variant="rowText" tone="ink" numberOfLines={1}>
                    {thread.title}
                  </Txt>
                  <Txt variant="stepMeta" tone="ink3">
                    {thread.file}
                  </Txt>
                </View>
                <HeaderAction label={`Remove ${thread.title}`} onPress={() => removeThread(thread.id)}>
                  <TrashIcon size={18} color={color.ink3} />
                </HeaderAction>
              </View>
            ))}
            <Button
              label="Clear history"
              variant="ghost"
              icon={<TrashIcon size={18} color={color.ink} />}
              onPress={confirmClear}
            />
          </Card>
        ) : null}

        <Card style={styles.card}>
          <Row
            title="Kriko for mobile"
            subtitle={
              <Txt variant="body" tone="ink3" style={styles.rowBody}>
                Built on Expo. The reader is a local model; the run engine in this build answers from
                fixtures.
              </Txt>
            }
          />
        </Card>
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: 16, gap: gap[3] },
  card: { gap: gap[4] },
  readerRow: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  readerText: { flex: 1, gap: 2 },
  rowBody: { marginTop: 4 },
  historyHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  historyRow: { flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  historyText: { flex: 1, gap: 3 },
});
