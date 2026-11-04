import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { BackIcon } from '../components/Icon';
import { HeaderAction, Hero, Page } from '../components/Chrome';
import { ProductCard } from '../components/ProductCard';
import { useStore } from '../engine/store';
import { loadScreenAudit, type ScreenAuditEntry } from '../engine/screenAudit';
import { gap, PAGE_X } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

export default function Privacy() {
  const { threads, queueJobs, showDiagnostics } = useStore();
  const [audits, setAudits] = useState<ScreenAuditEntry[]>([]);
  const color = useColors();
  const styles = useStyles();
  useEffect(() => { void loadScreenAudit().then(setAudits); }, []);
  const messages = threads.flatMap((thread) => thread.messages.map((message) => ({ thread, message })));
  return (
    <Page artHeight={0} actions={<HeaderAction label="Back" onPress={() => router.back()}><BackIcon size={21} color={color.ink} /></HeaderAction>}>
      <Hero crumb="kriko / privacy" title="Privacy and saved data" subtitle="What this phone keeps, and what a question sends." />
      <ScrollView contentContainerStyle={styles.body}>
        <View style={styles.section}>
          <Txt variant="rowTitle" tone="ink">Stored on this phone</Txt>
          <Txt variant="bodyTight" tone="ink3">Eligible simple answers may be reused from memory for up to ten minutes. This cache is not saved to disk and is cleared when you clear history or change access keys. Screen reads and product research are excluded.</Txt>
          <Txt variant="bodyTight" tone="ink3">Conversation text, answers, product reading fields, screenshots or their local thumbnail references, sources, and search/read steps are saved in app storage. Price watches are also stored here, including product name, merchant URL, currency, check interval, last observed price and next check time. Provider keys are stored separately using the phone’s secure storage. Chat history and price-watch records are not encrypted by Kriko itself. Clearing chats and scan results also clears screen-read audit thumbnails and records; price watches can be removed individually in Settings.</Txt>
        </View>
        <View style={styles.section}>
          <Txt variant="rowTitle" tone="ink">Sent to providers</Txt>
          <Txt variant="bodyTight" tone="ink3">The question and relevant context go to Mercury to write an answer. When a Mistral key is configured, eligible simple text questions may go to Mistral instead. Search terms and selected pages go to DeepSeek Search and Fetch. A screenshot is uploaded to DeepSeek vision when image reading is needed. Product research may fetch the exact merchant result page to extract product metadata and its image URL, then request the advertised image from its HTTPS host. Tracked price checks request the saved product page and search provider. These third-party providers and sites process requests under their own terms. This build has no Kriko account or analytics upload.</Txt>
        </View>
        <View style={styles.section}>
          <Txt variant="rowTitle" tone="ink">Voice typing</Txt>
          <Txt variant="bodyTight" tone="ink3">The microphone starts only when you tap it and stops when you finish, cancel, or leave the app. Android’s speech recognition service processes the audio and may send it to its provider. Kriko does not save audio recordings. Recognized words stay in your editable draft until you press Send; sending includes them in the normal question and history.</Txt>
        </View>
        <View style={styles.section}>
          <Txt variant="rowTitle" tone="ink">Screen reads</Txt>
          <Txt variant="bodyTight" tone="ink3">Each attempted vision read is recorded before upload. The log keeps a small local screenshot thumbnail, time, outcome, and observed product text. A screenshot can include personal or sensitive information visible on screen; review what you capture before asking Kriko to read it. Provider keys and raw error details are never saved in the audit record.</Txt>
          {audits.length ? audits.map((audit) => (
            <View key={audit.id} style={styles.entry}>
              <Txt variant="meta" tone="ink">{new Date(audit.at).toLocaleString()} · {audit.status === 'success' ? 'Read complete' : audit.status === 'error' ? 'Read failed' : 'Read in progress'}</Txt>
              {audit.reading ? <Txt variant="bodyTight" tone="ink2">Observed: {[audit.reading.brand, audit.reading.product, audit.reading.model, audit.reading.price, audit.reading.condition, audit.reading.detail, audit.reading.note, audit.reading.visualDescription].filter(Boolean).join(' · ') || 'No text returned'}</Txt> : null}
              {audit.imageUri ? <ProductCard reading={audit.reading} imageUri={audit.imageUri} /> : <Txt variant="meta" tone="ink3">No thumbnail could be kept for this capture.</Txt>}
            </View>
          )) : <Txt variant="bodyTight" tone="ink3">No screen reads recorded.</Txt>}
        </View>
        <View style={styles.section}>
          <Txt variant="rowTitle" tone="ink">Saved conversation content</Txt>
          {messages.length ? messages.map(({ thread, message }) => (
            <View key={`${thread.id}-${message.id}`} style={styles.entry}>
              <Txt variant="meta" tone="ink">{thread.title} · {message.role === 'user' ? 'You sent' : 'Kriko answered'}</Txt>
              {message.text ? <Txt variant="bodyTight" tone="ink2">{message.text}</Txt> : null}
              {message.reading ? <Txt variant="bodyTight" tone="ink3">Product details saved: {[message.reading.brand, message.reading.product, message.reading.model, message.reading.price, message.reading.condition, message.reading.detail, message.reading.note].filter(Boolean).join(' · ')}</Txt> : null}
              {message.imageUri ? <Txt variant="meta" tone="ink3">A screenshot reference is saved with this message.</Txt> : null}
              {message.imageUri ? <ProductCard reading={message.reading} imageUri={message.imageUri} /> : null}
              {message.sources?.map((source) => <Txt key={source.url} variant="meta" tone="ink3">Source: {source.title} — {source.url}</Txt>)}
              {message.steps?.filter((step) => showDiagnostics || !step.text.startsWith('diagnostic:')).map((step) => <Txt key={step.id} variant="meta" tone="ink3">{step.kind}: {step.text}</Txt>)}
              {message.error ? <Txt variant="meta" tone="risk">Saved error: {message.error}</Txt> : null}
            </View>
          )) : <Txt variant="bodyTight" tone="ink3">No saved chat or scan content.</Txt>}
        </View>
        <View style={styles.section}>
          <Txt variant="rowTitle" tone="ink">Saved scan queue</Txt>
          {queueJobs.length ? queueJobs.map((job) => (
            <View key={job.id} style={styles.entry}>
              <Txt variant="meta" tone="ink">{job.reading.product || job.reading.brand || 'Product scan'} · {job.status}</Txt>
              <Txt variant="bodyTight" tone="ink2">Question: {job.question}</Txt>
              <Txt variant="bodyTight" tone="ink2">Saved result: {job.text || (job.error ? `Failed: ${job.error}` : 'No answer saved')}</Txt>
              <Txt variant="bodyTight" tone="ink3">Product details: {[job.reading.brand, job.reading.product, job.reading.model, job.reading.price, job.reading.condition, job.reading.detail, job.reading.note].filter(Boolean).join(' · ') || 'None recorded'}</Txt>
              {job.imageUri ? <ProductCard reading={job.reading} imageUri={job.imageUri} /> : null}
              {job.sources.map((source) => <Txt key={source.url} variant="meta" tone="ink3">Source: {source.title} — {source.url}</Txt>)}
              {job.steps.filter((step) => showDiagnostics || !step.text.startsWith('diagnostic:')).map((step) => <Txt key={step.id} variant="meta" tone="ink3">{step.kind}: {step.text}</Txt>)}
            </View>
          )) : <Txt variant="bodyTight" tone="ink3">No saved scan queue records.</Txt>}
        </View>
      </ScrollView>
    </Page>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  body: { paddingHorizontal: PAGE_X, paddingBottom: 44, gap: gap[5] },
  section: { gap: gap[2] },
  entry: { gap: gap[1], paddingVertical: gap[2], borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: color.edge },
}));
