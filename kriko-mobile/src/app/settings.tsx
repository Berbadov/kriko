/**
 * Settings, as a compact grouped list.
 *
 * Quiet section labels sit over rounded cards; a row is an accent icon tile, a
 * label, the current value in muted type and a chevron, or a toggle at the
 * row's right edge. Every choice opens a sheet with checkbox rows, and the
 * sentence that used to sit under each label is the sheet's first line, so the
 * list itself stays short. Nothing here changes a store setter: the same
 * setters run, in the same order, as the tall label-and-segmented screen did.
 */

import Constants from 'expo-constants';
import { router, type Href } from 'expo-router';
import {
  Activity,
  Gauge,
  Hand,
  Languages,
  ListChecks,
  Palette,
  PenLine,
  Ruler,
  Tag,
  TriangleAlert,
  Type as TypeIcon,
  Vibrate,
  Zap,
} from 'lucide-react-native';
import { useEffect, useState } from 'react';
import {
  Alert,
  AppState,
  ScrollView,
  StyleSheet,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AccessSheet } from '../components/AccessSheet';
import { useDock } from '../components/dock';
import { GlassCard } from '../components/Glass';
import {
  BackIcon,
  GlobeIcon,
  HistoryIcon,
  InfoIcon,
  KeyIcon,
  ResetIcon,
  ScanIcon,
  SearchIcon,
  ShieldIcon,
  TrashIcon,
} from '../components/Icon';
import { MotionPressable } from '../components/Motion';
import { PriceTracking } from '../components/PriceTracking';
import { PuckPreview } from '../components/PuckPreview';
import { ChoiceSheet, type Choice } from '../components/settings/ChoiceSheet';
import { PrioritiesSheet } from '../components/settings/PrioritiesSheet';
import { SettingRow, SettingsCard, SettingsSection, ToggleRow } from '../components/settings/SettingsList';
import { UpdateCard } from '../components/UpdateCard';
import { nativeLanguageName } from '../engine/languages';
import {
  canDrawOverApps,
  isDefaultAssistant,
  openAssistantSettings,
  openDrawOverAppsSettings,
  overlayAvailable,
} from '../engine/overlay';
import { ANSWER_LANGUAGES, SOURCE_LANGUAGES, type AnswerLanguage, type SourceLanguage } from '../engine/researchLanguage';
import type { AnswerStyle } from '../engine/prompt';
import { useStore } from '../engine/store';
import { updateNeedsAttention } from '../engine/updatecore';
import { updatesSupported, useAppUpdate } from '../engine/updater';
import { tr, type Language } from '../i18n';
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

/** Which sheet is open. One at a time, exactly like the old inline sections. */
type SheetName =
  | 'access'
  | 'theme'
  | 'textSize'
  | 'motion'
  | 'interface'
  | 'sources'
  | 'answers'
  | 'answerLength'
  | 'depth'
  | 'sourceCount'
  | 'priorities'
  | 'transparency';

/**
 * The five palettes, drawn as the actual ground, card, ink and accent so
 * "white" is something the reader sees before choosing it.
 */
const THEMES: readonly { value: Appearance; label: string; ground: string; card: string; ink: string; accent: string }[] = [
  { value: 'system', label: 'System', ground: '#2A2D33', card: '#141518', ink: '#EDEFF2', accent: '#6C8CFF' },
  { value: 'dark', label: 'Dark', ground: '#000000', card: '#1A1A1A', ink: '#F5F5F5', accent: '#3562E9' },
  { value: 'gray', label: 'Gray', ground: '#202226', card: '#2B2E33', ink: '#F4F5F7', accent: '#7C9BFF' },
  { value: 'paper', label: 'Paper', ground: '#F4F0E6', card: '#FFFDF7', ink: '#24231F', accent: '#2E5BEF' },
  { value: 'white', label: 'White', ground: '#F7F8FA', card: '#FFFFFF', ink: '#111318', accent: '#2E5BEF' },
];

