import Constants from 'expo-constants';
import { router, type Href } from 'expo-router';
import { useEffect, useState } from 'react';
import { Alert, AppState, StyleSheet, View } from 'react-native';

import { AccessSheet } from '../components/AccessSheet';
import { Divider, HeaderAction, Hero, Page } from '../components/Chrome';
import { BackIcon, ChevronRightIcon, GlobeIcon, KeyIcon, ShieldIcon, SparkIcon, TrashIcon } from '../components/Icon';
import { MotionPressable, MotionView } from '../components/Motion';
import { PuckPreview } from '../components/PuckPreview';
import { Button, Chip, SectionLabel, Segmented, Toggle } from '../components/Primitives';
import { isDefaultAssistant, openAssistantSettings, overlayAvailable } from '../engine/overlay';
import { useStore } from '../engine/store';
import { tr } from '../i18n';
import { tap } from '../theme/feedback';
import {
  nearestPuckOpacityStep,
  type Appearance,
  type MotionPreference,
  type TextSize,
} from '../theme/preferences';
import { gap, PAGE_X } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
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
    appearance,
    textSize,
    motion,
    haptics,
    puckOpacity,
    setPuckOpacity,
    setThoroughness,
    setAnswerStyle,
    setAppLanguage,
    setAppearance,
    setTextSize,
    setMotion,
    setHaptics,
    resetPreferences,
  } = useStore();
  const color = useColors();
  const styles = useStyles();
  const [sheet, setSheet] = useState(false);
  const scanner = overlayAvailable();
  const assistant = useAssistantStatus(scanner);

  const accessTitle =
    access.kind === 'trial' ? 'Free trial' : access.kind === 'shared' ? 'Shared access' :
      access.kind === 'own' ? 'Your own keys' : 'No access yet';
  const accessDetail =
    access.kind === 'trial'
      ? `${trialLeft} of ${access.limit} questions left on this phone, on the owner’s keys.`
      : access.kind === 'shared'
        ? access.label
          ? `${access.label}’s Mercury and DeepSeek keys, opened on this phone.`
          : 'The owner’s Mercury and DeepSeek keys, opened on this phone.'
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

  const confirmReset = () => {
    Alert.alert(
      tr('Reset preferences?'),
      tr('Every appearance, text-size, motion and answer choice goes back to its default. Keys, conversations and scans stay.'),
      [
        { text: tr('Cancel'), style: 'cancel' },
        { text: tr('Reset'), style: 'destructive', onPress: resetPreferences },
      ],
    );
  };

  const messageCount = threads.reduce((total, thread) => total + thread.messages.length, 0);
  const accessLabel = access.kind === 'trial' ? `${trialLeft} left` : access.kind === 'none' ? 'Locked' : 'Unlocked';

  return (
    <Page
      artHeight={0}
      actions={<HeaderAction label={tr('Back')} onPress={() => router.back()}><BackIcon size={21} color={color.ink} /></HeaderAction>}
    >
      <Hero
        crumb="kriko / settings"
        title="Settings"
        subtitle="A few choices. Everything stays on this phone."
      />

      <View style={styles.body}>
        <MotionView key={`${access.kind}-${trialLeft}`} delay={0} style={styles.section}>
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
            <MotionPressable onPress={confirmForget} accessibilityRole="button" style={styles.textAction}>
              <Txt variant="actionSmall" tone="risk">Forget these keys</Txt>
            </MotionPressable>
          ) : null}
        </MotionView>

        <Divider />

        <MotionView delay={60} style={styles.section}>
          <SectionLabel>Appearance</SectionLabel>
          <Setting label="Theme" description="System follows your phone. White is brightest.">
            <ThemePicker value={appearance} onChange={setAppearance} />
          </Setting>
          <Setting label="Text size" description="How large every answer and label is drawn.">
            <Segmented<TextSize>
              value={textSize}
              onChange={setTextSize}
              options={[
                { value: 'small', label: 'Small' },
                { value: 'default', label: 'Default' },
                { value: 'large', label: 'Large' },
              ]}
            />
          </Setting>
          <Setting label="Motion" description="Transitions and reveals. System follows your phone’s setting.">
            <Segmented<MotionPreference>
              value={motion}
              onChange={setMotion}
              options={[
                { value: 'system', label: 'System' },
                { value: 'reduced', label: 'Reduced' },
                { value: 'full', label: 'Full' },
              ]}
            />
          </Setting>
          <View style={styles.toggleRow}>
            <View style={[styles.settingText, styles.toggleText]}>
              <Txt variant="rowTitle" tone="ink">Haptics</Txt>
              <Txt variant="bodyTight" tone="ink3">A small tap when you choose or act.</Txt>
            </View>
            <Toggle value={haptics} onChange={() => { tap(); setHaptics(!haptics); }} label={tr('Haptics')} />
          </View>
        </MotionView>

        <Divider />

        {scanner ? (
          <>
            <MotionView delay={80} style={styles.section}>
              <SectionLabel>Floating scanner</SectionLabel>
              <View style={styles.puckRow}>
                <PuckPreview opacity={puckOpacity} />
                <View style={styles.puckText}>
                  <Txt variant="rowTitle" tone="ink">Transparency</Txt>
                  <Txt variant="bodyTight" tone="ink3">
                    How solid the floating K is while it waits. A touch, a scan or an answer brings it to full strength.
                  </Txt>
                </View>
              </View>
              <Segmented<string>
                value={String(nearestPuckOpacityStep(puckOpacity))}
                onChange={(value) => setPuckOpacity(Number(value))}
                options={[
                  { value: '35', label: 'Faint' },
                  { value: '55', label: 'Soft' },
                  { value: '75', label: 'Strong' },
                  { value: '100', label: 'Solid' },
                ]}
              />
            </MotionView>

            <Divider />

            <MotionView delay={100} style={styles.section}>
              <SectionLabel>Phone assistant</SectionLabel>
              <View style={styles.accessRow}>
                <View style={styles.keyMark}><SparkIcon size={19} color={color.accent} /></View>
                <View style={styles.accessText}>
                  <Txt variant="rowTitle" tone="ink">Scan with a long press</Txt>
                  <Txt variant="bodyTight" tone="ink3">
                    {assistant
                      ? 'Kriko is your phone’s assistant. Hold the power or home button to scan the screen at once.'
                      : 'Make Kriko your phone’s assistant, then hold the power or home button to scan the screen at once.'}
                  </Txt>
                </View>
                <Chip label={assistant ? 'Active' : 'Not set'} tone={assistant ? 'ok' : 'neutral'} size="sm" />
              </View>
              <Button
                label={assistant ? 'Assistant settings' : 'Set as assistant'}
                variant={assistant ? 'ghost' : 'primary'}
                onPress={() => { void openAssistantSettings(); }}
              />
              {assistant ? null : (
                <Txt variant="bodyTight" tone="ink3">
                  In the list, choose Kriko under Digital assistant app, and keep “Use screenshot” on.
                </Txt>
              )}
            </MotionView>

            <Divider />
          </>
        ) : null}

        <MotionView delay={110} style={styles.section}>
          <SectionLabel>Language</SectionLabel>
          <Setting label="Interface language" description="Answers follow the language you ask in.">
            <Segmented
              value={language}
              onChange={setAppLanguage}
              options={[{ value: 'en', label: 'English' }, { value: 'tr', label: 'Türkçe' }]}
            />
          </Setting>
        </MotionView>

        <Divider />

        <MotionView delay={160} style={styles.section}>
          <SectionLabel>How Kriko answers</SectionLabel>
          <Setting label="Answer length" description="Choose how much the agent writes.">
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
          <Setting label="Research depth" description="Sets the maximum search budget. Kriko may stop early when the evidence is enough.">
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
        </MotionView>

        <Divider />

        <MotionView delay={210} style={styles.section}>
          <SectionLabel>What happens to your data</SectionLabel>
          <Fact icon={<SparkIcon size={16} color={color.ink3} />} label="Writes answers" value="Mercury 3" />
          <Fact icon={<GlobeIcon size={16} color={color.ink3} />} label="Searches and reads" value="DeepSeek Search & Fetch" />
          <Fact icon={<ShieldIcon size={16} color={color.ink3} />} label="Reads screenshots" value="DeepSeek vision" />
          <Txt variant="bodyTight" tone="ink3" style={styles.privacy}>
            Your question and listing text go to Inception. Search queries and chosen pages go to DeepSeek. A screenshot is uploaded once for reading and kept only as a chat thumbnail. No Kriko account, server, or analytics.
          </Txt>
        </MotionView>

        <Divider />

        <MotionView delay={260} style={styles.section}>
          <View style={styles.sectionHead}>
            <SectionLabel>Saved conversations</SectionLabel>
            <Txt variant="monoSm" tone="ink3" style={styles.sectionCount}>{tr(`${threads.length} chat${threads.length === 1 ? '' : 's'} · ${messageCount} messages`)}</Txt>
          </View>
          {threads.length ? (
            <Button label="Clear chats and scan results" variant="danger" icon={<TrashIcon size={16} color={color.risk} />} onPress={confirmClear} />
          ) : <Txt variant="bodyTight" tone="ink3">Nothing saved yet.</Txt>}
        </MotionView>

        <Divider />

        <MotionView delay={300} style={styles.section}>
          <SectionLabel>More</SectionLabel>
          <NavRow title="History" subtitle="Chats, scans, and the pages behind them." onPress={() => router.push('/history' as Href)} />
          <Divider inset={40} />
          <NavRow title="About Kriko" subtitle="How this build works and what it sends." onPress={() => router.push('/about' as Href)} />
          <Divider inset={40} />
          <NavRow title="Reset preferences" subtitle="Put every choice on this screen back to its default." onPress={confirmReset} />
        </MotionView>

        <Txt variant="monoSm" tone="ink3" style={styles.foot}>
          {tr(`Kriko Agent for mobile · ${Constants.expoConfig?.version ?? '0.9'} · Mercury and DeepSeek are third-party services.`)}
        </Txt>
      </View>

      {sheet ? <AccessSheet visible onClose={() => setSheet(false)} /> : null}
    </Page>
  );
}

