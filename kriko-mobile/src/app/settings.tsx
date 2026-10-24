import Constants from 'expo-constants';
import { router, type Href } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, View } from 'react-native';

import { AccessSheet } from '../components/AccessSheet';
import { Divider, HeaderAction, Hero, Page } from '../components/Chrome';
import { BackIcon, ChevronRightIcon, GlobeIcon, KeyIcon, ShieldIcon, SparkIcon, TrashIcon } from '../components/Icon';
import { MotionView } from '../components/Motion';
import { Button, Chip, SectionLabel, Segmented } from '../components/Primitives';
import { useStore } from '../engine/store';
import { tr } from '../i18n';
import { color, gap, PAGE_X } from '../theme/tokens';
import { Txt } from '../theme/Txt';

export default function Settings() {
  const {
    access,
    trialLeft,
    threads,
    clearHistory,
    forgetAccess,
    thoroughness,
    answerStyle,
    language,
    setThoroughness,
    setAnswerStyle,
    setAppLanguage,
  } = useStore();
  const [sheet, setSheet] = useState(false);

  const accessTitle =
    access.kind === 'trial' ? 'Free trial' : access.kind === 'shared' ? 'Shared access' :
      access.kind === 'own' ? 'Your own keys' : 'No access yet';
  const accessDetail =
    access.kind === 'trial'
      ? `${trialLeft} of ${access.limit} questions left on this phone, on the owner’s keys.`
      : access.kind === 'shared'
        ? `${access.label || 'The owner'}’s Mercury and DeepSeek keys, opened on this phone.`
        : access.kind === 'own'
          ? 'Mercury and DeepSeek keys stored in this phone’s secure storage.'
          : 'Paste an access code, or add your own Mercury and DeepSeek keys.';

  const confirmForget = () => {
    Alert.alert(tr('Forget these keys?'), tr('The opened keys are removed from this phone. Your conversations stay.'), [
      { text: tr('Keep'), style: 'cancel' },
      { text: tr('Forget'), style: 'destructive', onPress: () => { forgetAccess().catch(() => {}); } },
    ]);
  };

  const confirmClear = () => {
    Alert.alert(
      tr('Clear every chat?'),
      tr(`${threads.length} conversation(s), scan results, and their sources are removed from this phone.`),
      [
        { text: tr('Cancel'), style: 'cancel' },
        { text: tr('Clear'), style: 'destructive', onPress: clearHistory },
      ],
    );
  };

  const messageCount = threads.reduce((total, thread) => total + thread.messages.length, 0);
  const accessLabel = access.kind === 'trial' ? `${trialLeft} left` : access.kind === 'none' ? 'Locked' : 'Unlocked';

  return (
    <Page
      artHeight={0}
      actions={<HeaderAction label="Back" onPress={() => router.back()}><BackIcon size={21} color={color.ink} /></HeaderAction>}
    >
      <Hero crumb="kriko / settings" title="Settings" subtitle="A few choices. Everything stays on this phone." />

      <View style={styles.body}>
        <MotionView delay={0} style={styles.section}>
          <SectionLabel>Access</SectionLabel>
          <View style={styles.accessRow}>
            <View style={styles.keyMark}><KeyIcon size={19} color={color.accent} /></View>
            <View style={styles.accessText}>
              <Txt variant="rowTitle" tone="ink">{accessTitle}</Txt>
              <Txt variant="bodyTight" tone="ink3">{accessDetail}</Txt>
            </View>
            <Chip label={accessLabel} tone={access.kind === 'none' || (access.kind === 'trial' && trialLeft === 0) ? 'neutral' : 'ok'} size="sm" />
          </View>
          <Button label={access.kind === 'none' ? 'Add access' : 'Replace access'} onPress={() => setSheet(true)} variant={access.kind === 'none' ? 'primary' : 'ghost'} />
          {access.kind === 'shared' || access.kind === 'own' ? (
            <Pressable onPress={confirmForget} accessibilityRole="button" style={styles.textAction}>
              <Txt variant="actionSmall" tone="risk">Forget these keys</Txt>
            </Pressable>
          ) : null}
        </MotionView>

        <Divider />

        <MotionView delay={70} style={styles.section}>
          <SectionLabel>How Kriko answers</SectionLabel>
          <Setting label="Answer length" description="Choose how much the agent writes." >
            <Segmented
              value={answerStyle}
              onChange={setAnswerStyle}
              options={[
                { value: 'short', label: 'Short' },
                { value: 'standard', label: 'Standard' },
                { value: 'product', label: 'Product' },
              ]}
            />
          </Setting>
          <Setting label="Research depth" description="Sets the maximum search budget. Kriko may stop early when the evidence is enough." >
            <Segmented
              value={String(thoroughness)}
              onChange={(value) => setThoroughness(Number(value))}
              options={[
                { value: '0', label: 'Light' },
                { value: '50', label: 'Default' },
                { value: '100', label: 'Deep' },
              ]}
            />
          </Setting>
          <Setting label="Language" description="Answers follow the language you ask in." >
            <Segmented
              value={language}
              onChange={setAppLanguage}
              options={[{ value: 'en', label: 'English' }, { value: 'tr', label: 'Türkçe' }]}
            />
          </Setting>
        </MotionView>

        <Divider />

        <MotionView delay={140} style={styles.section}>
          <SectionLabel>What happens to your data</SectionLabel>
          <Fact icon={<SparkIcon size={16} color={color.ink3} />} label="Writes answers" value="Mercury 3" />
          <Fact icon={<GlobeIcon size={16} color={color.ink3} />} label="Searches and reads" value="DeepSeek Search & Fetch" />
          <Fact icon={<ShieldIcon size={16} color={color.ink3} />} label="Reads screenshots" value="DeepSeek vision" />
          <Txt variant="bodyTight" tone="ink3" style={styles.privacy}>
            Your question and listing text go to Inception. Search queries and chosen pages go to DeepSeek. A screenshot is uploaded once for reading and kept only as a chat thumbnail. No Kriko account, server, or analytics.
          </Txt>
        </MotionView>

        <Divider />

        <MotionView delay={210} style={styles.section}>
          <View style={styles.sectionHead}>
            <SectionLabel>Saved conversations</SectionLabel>
            <Txt variant="monoSm" tone="ink3">{tr(`${threads.length} chat${threads.length === 1 ? '' : 's'} · ${messageCount} messages`)}</Txt>
          </View>
          {threads.length ? (
            <Button label="Clear chats and scan results" variant="danger" icon={<TrashIcon size={16} color={color.risk} />} onPress={confirmClear} />
          ) : <Txt variant="bodyTight" tone="ink3">Nothing saved yet.</Txt>}
        </MotionView>

        <Divider />

        <MotionView delay={280} style={styles.section}>
          <SectionLabel>More</SectionLabel>
          <NavRow title="History" subtitle="Chats, scans, and the pages behind them." onPress={() => router.push('/history' as Href)} />
          <Divider inset={40} />
          <NavRow title="About Kriko" subtitle="How this build works and what it sends." onPress={() => router.push('/about' as Href)} />
        </MotionView>

        <Txt variant="monoSm" tone="ink3" style={styles.foot}>
          {tr(`Kriko Agent for mobile · ${Constants.expoConfig?.version ?? '0.7.0'} · Mercury and DeepSeek are third-party services.`)}
        </Txt>
      </View>

      {sheet ? <AccessSheet visible onClose={() => setSheet(false)} /> : null}
    </Page>
  );
}