const TEXT_SIZE_OPTIONS: readonly Choice<TextSize>[] = [
  { value: 'small', label: 'Small' },
  { value: 'default', label: 'Default' },
  { value: 'large', label: 'Large' },
];

const MOTION_OPTIONS: readonly Choice<MotionPreference>[] = [
  { value: 'system', label: 'System' },
  { value: 'reduced', label: 'Reduced' },
  { value: 'full', label: 'Full' },
];

const ANSWER_LENGTH_OPTIONS: readonly Choice<AnswerStyle>[] = [
  { value: 'short', label: 'Short' },
  { value: 'standard', label: 'Standard' },
  { value: 'product', label: 'Product' },
];

const DEPTH_OPTIONS = [
  { value: '0', label: 'Light' },
  { value: '50', label: 'Default' },
  { value: '100', label: 'Deep' },
] as const;

const SOURCE_COUNT_OPTIONS = [
  { value: '3', label: '3' },
  { value: '5', label: '5' },
  { value: '8', label: '8' },
  { value: '10', label: '10' },
] as const;

const OPACITY_OPTIONS = [
  { value: '35', label: 'Faint' },
  { value: '55', label: 'Soft' },
  { value: '75', label: 'Strong' },
  { value: '100', label: 'Solid' },
] as const;

const INTERFACE_OPTIONS: readonly Choice<Language>[] = [
  { value: 'en', label: 'English' },
  { value: 'tr', label: 'Türkçe' },
];

/** Every language the engine serves, in the order `languages.ts` lists them. */
const SOURCE_OPTIONS: readonly Choice<SourceLanguage>[] = SOURCE_LANGUAGES.map((code) =>
  code === 'any' ? { value: code, label: 'Any' } : { value: code, label: nativeLanguageName(code), translate: false });

const ANSWER_OPTIONS: readonly Choice<AnswerLanguage>[] = ANSWER_LANGUAGES.map((code) =>
  code === 'auto' ? { value: code, label: 'Auto' } : { value: code, label: nativeLanguageName(code), translate: false });

