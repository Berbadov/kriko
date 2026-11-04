import { useEffect, useState } from 'react';
import { Alert, AppState, TextInput, View, StyleSheet } from 'react-native';
import { Button, SectionLabel } from './Primitives';
import { Txt } from '../theme/Txt';
import { makeStyles, useColors } from '../theme/theme';
import { gap, radius } from '../theme/tokens';
import { addPriceWatch, loadPriceWatches, PRICE_INTERVALS, removePriceWatch, updatePriceWatch, type PriceInterval, type PriceWatch } from '../engine/priceTracking';

/** Embeddable settings surface. Parent performs credentialed checks via secure store. */
export function PriceTracking({ onCheck }: { onCheck: (watchId: string) => Promise<void> }) {
  const color = useColors(), styles = useStyles();
  const [items, setItems] = useState<PriceWatch[]>([]), [url, setUrl] = useState(''), [name, setName] = useState(''), [currency, setCurrency] = useState('USD'), [interval, setInterval] = useState<PriceInterval>(24), [busy, setBusy] = useState(false), [autoErrors, setAutoErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    let mounted = true;
    loadPriceWatches().then(watches => { if (mounted) setItems(watches); });
    return () => { mounted = false; };
  }, []);
  useEffect(() => {
    let live = true;
    let checking = false;
    const runDue = async () => {
      if (!live || checking || AppState.currentState !== 'active') return;
      checking = true;
      try {
        const watches = await loadPriceWatches();
        for (const watch of watches) {
          if (!live || AppState.currentState !== 'active') break;
          if (watch.paused || watch.nextCheckAt > Date.now()) continue;
          try {
            await onCheck(watch.id);
            if (live) setAutoErrors(current => { const next = { ...current }; delete next[watch.id]; return next; });
          } catch (error) {
            // Access can expire or be absent; keep this visible on the watch and continue to others.
            if (live) setAutoErrors(current => ({ ...current, [watch.id]: error instanceof Error ? error.message : 'Could not check this price.' }));
          }
        }
        if (live) setItems(await loadPriceWatches());
      } catch {
        // A temporary storage read failure should not break the foreground timer.
      } finally { checking = false; }
    };
    void runDue();
    const startInterval = globalThis.setInterval as unknown as (handler: () => void, milliseconds: number) => number;
    const stopInterval = globalThis.clearInterval as unknown as (handle: number) => void;
    const timer = startInterval(() => { void runDue(); }, 60_000);
    const subscription = AppState.addEventListener('change', state => { if (state === 'active') void runDue(); });
    return () => { live = false; stopInterval(timer); subscription.remove(); };
  }, [onCheck]);
  const act = async (work: () => Promise<PriceWatch[]>) => { setBusy(true); try { setItems(await work()); } catch (error) { Alert.alert('Price tracking', error instanceof Error ? error.message : 'Could not update tracking.'); } finally { setBusy(false); } };
  const field = (value: string, setValue: (v: string) => void, placeholder: string, autoCapitalize: 'none' | 'words' | 'characters' = 'none') => <TextInput value={value} onChangeText={setValue} placeholder={placeholder} placeholderTextColor={color.ink3} autoCapitalize={autoCapitalize} style={styles.input} accessibilityLabel={placeholder} />;
  return <View style={styles.wrap}>
    <SectionLabel>Price tracking</SectionLabel>
    <Txt variant="bodyTight" tone="ink3">Checks run only while Kriko is open and active. There is no background scheduler; due checks run when you open this screen.</Txt>
    {field(name, setName, 'Product name', 'words')}{field(url, setUrl, 'https://shop.example/product')}{field(currency, setCurrency, 'Currency (USD, EUR, TRY)', 'characters')}
    <Txt variant="sectionLabel" tone="ink2">Check interval</Txt>
    <View style={styles.options}>{PRICE_INTERVALS.map(hours => <Button key={hours} label={hours < 24 ? `${hours}h` : `${hours / 24}d`} variant={interval === hours ? 'primary' : 'quiet'} onPress={() => setInterval(hours)} />)}</View>
    <Button label="Track product" onPress={() => void act(async () => { const result = await addPriceWatch({ name, url, currency, intervalHours: interval }); setName(''); setUrl(''); return result; })} disabled={busy} />
    {items.map(item => <View key={item.id} style={styles.card}>
      <Txt variant="rowTitle" tone="ink">{item.name}</Txt><Txt variant="meta" tone="ink3" numberOfLines={1}>{item.url}</Txt>
      <Txt variant="bodyTight" tone="ink2">{item.lastPrice === null ? 'No price observed yet' : `Last observed: ${item.currency} ${item.lastPrice}`} · {item.lastObservedAt ? new Date(item.lastObservedAt).toLocaleString() : 'not checked'}</Txt>
      {autoErrors[item.id] || item.lastError ? <Txt variant="meta" tone="warn">{autoErrors[item.id] || item.lastError}</Txt> : null}
      <Txt variant="meta" tone="ink3">{item.paused ? 'Paused' : `Next due ${new Date(item.nextCheckAt).toLocaleString()}`}</Txt>
      <Txt variant="sectionLabel" tone="ink2">Check interval</Txt>
      <View style={styles.options}>{PRICE_INTERVALS.map(hours => <Button key={hours} label={hours < 24 ? `${hours}h` : `${hours / 24}d`} variant={item.intervalHours === hours ? 'primary' : 'quiet'} onPress={() => void act(() => updatePriceWatch(item.id, { intervalHours: hours }))} disabled={busy} />)}</View>
      <View style={styles.options}>
        <Button label={item.paused ? 'Resume' : 'Pause'} onPress={() => void act(() => updatePriceWatch(item.id, { paused: !item.paused }))} disabled={busy} />
        <Button label="Check now" onPress={() => void act(async () => { await onCheck(item.id); return loadPriceWatches(); })} disabled={busy} />
        <Button label="Remove" onPress={() => void act(() => removePriceWatch(item.id))} disabled={busy} />
      </View>
    </View>)}
  </View>;
}

const useStyles = makeStyles(color => StyleSheet.create({ wrap: { gap: gap[3], marginTop: gap[4] }, input: { minHeight: 46, borderWidth: 1, borderColor: color.edgeStrong, borderRadius: radius.m, color: color.ink, paddingHorizontal: gap[3], fontSize: 15 }, options: { flexDirection: 'row', flexWrap: 'wrap', gap: gap[2] }, card: { gap: gap[2], backgroundColor: color.surface, borderRadius: radius.m, borderWidth: 1, borderColor: color.edge, padding: gap[3] } }));
