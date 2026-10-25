import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import {
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { useStore } from '../engine/store';
import { tr } from '../i18n';
import { font, gap } from '../theme/tokens';
import { makeStyles, useColors, useType } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { ActivityDots, MotionPressable, MotionView } from './Motion';
import { PasteIcon, XIcon } from './Icon';
import { Divider } from './Chrome';
import { Button } from './Primitives';
import { AnimatedSheet } from './AnimatedSheet';

type Mode = 'code' | 'own';

export function AccessSheet({ visible, onClose, firstRun, initialMode = 'code' }: {
  visible: boolean;
  onClose: () => void;
  firstRun?: boolean;
  initialMode?: Mode;
}) {
  const { unlock, saveOwnKeys } = useStore();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [label, setLabel] = useState('');
  const [mercury, setMercury] = useState('');
  const [deepseek, setDeepseek] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const color = useColors();
  const styles = useStyles();

  const paste = async (setter: (text: string) => void) => {
    try {
      const text = await Clipboard.getStringAsync();
      if (text) setter(text.trim());
    } catch {
      // Clipboard access is optional on this device.
    }
  };

  const submit = async (dismiss: () => void) => {
    if (busy) return;
    setBusy(true);
    setError('');
    await new Promise((resolve) => setTimeout(resolve, 40));
    try {
      if (mode === 'code') await unlock(code, password, label.trim() || 'Shared access');
      else await saveOwnKeys(mercury, deepseek);
      setCode('');
      setPassword('');
      setMercury('');
      setDeepseek('');
      dismiss();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'That did not open.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatedSheet visible={visible} onClose={onClose} style={styles.panel}>
      {(dismiss) => (
        <View style={styles.content}>
          <MotionView delay={0} style={styles.head}>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">{firstRun ? 'Start with Kriko' : 'Use Kriko'}</Txt>
              <Txt variant="bodyTight" tone="ink3">Keys stay on this phone.</Txt>
            </View>
            <MotionPressable onPress={dismiss} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close')} style={styles.close}>
              <XIcon size={20} color={color.ink2} />
            </MotionPressable>
          </MotionView>

          <Txt variant="bodyTight" tone="ink3">
            The person who shares access sends a code and password separately. Or add your own provider keys.
          </Txt>

          <View style={styles.tabs}>
            <Tab label="Access code" active={mode === 'code'} onPress={() => setMode('code')} />
            <Tab label="My own keys" active={mode === 'own'} onPress={() => setMode('own')} />
          </View>

          <ScrollView keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false} contentContainerStyle={styles.fields}>
            {mode === 'code' ? (
              <MotionView key={mode} delay={0} style={styles.fieldGroup}>
                <Field
                  label="Access code"
                  value={code}
                  onChangeText={setCode}
                  placeholder={tr('The long line that starts with S1NB…')}
                  multiline
                  autoCapitalize="none"
                  action={<MotionPressable onPress={() => paste(setCode)} hitSlop={8} accessibilityRole="button" accessibilityLabel={tr('Paste the access code')} style={styles.paste}><PasteIcon size={15} color={color.accent} /><Txt variant="actionSmall" tone="accent">Paste</Txt></MotionPressable>}
                />
                <Field label="Password" value={password} onChangeText={setPassword} placeholder={tr('Sent separately')} secureTextEntry autoCapitalize="none" />
                <Field label="Label · optional" value={label} onChangeText={setLabel} placeholder={tr('Who this access is from')} autoCapitalize="none" />
              </MotionView>
            ) : (
              <MotionView key={mode} delay={0} style={styles.fieldGroup}>
                <Field label="Mercury key" value={mercury} onChangeText={setMercury} placeholder="mercury_…" autoCapitalize="none" secureTextEntry />
                <Field label="DeepSeek key" value={deepseek} onChangeText={setDeepseek} placeholder="sk-…" autoCapitalize="none" secureTextEntry />
                <Txt variant="bodyTight" tone="ink3">Mercury writes the answer. DeepSeek searches and reads the web.</Txt>
              </MotionView>
            )}

            {error ? <Txt variant="bodyTight" tone="risk" accessibilityRole="alert">{error}</Txt> : null}
            {busy ? <View style={styles.progress}><ActivityDots color={color.accent} /><Txt variant="bodyTight" tone="ink3">Opening access on this phone…</Txt></View> : null}
            <Button label={busy ? 'Opening…' : mode === 'code' ? 'Use these keys' : 'Save the keys'} onPress={() => { void submit(dismiss); }} disabled={busy || (mode === 'code' ? !code.trim() || !password : !mercury.trim() || !deepseek.trim())} />

            <Divider />
            <Txt variant="bodyTight" tone="ink3" style={styles.foot}>
              Access codes are checked on this phone. Opened keys are stored in the system’s secure storage and are never shown again.
            </Txt>
          </ScrollView>
        </View>
      )}
    </AnimatedSheet>
  );
}

function Tab({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  const styles = useStyles();
  return (
    <MotionPressable onPress={onPress} accessibilityRole="tab" accessibilityState={{ selected: active }} style={[styles.tab, active && styles.tabOn]}>
      <Txt variant="actionSmall" tone={active ? 'accent' : 'muted'}>{label}</Txt>
    </MotionPressable>
  );
}

function Field({ label, value, onChangeText, placeholder, secureTextEntry, multiline, autoCapitalize, action }: {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  placeholder: string;
  secureTextEntry?: boolean;
  multiline?: boolean;
  autoCapitalize?: 'none' | 'sentences';
  action?: React.ReactNode;
}) {
  const color = useColors();
  const styles = useStyles();
  const type = useType();
  return (
    <View style={styles.field}>
      <View style={styles.fieldHead}>
        <Txt variant="monoSm" tone="ink3" caps>{label}</Txt>
        {action}
      </View>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={color.ink3}
        secureTextEntry={secureTextEntry}
        multiline={multiline}
        autoCapitalize={autoCapitalize ?? 'sentences'}
        autoCorrect={false}
        selectionColor={color.accent}
        style={[styles.input, type.input, multiline && styles.inputMulti]}
        accessibilityLabel={tr(label)}
      />
      <View style={styles.underline} />
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  panel: { maxHeight: '94%', paddingHorizontal: gap[4] },
  content: { gap: gap[3] },
  head: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  headText: { flex: 1, gap: 2 },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  tabs: { flexDirection: 'row', borderBottomWidth: 1, borderColor: color.edge },
  tab: { flex: 1, minHeight: 46, alignItems: 'center', justifyContent: 'center', borderBottomWidth: 2, borderBottomColor: 'transparent' },
  tabOn: { borderBottomColor: color.accent },
  fields: { gap: gap[3], paddingBottom: gap[2] },
  fieldGroup: { gap: gap[3] },
  field: { gap: 4 },
  fieldHead: { minHeight: 28, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  input: { minHeight: 42, paddingHorizontal: 0, paddingVertical: 7, color: color.ink, fontFamily: font.regular, fontSize: 16, lineHeight: 22 },
  inputMulti: { minHeight: 74, textAlignVertical: 'top' },
  underline: { height: StyleSheet.hairlineWidth, backgroundColor: color.edge },
  paste: { minHeight: 40, flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 4 },
  progress: { minHeight: 36, flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  foot: { lineHeight: 20 },
}));