export default function Settings() {
  const {
    access,
    checkPriceWatch,
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
    researchPreferences,
    setResearchPreferences,
    showDiagnostics,
    setShowDiagnostics,
  } = useStore();
  const color = useColors();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const dock = useDock();
  const [sheet, setSheet] = useState<SheetName | null>(null);
  const attention = updateNeedsAttention(useAppUpdate());
  const updates = updatesSupported();
  const scanner = overlayAvailable();
  const assistant = usePhoneSetting(scanner, isDefaultAssistant);
  const overPage = usePhoneSetting(scanner, canDrawOverApps);

  const savedPriorities = researchPreferences.products.filter((item) => item !== 'all').join(', ');

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
  const accessState = access.kind === 'trial' ? `${trialLeft} left` : access.kind === 'none' ? 'Locked' : 'Unlocked';

  const themeLabel = THEMES.find((option) => option.value === appearance)?.label ?? 'System';
  const textSizeLabel = TEXT_SIZE_OPTIONS.find((option) => option.value === textSize)?.label ?? 'Default';
  const motionLabel = MOTION_OPTIONS.find((option) => option.value === motion)?.label ?? 'System';
  const answerLengthLabel = ANSWER_LENGTH_OPTIONS.find((option) => option.value === answerStyle)?.label ?? 'Standard';
  const depthLabel = DEPTH_OPTIONS.find((option) => Number(option.value) === thoroughness)?.label ?? String(thoroughness);
  const sourceCountLabel =
    SOURCE_COUNT_OPTIONS.find((option) => Number(option.value) === researchPreferences.sourceCount)?.label
    ?? String(researchPreferences.sourceCount);
  const opacityLabel =
    OPACITY_OPTIONS.find((option) => Number(option.value) === nearestPuckOpacityStep(puckOpacity))?.label ?? 'Soft';
  const sourceLanguage = researchPreferences.sourceLanguage;
  const answerLanguage = researchPreferences.answerLanguage;
  const sourceLanguageLabel = sourceLanguage === 'any' ? 'Any' : nativeLanguageName(sourceLanguage);
  const answerLanguageLabel = answerLanguage === 'auto' ? 'Auto' : nativeLanguageName(answerLanguage);
  const interfaceLabel = language === 'tr' ? 'Türkçe' : 'English';
  const chatCount = `${threads.length} chat${threads.length === 1 ? '' : 's'}`;

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

  const onScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, layoutMeasurement, contentSize } = event.nativeEvent;
    dock.report({ offset: contentOffset.y, viewport: layoutMeasurement.height, content: contentSize.height });
  };

  const closeSheet = () => setSheet(null);

  return (
    <View style={styles.page}>
      <View style={[styles.topBar, { paddingTop: insets.top + 6 }]}>
        <MotionPressable
          onPress={() => router.back()}
          accessibilityRole="button"
          accessibilityLabel={tr('Back')}
          hitSlop={4}
          style={styles.back}
        >
          <BackIcon size={20} color={color.ink} />
        </MotionPressable>
        <Txt variant="cardTitle" tone="ink" numberOfLines={1} style={styles.title}>Settings</Txt>
        <View style={styles.backSpace} />
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
        scrollEventThrottle={16}
        onScroll={onScroll}
      >
        {/* A version, or a step it needs, comes first; otherwise it waits in About. */}
        {attention && updates ? (
          <SettingsSection label="Updates" delay={0}>
            <GlassCard radius={18} border={1} tint={color.surface} contentStyle={styles.cardPad}>
              <UpdateCard />
            </GlassCard>
          </SettingsSection>
        ) : null}

        <SettingsSection label="Access" delay={0}>
          <SettingsCard>
            <SettingRow
              icon={<KeyIcon size={17} color={color.accent} />}
              label={accessTitle}
              value={accessState}
              subtitle={accessDetail}
              onPress={() => setSheet('access')}
              accessibilityHint={access.kind === 'none' ? tr('Add access') : tr('Replace access')}
            />
            {access.kind === 'shared' || access.kind === 'own' ? (
              <SettingRow
                icon={<TrashIcon size={17} color={color.risk} />}
                label="Forget these keys"
                danger
                chevron={false}
                onPress={confirmForget}
              />
            ) : null}
          </SettingsCard>
        </SettingsSection>

        <SettingsSection label="Appearance" delay={40}>
          <SettingsCard>
            <SettingRow
              icon={<Palette size={17} color={color.accent} strokeWidth={1.7} />}
              label="Theme"
              value={themeLabel}
              onPress={() => setSheet('theme')}
            />
            <SettingRow
              icon={<TypeIcon size={17} color={color.accent} strokeWidth={1.7} />}
              label="Text size"
              value={textSizeLabel}
              onPress={() => setSheet('textSize')}
            />
            <SettingRow
              icon={<Zap size={17} color={color.accent} strokeWidth={1.7} />}
              label="Motion"
              value={motionLabel}
              onPress={() => setSheet('motion')}
            />
            <ToggleRow
              icon={<Vibrate size={17} color={color.accent} strokeWidth={1.7} />}
              label="Haptics"
              value={haptics}
              onChange={() => { tap(); setHaptics(!haptics); }}
            />
          </SettingsCard>
        </SettingsSection>

        <SettingsSection label="Language" delay={80}>
          <SettingsCard>
            <SettingRow
              icon={<Languages size={17} color={color.accent} strokeWidth={1.7} />}
              label="Interface language"
              value={interfaceLabel}
              onPress={() => setSheet('interface')}
            />
            <SettingRow
              icon={<GlobeIcon size={17} color={color.accent} />}
              label="Sources language"
              value={sourceLanguageLabel}
              valueTranslate={sourceLanguage === 'any'}
              onPress={() => setSheet('sources')}
            />
            <SettingRow
              icon={<PenLine size={17} color={color.accent} strokeWidth={1.7} />}
              label="Answers language"
              value={answerLanguageLabel}
              valueTranslate={answerLanguage === 'auto'}
              onPress={() => setSheet('answers')}
            />
          </SettingsCard>
        </SettingsSection>

        <SettingsSection label="How Kriko answers" delay={120}>
          <SettingsCard>
            <SettingRow
              icon={<Ruler size={17} color={color.accent} strokeWidth={1.7} />}
              label="Answer length"
              value={answerLengthLabel}
              onPress={() => setSheet('answerLength')}
            />
            <SettingRow
              icon={<SearchIcon size={17} color={color.accent} />}
              label="Research depth"
              value={depthLabel}
              onPress={() => setSheet('depth')}
            />
            <SettingRow
              icon={<ListChecks size={17} color={color.accent} strokeWidth={1.7} />}
              label="Sources to compare"
              value={sourceCountLabel}
              onPress={() => setSheet('sourceCount')}
            />
            <SettingRow
              icon={<Tag size={17} color={color.accent} strokeWidth={1.7} />}
              label="Products and priorities"
              value={savedPriorities || 'Any'}
              valueTranslate={!savedPriorities}
              onPress={() => setSheet('priorities')}
            />
            <ToggleRow
              icon={<TriangleAlert size={17} color={color.accent} strokeWidth={1.7} />}
              label="Include isolated reports"
              value={researchPreferences.includeIsolated}
              onChange={() => {
                tap();
                setResearchPreferences({ ...researchPreferences, includeIsolated: !researchPreferences.includeIsolated });
              }}
            />
            <ToggleRow
              icon={<Activity size={17} color={color.accent} strokeWidth={1.7} />}
              label="Include one-time issues"
              value={researchPreferences.includeOneTimeIssues}
              onChange={() => {
                tap();
                setResearchPreferences({ ...researchPreferences, includeOneTimeIssues: !researchPreferences.includeOneTimeIssues });
              }}
            />
            <ToggleRow
              icon={<Gauge size={17} color={color.accent} strokeWidth={1.7} />}
              label="Show usage details"
              value={showDiagnostics}
              onChange={() => { tap(); setShowDiagnostics(!showDiagnostics); }}
            />
          </SettingsCard>
        </SettingsSection>

        {scanner ? (
          <SettingsSection label="Floating scanner" delay={160}>
            <SettingsCard>
              <SettingRow
                icon={<ScanIcon size={17} color={color.accent} />}
                label="Transparency"
                value={opacityLabel}
                onPress={() => setSheet('transparency')}
              />
              <SettingRow
                icon={<Hand size={17} color={color.accent} strokeWidth={1.7} />}
                label="Scan with a long press"
                value={assistant ? 'Active' : 'Not set'}
                subtitle={assistant
                  ? 'Kriko is your phone’s assistant. Hold the power or home button to scan the screen at once.'
                  : 'In the list, choose Kriko under Digital assistant app, and keep “Use screenshot” on.'}
                onPress={() => { void openAssistantSettings(); }}
                accessibilityHint={assistant ? tr('Assistant settings') : tr('Set as assistant')}
              />
              <SettingRow
                icon={<GlobeIcon size={17} color={color.accent} />}
                label="Answer over your page"
                value={overPage ? 'Allowed' : 'Off'}
                subtitle={overPage
                  ? 'The answer opens over the page you scanned, so you never leave it.'
                  : 'Allow Kriko over other apps and the answer opens over the page you scanned, instead of taking you into Kriko.'}
                onPress={() => { void openDrawOverAppsSettings(); }}
                accessibilityHint={overPage ? tr('Over-other-apps settings') : tr('Allow over other apps')}
              />
            </SettingsCard>
          </SettingsSection>
        ) : null}

        <SettingsSection label="Data" delay={200}>
          <SettingsCard>
            <SettingRow
              icon={<ShieldIcon size={17} color={color.accent} />}
              label="Privacy and saved data"
              onPress={() => router.push('/privacy' as Href)}
            />
            <SettingRow
              icon={<TrashIcon size={17} color={color.risk} />}
              label="Clear chats and scan results"
              value={chatCount}
              danger
              chevron={false}
              onPress={confirmClear}
            />
            <SettingRow
              icon={<ResetIcon size={17} color={color.accent} />}
              label="Reset preferences"
              onPress={confirmReset}
            />
          </SettingsCard>
        </SettingsSection>

        {/* Its own effect runs due price checks whenever Settings opens, so it
            stays mounted here instead of hiding behind a row's sheet. */}
        <SettingsSection delay={220}>
          <PriceTracking onCheck={checkPriceWatch} />
        </SettingsSection>

        <SettingsSection label="About" delay={260}>
          {updates && !attention ? (
            <GlassCard radius={18} border={1} tint={color.surface} contentStyle={styles.cardPad}>
              <UpdateCard />
            </GlassCard>
          ) : null}
          <SettingsCard>
            <SettingRow
              icon={<HistoryIcon size={17} color={color.accent} />}
              label="History"
              onPress={() => router.push('/history' as Href)}
            />
            <SettingRow
              icon={<InfoIcon size={17} color={color.accent} />}
              label="About Kriko"
              onPress={() => router.push('/about' as Href)}
            />
          </SettingsCard>
          <Txt variant="monoSm" tone="ink3" style={styles.footer}>
            {`Kriko Agent for mobile · ${Constants.expoConfig?.version ?? '0.9'} · Mercury and DeepSeek are third-party services.`}
          </Txt>
        </SettingsSection>
      </ScrollView>

      <AccessSheet visible={sheet === 'access'} onClose={closeSheet} />

      <ChoiceSheet<Appearance>
        visible={sheet === 'theme'}
        title="Theme"
        subtitle="System follows your phone. White is brightest."
        options={THEMES.map((theme) => ({
          value: theme.value,
          label: theme.label,
          preview: <ThemeSwatch ground={theme.ground} card={theme.card} ink={theme.ink} accent={theme.accent} />,
        }))}
        selected={appearance}
        onSelect={setAppearance}
        onClose={closeSheet}
      />

      <ChoiceSheet<TextSize>
        visible={sheet === 'textSize'}
        title="Text size"
        subtitle="How large every answer and label is drawn."
        options={TEXT_SIZE_OPTIONS}
        selected={textSize}
        onSelect={setTextSize}
        onClose={closeSheet}
      />

      <ChoiceSheet<MotionPreference>
        visible={sheet === 'motion'}
        title="Motion"
        subtitle="Transitions and reveals. System follows your phone’s setting."
        options={MOTION_OPTIONS}
        selected={motion}
        onSelect={setMotion}
        onClose={closeSheet}
      />

      <ChoiceSheet<Language>
        visible={sheet === 'interface'}
        title="Interface language"
        subtitle="Answers follow the language you ask in."
        options={INTERFACE_OPTIONS}
        selected={language}
        onSelect={setAppLanguage}
        onClose={closeSheet}
      />

      <ChoiceSheet<SourceLanguage>
        visible={sheet === 'sources'}
        title="Sources language"
        subtitle="Any searches all languages by default."
        options={SOURCE_OPTIONS}
        selected={sourceLanguage}
        onSelect={(value) => setResearchPreferences({ ...researchPreferences, sourceLanguage: value })}
        onClose={closeSheet}
      />

      <ChoiceSheet<AnswerLanguage>
        visible={sheet === 'answers'}
        title="Answers language"
        subtitle="Auto follows your question; if unclear, uses the interface language."
        options={ANSWER_OPTIONS}
        selected={answerLanguage}
        onSelect={(value) => setResearchPreferences({ ...researchPreferences, answerLanguage: value })}
        onClose={closeSheet}
      />

      <ChoiceSheet<AnswerStyle>
        visible={sheet === 'answerLength'}
        title="Answer length"
        subtitle="Choose how much the agent writes."
        options={ANSWER_LENGTH_OPTIONS}
        selected={answerStyle}
        onSelect={setAnswerStyle}
        onClose={closeSheet}
      />

      <ChoiceSheet
        visible={sheet === 'depth'}
        title="Research depth"
        subtitle="Sets the maximum search budget. Kriko may stop early when the evidence is enough."
        options={DEPTH_OPTIONS}
        selected={String(thoroughness)}
        onSelect={(value) => setThoroughness(Number(value))}
        onClose={closeSheet}
      />

      <ChoiceSheet
        visible={sheet === 'sourceCount'}
        title="Sources to compare"
        subtitle="How many useful sources to aim for, up to ten."
        options={SOURCE_COUNT_OPTIONS}
        selected={String(researchPreferences.sourceCount)}
        onSelect={(value) => setResearchPreferences({ ...researchPreferences, sourceCount: Number(value) })}
        onClose={closeSheet}
      />

      <ChoiceSheet
        visible={sheet === 'transparency'}
        title="Transparency"
        subtitle="How see-through the floating K and its glass panels are. Faint shows the most of your page; Solid shows none."
        intro={<PuckPreview opacity={puckOpacity} />}
        options={OPACITY_OPTIONS}
        selected={String(nearestPuckOpacityStep(puckOpacity))}
        onSelect={(value) => setPuckOpacity(Number(value))}
        onClose={closeSheet}
      />

      <PrioritiesSheet
        visible={sheet === 'priorities'}
        products={researchPreferences.products}
        onSave={(products) => setResearchPreferences({ ...researchPreferences, products })}
        onClose={closeSheet}
      />
    </View>
  );
}

