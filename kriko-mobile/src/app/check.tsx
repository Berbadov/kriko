/**
 * Check: confirm what the reader found before it searches.
 *
 * The image is read on the phone. Only the text on this screen is sent, which is
 * the promise the screen has to make visible — and every field is editable,
 * because a reading that cannot be corrected is not a confirmation.
 */

import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { SAMPLE_SHOT, shotSource } from '../assets/shots';
import { Divider, Hero, HeaderAction, Page } from '../components/Chrome';
import { ChevronRightIcon, SearchIcon, XIcon } from '../components/Icon';
import { Button, Card, SectionLabel } from '../components/Primitives';
import { PrivacyNote } from '../components/Run';
import { SCREENSHOT_READING } from '../engine/research';
import { useStore } from '../engine/store';
import { color, font, gap, radius } from '../theme/tokens';
import { Txt } from '../theme/Txt';

type FieldKey = 'brand' | 'product' | 'model';

const FIELD_LABELS: Record<FieldKey, string> = {
  brand: 'Brand',
  product: 'Product',
  model: 'Model number',
};

export default function Check() {
  const { ask, web, pendingShot, setPendingShot } = useStore();
  const [failed, setFailed] = useState(false);
  const [brand, setBrand] = useState(SCREENSHOT_READING.brand);
  const [product, setProduct] = useState(SCREENSHOT_READING.product);
  const [model, setModel] = useState<string | null>(null);
  const [editing, setEditing] = useState<FieldKey | null>(null);

  /** A picked image that will not open falls back to the shipped sample. */
  const uri = failed ? SAMPLE_SHOT : (pendingShot ?? SAMPLE_SHOT);
  const usingSample = uri === SAMPLE_SHOT;

  const title = [brand, product].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();

  const find = () => {
    const thread = ask({
      query: title || 'Shared screenshot',
      title: title || 'Shared screenshot',
      kind: 'screenshot',
      imageUri: uri,
      web,
    });
    setPendingShot(null);
    router.replace(`/product/${thread.id}`);
  };

  const valueOf = (key: FieldKey) => (key === 'brand' ? brand : key === 'product' ? product : model);
  const setValue = (key: FieldKey, next: string) => {
    if (key === 'brand') setBrand(next);
    else if (key === 'product') setProduct(next);
    else setModel(next.trim() || null);
  };

  return (
    <Page
      artHeight={220}
      actions={
        <HeaderAction label="Close" onPress={() => router.back()}>
          <XIcon size={22} color="#FFFFFF" />
        </HeaderAction>
      }
      footer={
        <View style={styles.footer}>
          <Button label="Find product" icon={<SearchIcon size={19} color="#FFFFFF" />} onPress={find} />
          <Button label="Choose another" variant="ghost" onPress={() => router.back()} />
        </View>
      }
    >
      <Hero
        crumb="kriko / chat / screenshot"
        title="Check"
        subtitle="Confirm what the reader found before it searches."
      />

      <View style={styles.body}>
        <Card style={styles.shotCard}>
          <Image
            source={shotSource(uri)}
            style={styles.shot}
            contentFit="cover"
            contentPosition="top"
            onError={() => setFailed(true)}
          />
          <View style={styles.shotText}>
            <Txt variant="cardTitle" tone="ink">
              {usingSample ? 'Sample screenshot' : 'Shared screenshot'}
            </Txt>
            <Txt variant="mono" tone="ink3">
              read on this phone
            </Txt>
          </View>
          <Button label="Change" variant="ghost" style={styles.change} onPress={() => router.back()} />
        </Card>

        <Card style={styles.fields}>
          <SectionLabel>Read from the image</SectionLabel>
          <Field
            label={FIELD_LABELS.brand}
            value={brand}
            onPress={() => setEditing('brand')}
          />
          <Divider />
          <Field
            label={FIELD_LABELS.product}
            value={product}
            onPress={() => setEditing('product')}
          />
          <Divider />
          <Field
            label={FIELD_LABELS.model}
            value={model ?? 'Not visible in the image'}
            muted={!model}
            action={model ? undefined : 'Add'}
            onAction={() => setEditing('model')}
            onPress={() => setEditing('model')}
          />
        </Card>

        <PrivacyNote title="Only this text is sent" body="The image stays on this phone." />
      </View>

      <FieldEditor
        key={editing ?? 'closed'}
        field={editing}
        value={editing ? (valueOf(editing) ?? '') : ''}
        onClose={() => setEditing(null)}
        onSave={(next) => {
          if (editing) setValue(editing, next);
          setEditing(null);
        }}
      />
    </Page>
  );
}