/**
 * Whether Kriko is the phone's chosen assistant. It is chosen on a system
 * screen, so it is read again every time the reader comes back to the app.
 */
function useAssistantStatus(enabled: boolean): boolean {
  const [chosen, setChosen] = useState(false);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    const refresh = () => { void isDefaultAssistant().then((value) => { if (alive) setChosen(value); }); };
    refresh();
    const subscription = AppState.addEventListener('change', (state) => { if (state === 'active') refresh(); });
    return () => { alive = false; subscription.remove(); };
  }, [enabled]);
  return chosen;
}

function Setting({ label, description, children }: { label: string; description: string; children: React.ReactNode }) {
  const styles = useStyles();
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

/**
 * The palette choice as four swatches: the actual ground, a card, the ink and
 * the accent, so "white" is a thing the reader sees before choosing it.
 */
function ThemePicker({ value, onChange }: { value: Appearance; onChange: (value: Appearance) => void }) {
  const color = useColors();
  const styles = useStyles();
  const options: {
    value: Appearance;
    label: string;
    ground: string;
    card: string;
    ink: string;
    accent: string;
  }[] = [
    { value: 'system', label: 'System', ground: '#2A2D33', card: '#141518', ink: '#EDEFF2', accent: '#6C8CFF' },
    { value: 'dark', label: 'Dark', ground: '#000000', card: '#1A1A1A', ink: '#F5F5F5', accent: '#3562E9' },
    { value: 'paper', label: 'Paper', ground: '#F4F0E6', card: '#FFFDF7', ink: '#24231F', accent: '#2E5BEF' },
    { value: 'white', label: 'White', ground: '#F7F8FA', card: '#FFFFFF', ink: '#111318', accent: '#2E5BEF' },
  ];
  return (
    <View style={styles.themeRow}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <MotionPressable
            key={option.value}
            onPress={() => { tap(); onChange(option.value); }}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            accessibilityLabel={tr(option.label)}
            style={[
              styles.themeOption,
              { borderColor: selected ? color.accent : color.edge },
              selected ? styles.themeOptionOn : null,
            ]}
          >
            <View style={[styles.swatch, { backgroundColor: option.ground }]}>
              <View style={[styles.swatchCard, { backgroundColor: option.card }]}>
                <View style={[styles.swatchLine, { backgroundColor: option.ink, width: 18 }]} />
                <View style={[styles.swatchLine, { backgroundColor: option.ink, width: 11, opacity: 0.55 }]} />
              </View>
              <View style={[styles.swatchDot, { backgroundColor: option.accent }]} />
            </View>
            <Txt variant="actionSmall" tone={selected ? 'ink' : 'ink3'}>{option.label}</Txt>
          </MotionPressable>
        );
      })}
    </View>
  );
}

