/**
 * A screenshot becomes a question: read it, show what was read, let it be
 * corrected, then ask.
 *
 * The image does leave the phone here — DeepSeek's vision model reads it — and
 * the sheet says so in the same breath as the action. What stays is the text
 * the reader confirmed; the picture is only kept as a thumbnail beside their
 * message.
 */

import { Image } from 'expo-image';
import { useEffect, useRef, useState } from 'react';
import {
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { useStore } from '../engine/store';
import { hasProductReading } from '../engine/reading';
import { tr } from '../i18n';
import type { Reading } from '../engine/types';
import { font, gap, radius } from '../theme/tokens';
import { makeStyles, useColors, useType } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { ActivityDots, MotionPressable, MotionView } from './Motion';
import { XIcon } from './Icon';
import { Divider } from './Chrome';
import { Button, SectionLabel } from './Primitives';
import { AnimatedSheet } from './AnimatedSheet';

export interface Shot {
  uri: string;
  base64: string;
  mime: string;
}

const EMPTY: Reading = {
  brand: '',
  product: '',
  model: '',
  price: '',
  condition: 'unknown',
  detail: '',
  note: '',
};

const CONDITIONS = ['unknown', 'new', 'used', 'refurbished'] as const;

export function ScreenshotSheet({
  shot,
  onClose,
  onAsk,
}: {
  shot: Shot;
  onClose: () => void;
  onAsk: (reading: Reading, question: string) => void;
}) {
  const { readShot } = useStore();
  const [reading, setReading] = useState<Reading>(EMPTY);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [readAttempt, setReadAttempt] = useState(0);
  const askAfterDismiss = useRef<{ reading: Reading; question: string } | null>(null);

  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    const run = async () => {
      try {
        const result = await readShot(shot.base64, shot.mime, controller.signal, shot.uri);
        if (alive) setReading(result);
      } catch (caught) {
        if (!alive) return;
        setError(
          caught instanceof Error
            ? caught.message
            : 'The image could not be read. Type what the listing says instead.',
        );
      } finally {
        if (alive) setBusy(false);
      }
    };
    void run();
    return () => {
      alive = false;
      controller.abort();
    };
  }, [shot, readShot, readAttempt]);

  const color = useColors();
  const styles = useStyles();

  const named = hasProductReading(reading);
  const canAsk = !busy && named;
  const retryRead = () => {
    setReading(EMPTY);
    setError('');
    setBusy(true);
    setReadAttempt((attempt) => attempt + 1);
  };

  const set = (key: keyof Reading, value: string) =>
    setReading((current) => ({ ...current, [key]: value, ...(key === 'model' && value.trim() ? { identityBasis: 'mixed' as const } : {}) }));

  return (
    <AnimatedSheet visible onClose={() => {
      onClose();
      const pending = askAfterDismiss.current;
      askAfterDismiss.current = null;
      if (pending) onAsk(pending.reading, pending.question);
    }} style={styles.panel}>
      {(dismiss) => (
        <View style={styles.content}>
          <MotionView delay={0} style={styles.head}>
            <View style={styles.headText}>
              <Txt variant="productTitle" tone="ink">
                Identify the product
              </Txt>
              <Txt variant="bodyTight" tone="ink3">
                {busy ? 'Looking at appearance and text…' : error ? 'Could not finish reading' : 'Check the details, then ask'}
              </Txt>
            </View>
            <MotionPressable onPress={dismiss} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr('Close')}>
              <XIcon size={21} color={color.ink3} />
            </MotionPressable>
          </MotionView>

          <ScrollView
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
            contentContainerStyle={styles.body}
          >
            <MotionView key="preview" delay={35} style={styles.preview}>
              <Image
                source={{ uri: shot.uri }}
                style={styles.image}
                contentFit="contain"
                accessibilityLabel={tr('Full screenshot being read')}
              />
              {busy ? (
                <View style={styles.previewBusy}>
                  <ActivityDots color={color.accent} />
                  <Txt variant="bodyTight" tone="ink">Recognising the product</Txt>
                </View>
              ) : null}
            </MotionView>

            {error ? (
              <MotionView key={`error-${readAttempt}`} delay={0} style={styles.error}>
                <Txt variant="bodyTight" tone="risk">{error}</Txt>
                <Txt variant="bodyTight" tone="ink3">Fill in the product by hand; the question still works.</Txt>
                <Button label="Try reading again" variant="ghost" onPress={retryRead} />
              </MotionView>
            ) : null}

            {!busy && (reading.visualDescription || reading.visualCandidates?.length || reading.identityBasis === 'appearance' || reading.identityBasis === 'unknown') ? (
              <MotionView delay={50} style={styles.visualCard}>
                <SectionLabel>{reading.identityBasis === 'appearance' || reading.identityBasis === 'unknown' ? 'Possible visual identification' : 'Appearance and text'}</SectionLabel>
                {reading.visualDescription ? <Txt variant="bodyTight" tone="ink2">{reading.visualDescription}</Txt> : null}
                {reading.visualCandidates?.map((candidate) => (
                  <View key={candidate.name} style={styles.visualMatch}>
                    <Txt variant="rowTitle" tone="ink">Possible: {candidate.name}</Txt>
                    <Txt variant="monoSm" tone="ink3">{candidate.confidence} confidence · visual match</Txt>
                    {candidate.reason ? <Txt variant="bodyTight" tone="ink3">{candidate.reason}</Txt> : null}
                  </View>
                ))}
                {reading.visualCandidates?.length || reading.identityBasis === 'appearance' || reading.identityBasis === 'unknown' ? <Txt variant="bodyTight" tone="ink3">Similar models may look alike. These matches guide research; they do not confirm the exact model.</Txt> : null}
              </MotionView>
            ) : null}

            <MotionView delay={70} style={styles.fields}>
              <View style={styles.groupHead}>
                <SectionLabel>Listing details</SectionLabel>
                <Txt variant="bodyTight" tone="ink3">Adjust anything that looks off.</Txt>
              </View>
              <EditField label="Brand" value={reading.brand} onChangeText={(value) => set('brand', value)} placeholder="Samsung" />
              <EditField label="Product" value={reading.product} onChangeText={(value) => set('product', value)} placeholder="Galaxy Buds2 Pro" />
              <View style={styles.pair}>
                <EditField
                  label="Model"
                  value={reading.model}
                  onChangeText={(value) => set('model', value)}
                  placeholder="SM-R510"
                  style={styles.pairField}
                />
                <EditField
                  label="Price"
                  value={reading.price}
                  onChangeText={(value) => set('price', value)}
                  placeholder="$189"
                  style={styles.pairField}
                />
              </View>
              <View style={styles.condition}>
                <Txt variant="monoSm" tone="ink3" caps>
                  Condition
                </Txt>
                <View style={styles.chips}>
                  {CONDITIONS.map((condition) => {
                    const active = reading.condition === condition;
                    return (
                      <MotionView key={`${condition}-${active}`} delay={0} style={styles.conditionMotion}>
                      <MotionPressable
                        onPress={() => set('condition', condition)}
                        accessibilityRole="button"
                        accessibilityState={{ selected: active }}
                        style={[styles.chip, active && styles.chipOn]}
                      >
                        <Txt variant="monoSm" tone={active ? color.onAccent : 'ink3'} caps>
                          {condition}
                        </Txt>
                      </MotionPressable>
                      </MotionView>
                    );
                  })}
                </View>
              </View>
            </MotionView>

            <MotionView delay={110} style={styles.detail}>
              <Divider />
              <EditField
                label="Visible listing text"
                value={reading.detail}
                onChangeText={(value) => set('detail', value)}
                placeholder="Title, variant, specs, seller claims…"
                multiline
              />
            </MotionView>

            {reading.note && !error ? (
              <Txt variant="bodyTight" tone="ink3" style={styles.note}>
                {reading.note}
              </Txt>
            ) : null}

            <MotionView delay={150} style={styles.question}>
              <Divider />
              <EditField
                label="Your question · optional"
                value={question}
                onChangeText={setQuestion}
                placeholder={tr('What should I check before buying it?')}
              />
            </MotionView>
          </ScrollView>

          <View style={styles.footer}>
            <Button label={busy ? 'Reading…' : 'Ask about this'} onPress={() => { askAfterDismiss.current = { reading, question }; dismiss(); }} disabled={!canAsk} />
            <Txt variant="bodyTight" tone="ink3" style={styles.privacy}>
              The image is sent to DeepSeek to read it. Kriko keeps the observations above and the
              thumbnail in your message.
            </Txt>
          </View>
        </View>
      )}
    </AnimatedSheet>
  );
}

