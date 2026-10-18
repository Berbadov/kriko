/**
 * Set up: install the reader once, on this phone.
 *
 * Nothing here talks to a server. The reader is the piece that reads a
 * screenshot and researches a product; the app only starts a chat once it is on
 * the device.
 */

import { router } from 'expo-router';
import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';

import { Hero, Page } from '../components/Chrome';
import { HashIcon } from '../components/Icon';
import { Button, Card, ProgressBar, Tile, Toggle } from '../components/Primitives';
import { PrivacyNote } from '../components/Run';
import { useStore } from '../engine/store';
import { color, gap } from '../theme/tokens';
import { Txt } from '../theme/Txt';

export default function Setup() {
  const { reader, readerReady, readerBusy, startDownload, toggleWifi } = useStore();

  useEffect(() => {
    if (reader.status === 'absent') startDownload();
  }, [reader.status, startDownload]);

  const percent = Math.round(reader.progress * 100);

  return (
    <Page
      artHeight={260}
      footer={
        <View style={styles.footer}>
          <Button
            label="Start chatting"
            disabled={!readerReady}
            onPress={() => router.replace('/chat')}
          />
          <Txt variant="crumb" tone="ink3" style={styles.caption}>
            {readerReady
              ? `Reader ready · ${reader.modelSize} on this phone`
              : 'Starts when the download finishes.'}
          </Txt>
        </View>
      }
    >
      <Hero
        crumb="kriko / set up"
        title="Set up"
        subtitle="Download the reader once. It runs on this phone."
      />

      <View style={styles.stack}>
        <Card style={styles.card}>
          <View style={styles.modelRow}>
            <Tile>
              <HashIcon size={19} color={color.ink} />
            </Tile>
            <View style={styles.modelText}>
              <Txt variant="cardTitle" tone="ink">
                Reader model
              </Txt>
              <Txt variant="mono" tone="ink3" caps>
                [{reader.modelId}] · [{reader.modelSize}]
              </Txt>
            </View>
          </View>

          <View style={styles.progressBlock}>
            <View style={styles.progressHead}>
              <Txt variant="meta" tone="ink2">
                {readerReady ? 'Installed' : readerBusy ? 'Downloading' : 'Waiting'}
              </Txt>
              <Txt variant="metaMono" tone="ink">
                {percent}%
              </Txt>
            </View>
            <ProgressBar value={reader.progress} />
          </View>

          <View style={styles.wifiRow}>
            <View style={styles.wifiText}>
              <Txt variant="rowTitle" tone="ink">
                Wi-Fi only
              </Txt>
              <Txt variant="body" tone="ink2" style={styles.wifiBody}>
                Pause the download on mobile data.
              </Txt>
            </View>
            <Toggle value={reader.wifiOnly} onChange={toggleWifi} />
          </View>
        </Card>

        <PrivacyNote
          title="What leaves this phone"
          body="Screenshots are read here and never uploaded. A search sends only a product name and model number."
        />
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  stack: { paddingHorizontal: 16, gap: gap[3] },
  card: { gap: gap[5], paddingBottom: 18 },
  modelRow: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  modelText: { flex: 1, gap: 2 },
  progressBlock: { gap: gap[2] },
  progressHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  wifiRow: { flexDirection: 'row', alignItems: 'center', gap: gap[4] },
  wifiText: { flex: 1, gap: 2 },
  wifiBody: { maxWidth: 250 },
  footer: { gap: gap[3] },
  caption: { textAlign: 'center', letterSpacing: 0.6 },
});