function Field({
  label,
  value,
  muted,
  action,
  onAction,
  onPress,
}: {
  label: string;
  value: string;
  muted?: boolean;
  action?: string;
  onAction?: () => void;
  onPress?: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${label}: ${value}. Change it.`}
      style={({ pressed }) => [styles.field, pressed && styles.pressed]}
    >
      <View style={styles.fieldText}>
        <Txt variant="stepMeta" tone="ink3">
          {label}
        </Txt>
        <Txt variant="fieldValue" tone={muted ? 'ink3' : 'ink'} numberOfLines={2}>
          {value}
        </Txt>
      </View>
      {action ? (
        <Button label={action} variant="ghost" style={styles.addBtn} onPress={onAction} />
      ) : (
        <ChevronRightIcon size={20} color={color.ink3} />
      )}
    </Pressable>
  );
}

/** The sheet that edits one field: the reader's correction, not a rescue. */
function FieldEditor({
  field,
  value,
  onClose,
  onSave,
}: {
  field: FieldKey | null;
  value: string;
  onClose: () => void;
  onSave: (next: string) => void;
}) {
  const [draft, setDraft] = useState(value);

  return (
    <Modal visible={field !== null} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.sheetWrap}
      >
        <Pressable style={styles.scrim} onPress={onClose} accessibilityLabel="Close" />
        <View style={styles.sheet}>
          <Txt variant="cardTitle" tone="ink">
            {field ? FIELD_LABELS[field] : ''}
          </Txt>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            autoFocus
            selectionColor={color.accent}
            placeholder={field === 'model' ? 'e.g. SM-R510' : 'Type what the listing says'}
            placeholderTextColor={color.ink3}
            style={styles.input}
            returnKeyType="done"
            onSubmitEditing={() => onSave(draft)}
          />
          <View style={styles.sheetActions}>
            <Button label="Cancel" variant="ghost" style={styles.flex} onPress={onClose} />
            <Button label="Save" style={styles.flex} onPress={() => onSave(draft)} />
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: 16, gap: gap[3] },
  shotCard: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  shot: {
    width: 56,
    height: 74,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.edgeStrong,
    backgroundColor: color.inset,
  },
  shotText: { flex: 1, gap: 3 },
  change: { height: 40, paddingHorizontal: 14 },
  fields: { gap: gap[1], paddingVertical: 15 },
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: gap[3],
    paddingVertical: 9,
  },
  fieldText: { flex: 1, gap: 4 },
  addBtn: { height: 40, paddingHorizontal: 14 },
  pressed: { opacity: 0.7 },
  footer: { gap: gap[2] },
  sheetWrap: { flex: 1, justifyContent: 'flex-end' },
  scrim: { ...StyleSheet.absoluteFill, backgroundColor: color.scrim },
  sheet: {
    backgroundColor: color.surface,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    borderWidth: 1,
    borderColor: color.edge,
    padding: 20,
    paddingBottom: 28,
    gap: gap[4],
  },
  input: {
    borderWidth: 1,
    borderColor: color.edgeStrong,
    borderRadius: radius.m,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: color.ink,
    fontFamily: font.regular,
    fontSize: 16,
    backgroundColor: color.inset,
  },
  sheetActions: { flexDirection: 'row', gap: gap[2] },
  flex: { flex: 1 },
});