/** A phone setting the reader changes elsewhere; asked again whenever Kriko returns to the front. */
function usePhoneSetting(enabled: boolean, read: () => Promise<boolean>): boolean {
  const [value, setValue] = useState(false);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    const refresh = () => { void read().then((next) => { if (alive) setValue(next); }); };
    refresh();
    const subscription = AppState.addEventListener('change', (state) => { if (state === 'active') refresh(); });
    return () => { alive = false; subscription.remove(); };
  }, [enabled, read]);
  return value;
}

/** The palette choice as a tiny preview: ground, card, ink and accent. */
function ThemeSwatch({ ground, card, ink, accent }: { ground: string; card: string; ink: string; accent: string }) {
  const styles = useStyles();
  return (
    <View style={[styles.swatch, { backgroundColor: ground }]}>
      <View style={[styles.swatchCard, { backgroundColor: card }]}>
        <View style={[styles.swatchLine, { backgroundColor: ink, width: 14 }]} />
        <View style={[styles.swatchLine, { backgroundColor: ink, width: 8, opacity: 0.55 }]} />
      </View>
      <View style={[styles.swatchDot, { backgroundColor: accent }]} />
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  page: { flex: 1, backgroundColor: color.ground },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[2],
    paddingHorizontal: PAGE_X,
    paddingBottom: 8,
    backgroundColor: color.ground,
  },
  back: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edge,
  },
  backSpace: { width: 40, height: 40 },
  title: { flex: 1, textAlign: 'center' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: PAGE_X, paddingTop: 6, paddingBottom: 40, gap: gap[6] },
  cardPad: { padding: gap[4] },
  footer: { textAlign: 'center', paddingTop: gap[1], lineHeight: 17 },
  swatch: {
    width: 34,
    height: 30,
    borderRadius: 8,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  swatchCard: {
    width: 24,
    height: 17,
    borderRadius: 4,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  swatchLine: { height: 2, borderRadius: 1 },
  swatchDot: { position: 'absolute', width: 6, height: 6, borderRadius: 3, right: 4, top: 4 },
}));