function EditField({
  label,
  value,
  onChangeText,
  placeholder,
  multiline,
  style,
}: {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  placeholder: string;
  multiline?: boolean;
  style?: object;
}) {
  const color = useColors();
  const styles = useStyles();
  const type = useType();
  return (
    <View style={[styles.field, style]}>
      <Txt variant="monoSm" tone="ink3" caps>
        {label}
      </Txt>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={color.ink4}
        multiline={multiline}
        selectionColor={color.accent}
        style={[styles.input, type.body, multiline && styles.inputMulti]}
        accessibilityLabel={tr(label)}
      />
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  panel: { paddingTop: 14, paddingHorizontal: 18, maxHeight: '93%' },
  content: { gap: gap[3], flexShrink: 1 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: gap[3] },
  headText: { flex: 1, gap: 3 },
  body: { gap: gap[4], paddingBottom: gap[4] },
  preview: {
    borderRadius: radius.l,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.surface,
    height: 230,
  },
  image: { width: '100%', height: '100%', backgroundColor: color.surface },
  previewBusy: {
    position: 'absolute',
    left: 10,
    right: 10,
    bottom: 10,
    minHeight: 42,
    borderRadius: radius.m,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edge,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: gap[2],
  },
  error: { gap: gap[2], paddingVertical: gap[1] },
  visualCard: { gap: gap[2], padding: 14, borderRadius: radius.m, backgroundColor: color.inset },
  visualMatch: { gap: 4, paddingVertical: 6 },
  fields: { gap: gap[3] },
  groupHead: { gap: 3, paddingBottom: gap[1] },
  detail: { gap: gap[3] },
  question: { gap: gap[3] },
  field: { gap: 6 },
  pair: { flexDirection: 'row', gap: gap[3] },
  pairField: { flex: 1 },
  condition: { gap: 7 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 7 },
  conditionMotion: { borderRadius: radius.s },
  chip: {
    borderWidth: 1,
    borderColor: color.edge,
    borderRadius: radius.s,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  chipOn: { backgroundColor: color.accent, borderColor: color.accent },
  input: {
    borderBottomWidth: 1,
    borderColor: color.edge,
    backgroundColor: 'transparent',
    paddingHorizontal: 0,
    paddingVertical: 8,
    color: color.ink,
    fontFamily: font.regular,
    fontSize: 15,
    lineHeight: 20,
  },
  inputMulti: { minHeight: 80, textAlignVertical: 'top' },
  note: { lineHeight: 20, paddingVertical: gap[1] },
  footer: { gap: gap[2], paddingBottom: 22 },
  privacy: { lineHeight: 18 },
}));