function Setting({ label, description, children }: { label: string; description: string; children: React.ReactNode }) {
  return (
    <View style={styles.setting}>
      <View style={styles.settingText}>
        <Txt variant="rowTitle" tone="ink">{label}</Txt>
        <Txt variant="bodyTight" tone="ink3">{description}</Txt>
      </View>
      {children}
    </View>
  );
}

function Fact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <View style={styles.fact}>
      {icon}
      <Txt variant="bodyTight" tone="ink3" style={styles.factLabel}>{label}</Txt>
      <Txt variant="meta" tone="ink" style={styles.factValue}>{value}</Txt>
    </View>
  );
}

function NavRow({ title, subtitle, onPress }: { title: string; subtitle: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={title} style={({ pressed }) => [styles.navRow, pressed && styles.pressed]}>
      <View style={styles.navText}>
        <Txt variant="rowTitle" tone="ink">{title}</Txt>
        <Txt variant="bodyTight" tone="ink3">{subtitle}</Txt>
      </View>
      <ChevronRightIcon size={18} color={color.ink3} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: PAGE_X, gap: gap[4], paddingBottom: 44 },
  section: { gap: gap[3] },
  accessRow: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  keyMark: { width: 40, height: 40, borderRadius: 20, backgroundColor: color.accentSoft, alignItems: 'center', justifyContent: 'center' },
  accessText: { flex: 1, gap: 3 },
  textAction: { minHeight: 44, alignSelf: 'flex-start', justifyContent: 'center', paddingHorizontal: 4 },
  setting: { gap: gap[2], paddingVertical: gap[1] },
  settingText: { gap: 2 },
  fact: { flexDirection: 'row', alignItems: 'center', gap: gap[2], minHeight: 34 },
  factLabel: { flex: 1 },
  factValue: { textAlign: 'right', maxWidth: '58%' },
  privacy: { lineHeight: 21, paddingTop: gap[1] },
  sectionHead: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: gap[2] },
  navRow: { minHeight: 56, flexDirection: 'row', alignItems: 'center', gap: gap[3], paddingVertical: gap[1] },
  navText: { flex: 1, gap: 2 },
  pressed: { opacity: 0.65 },
  foot: { textAlign: 'center', lineHeight: 17, paddingTop: gap[2] },
});