function Fact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.fact}>
      {icon}
      <Txt variant="bodyTight" tone="ink3" style={styles.factLabel}>{label}</Txt>
      <Txt variant="meta" tone="ink" style={styles.factValue}>{value}</Txt>
    </View>
  );
}

function NavRow({ title, subtitle, onPress }: { title: string; subtitle: string; onPress: () => void }) {
  const color = useColors();
  const styles = useStyles();
  return (
    <MotionPressable onPress={onPress} accessibilityRole="button" accessibilityLabel={title} style={styles.navRow}>
      <View style={styles.navText}>
        <Txt variant="rowTitle" tone="ink">{title}</Txt>
        <Txt variant="bodyTight" tone="ink3">{subtitle}</Txt>
      </View>
      <ChevronRightIcon size={18} color={color.ink3} />
    </MotionPressable>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  body: { paddingHorizontal: PAGE_X, gap: gap[4], paddingBottom: 44 },
  section: { gap: gap[3] },
  accessRow: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  keyMark: { width: 40, height: 40, borderRadius: 20, backgroundColor: color.accentSoft, alignItems: 'center', justifyContent: 'center' },
  accessText: { flex: 1, gap: 3 },
  textAction: { minHeight: 44, alignSelf: 'flex-start', justifyContent: 'center', paddingHorizontal: 4 },
  setting: { gap: gap[2], paddingVertical: gap[1] },
  settingText: { gap: 2 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: gap[3], paddingVertical: gap[1] },
  toggleText: { flex: 1 },
  puckRow: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  puckText: { flex: 1, gap: 3 },
  themeRow: { flexDirection: 'row', gap: 8 },
  themeOption: {
    flex: 1,
    alignItems: 'center',
    gap: 7,
    paddingVertical: 9,
    paddingHorizontal: 4,
    borderRadius: 14,
    borderWidth: 1,
    backgroundColor: color.surface,
  },
  themeOptionOn: { backgroundColor: color.accentWash },
  swatch: {
    width: 44,
    height: 40,
    borderRadius: 8,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  swatchCard: {
    width: 30,
    height: 22,
    borderRadius: 4,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
  },
  swatchLine: { height: 2.5, borderRadius: 2 },
  swatchDot: { position: 'absolute', width: 7, height: 7, borderRadius: 4, right: 5, top: 5 },
  fact: { flexDirection: 'row', alignItems: 'center', gap: gap[2], minHeight: 34 },
  factLabel: { flex: 1 },
  factValue: { textAlign: 'right', maxWidth: '58%' },
  privacy: { lineHeight: 21, paddingTop: gap[1] },
  sectionHead: { gap: 2, alignItems: 'flex-start' },
  sectionCount: {},
  navRow: { minHeight: 56, flexDirection: 'row', alignItems: 'center', gap: gap[3], paddingVertical: gap[1] },
  navText: { flex: 1, gap: 2 },
  foot: { textAlign: 'center', lineHeight: 17, paddingTop: gap[2] },
}));
