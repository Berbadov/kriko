/** First-run access setup, with the same warm, editorial voice as Home. */

import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { AccessSheet } from '../components/AccessSheet';
import { AppHeader, HeaderAction } from '../components/Chrome';
import { KeyIcon, ShieldIcon, SlidersIcon } from '../components/Icon';
import { MotionPressable, MotionView } from '../components/Motion';
import { Button } from '../components/Primitives';
import { font, gap, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

export function WelcomeScreen() {
  const [sheet, setSheet] = useState<null | 'code' | 'own'>(null);
  const color = useColors();
  const styles = useStyles();

  return (
    <View style={styles.page}>
      <AppHeader
        actions={
          <HeaderAction label="Settings" onPress={() => router.push('/settings')}>
            <SlidersIcon size={21} color={color.ink} />
          </HeaderAction>
        }
      />
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.body}
        showsVerticalScrollIndicator={false}
      >
        <MotionView style={styles.hero}>
          <Txt variant="crumb" tone="ink3" style={styles.eyebrow}>A MORE INFORMED PURCHASE</Txt>
          <Txt variant="headline" tone="ink" style={styles.title}>
            Look beyond the listing.
          </Txt>
          <Txt variant="heroSub" tone="ink2" style={styles.sub}>
            Kriko checks product details against independent sources, then gives you a clear account of what it found.
          </Txt>
        </MotionView>

        <MotionView delay={80} style={styles.accessSection}>
          <View style={styles.accessHeading}>
            <View style={styles.keyTile}>
              <KeyIcon size={18} color={color.ink} />
            </View>
            <View style={styles.accessHeadingText}>
              <Txt variant="sectionLabel" tone="ink">Choose how to connect</Txt>
              <Txt variant="bodyTight" tone="ink3">No Kriko account is needed.</Txt>
            </View>
          </View>

          <View style={styles.accessCard}>
            <Txt variant="rowTitle" tone="ink">Use the shared access</Txt>
            <Txt variant="bodyTight" tone="ink2" style={styles.cardCopy}>
              Enter the access code and password from the person who shared this build. They arrive separately for your security.
            </Txt>
            <Button label="Enter access code" onPress={() => setSheet('code')} />
          </View>

          <MotionPressable
            onPress={() => setSheet('own')}
            accessibilityRole="button"
            style={styles.ownKeys}
          >
            <Txt variant="bodyTight" tone="ink">I have my own provider keys</Txt>
            <Txt variant="actionSmall" tone="accent">Set up keys</Txt>
          </MotionPressable>
        </MotionView>

        <MotionView delay={160} style={styles.privacy}>
          <ShieldIcon size={16} color={color.ink3} />
          <Txt variant="bodyTight" tone="ink3" style={styles.privacyText}>
            Your question and the product details go to the research providers. Kriko keeps your chats on this phone.
          </Txt>
        </MotionView>
      </ScrollView>

      {sheet ? (
        <AccessSheet
          visible
          initialMode={sheet}
          firstRun
          onClose={() => setSheet(null)}
        />
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  page: { flex: 1, backgroundColor: color.ground },
  scroll: { flex: 1 },
  body: { paddingHorizontal: PAGE_X, paddingTop: 30, paddingBottom: 40, gap: gap[6] },
  hero: { gap: 10, maxWidth: 390 },
  eyebrow: { letterSpacing: 1 },
  title: {
    fontFamily: font.editorial,
    letterSpacing: -1.05,
    maxWidth: 340,
  },
  sub: { maxWidth: 360, lineHeight: 23 },
  accessSection: { gap: gap[3] },
  accessHeading: { flexDirection: 'row', alignItems: 'center', gap: 11, marginBottom: 1 },
  keyTile: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edge,
    alignItems: 'center',
    justifyContent: 'center',
  },
  accessHeadingText: { gap: 2 },
  accessCard: {
    padding: 17,
    gap: 10,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edge,
    borderRadius: radius.l,
  },
  cardCopy: { lineHeight: 21 },
  ownKeys: {
    minHeight: 48,
    paddingHorizontal: 3,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: color.edge,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  privacy: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, maxWidth: 370 },
  privacyText: { flex: 1, lineHeight: 21 },
}));
