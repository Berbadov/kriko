/** Keeps the Android scanner connected to the research queue while other apps are visible. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, useColorScheme } from 'react-native';

import {
  isOverlayActive, overlayAvailable, startOverlaySession, stopOverlaySession,
  subscribeOverlayAction, subscribeOverlayScan, subscribeOverlaySession,
  setOverlayAppForeground, setOverlayUiReady, updateOverlayJobs, updateOverlayUi,
  type OverlayJob, type OverlayLabels, type OverlayScan,
} from '../engine/overlay';
import { readingTitle } from '../engine/prompt';
import { useStore } from '../engine/store';
import { discardFrame, keepThumbnail, writeFrame } from '../engine/thumbs';
import { tr } from '../i18n';
import { resolvePalette } from '../theme/preferences';

interface Session {
  active: boolean;
  available: boolean;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

const Context = createContext<Session | null>(null);

export function OverlaySessionProvider({ children }: { children: React.ReactNode }) {
  const store = useStore();
  const { queueJobs, readShot, enqueueScan, cancelQueue, language, appearance, puckOpacity } = store;
  const scheme = useColorScheme();
  const [active, setActive] = useState(false);
  const [readings, setReadings] = useState<OverlayJob[]>([]);
  const current = useRef({ queueJobs, readShot, enqueueScan, cancelQueue });
  useEffect(() => {
    current.current = { queueJobs, readShot, enqueueScan, cancelQueue };
  }, [queueJobs, readShot, enqueueScan, cancelQueue]);
  const waiting = useRef<(OverlayScan & { id: string })[]>([]);
  const processing = useRef(false);
  const mounted = useRef(true);
  const cancelled = useRef(new Set<string>());
  const readingAbort = useRef<{ id: string; controller: AbortController } | null>(null);

  // The bubble and panel draw themselves natively, so their words and palette
  // travel as data. `tr` gets the language explicitly, and `language` is the
  // memo's dependency, so switching it rebuilds every word and resends them.
  const labels = useMemo<OverlayLabels>(() => ({
    scan: tr('Scan', language),
    scanPage: tr('Scan this page', language),
    scanAgain: tr('Scan again', language),
    results: tr('Results', language),
    siteComments: tr('Site comments', language),
    queue: tr('Queue', language),
    stop: tr('Stop', language),
    now: tr('Now', language),
    all: tr('All', language),
    readSiteComments: tr('Read site comments', language),
    siteUrlHint: tr('Review site (optional)', language),
    cancel: tr('Cancel', language),
    close: tr('Close', language),
    queued: tr('Queued', language),
    running: tr('Running', language),
    reading: tr('Reading', language),
    done: tr('Done', language),
    error: tr('Error', language),
    cancelled: tr('Cancelled', language),
    productScan: tr('Product scan', language),
    sources: tr('Sources', language),
    queueFull: tr('Queue is full', language),
    dragHint: tr('Tap Kriko to scan this page. Press and hold for more.', language),
    dropToStop: tr('Drop here to stop sharing', language),
    notificationTitle: tr('Kriko screen scan is active', language),
    notificationText: tr('Tap the floating K to scan one screen when you choose.', language),
    stopSharing: tr('Stop screen sharing', language),
    channelName: tr('Floating screen scan', language),
    channelDescription: tr("Shows when Kriko's user-started floating scan session is active.", language),
    queueEmpty: tr('Scan a product page. Each scan joins the queue here.', language),
    answerEmpty: tr('Scan a product page to see its answer and sources here.', language),
    captureFailed: tr('Could not read that screen. Try scanning again.', language),
    sourceFailed: tr('Could not open that source.', language),
    copy: tr('Copy', language),
    copied: tr('Copied', language),
    scannedPage: tr('Scanned page', language),
    paused: tr('Screen capture paused', language),
    notificationPausedText: tr('Screen capture stopped. Tap Scan on the floating K to start it again.', language),
    resumeFailed: tr('Open Kriko and start the scanner again.', language),
    openingKriko: tr('Opening Kriko…', language),
    assistScanning: tr('Scanning this screen', language),
    assistNoShot: tr('Kriko could not see your screen. In your phone’s assistant settings, turn on “Use screenshot”.', language),
    // The brand reads the same in every language.
    assistTitle: 'Kriko',
    assistKeeps: tr('Kriko keeps reading. The answer will be in History.', language),
  }), [language]);

  // `system` follows the phone, exactly as the in-app theme provider resolves it.
  const theme = resolvePalette(appearance, scheme);

  const drain = useCallback(async () => {
    if (processing.current) return;
    processing.current = true;
    try {
      while (waiting.current.length && mounted.current) {
        const shot = waiting.current.shift()!;
        if (cancelled.current.delete(shot.id)) continue;
        const controller = new AbortController();
        readingAbort.current = { id: shot.id, controller };
        setReadings((items) => items.map((item) => item.id === shot.id
          ? { ...item, status: 'reading', text: 'Identifying appearance and product details…' } : item));
        // The scanner saves the frame as a file; if it could not, write one here.
        // Either way the reader gets its tighter look at a tall page, and the
        // chat gets a picture to keep.
        const frame = shot.uri || await writeFrame(shot.base64);
        try {
          const reading = await current.current.readShot(shot.base64, shot.mime, controller.signal, frame);
          if (!mounted.current) break;
          if (!cancelled.current.delete(shot.id)) {
            const picture = frame ? await keepThumbnail(frame) : undefined;
            current.current.enqueueScan(reading, picture, undefined, {
              researchMode: shot.mode ?? 'research', reviewSite: shot.reviewSite,
            });
          }
          setReadings((items) => items.filter((item) => item.id !== shot.id));
        } catch (error) {
          if (!mounted.current) break;
          if (cancelled.current.delete(shot.id)) continue;
          setReadings((items) => items.map((item) => item.id === shot.id
            ? { ...item, status: 'error', error: error instanceof Error ? error.message : 'The page could not be read.' }
            : item));
        } finally {
          readingAbort.current = null;
          await discardFrame(frame);
        }
      }
    } finally {
      processing.current = false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void isOverlayActive().then((value) => { if (mounted.current) setActive(value); }).catch(() => {});
    const offScan = subscribeOverlayScan((shot) => {
      if (waiting.current.length + (readingAbort.current ? 1 : 0) + current.current.queueJobs.filter((job) =>
        job.status === 'queued' || job.status === 'running').length >= 10) {
        setReadings((items) => [...items.filter((item) => item.id !== 'queue-full'), {
          id: 'queue-full', title: 'Queue is full', status: 'error',
          error: 'Wait for a product to finish, or cancel a queued scan.',
        }]);
        return;
      }
      const id = `read-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      waiting.current.push({ ...shot, id });
      setReadings((items) => [...items.slice(-9), {
        id, title: 'New product scan', status: 'queued', image: shot.uri || undefined,
      }]);
      void drain();
    });
    const offSession = subscribeOverlaySession(({ active: running }) => setActive(running));
    const offAction = subscribeOverlayAction(({ action, id }) => {
      if (action !== 'cancel') return;
      if (id.startsWith('read-') || id === 'queue-full') {
        cancelled.current.add(id);
        if (readingAbort.current?.id === id) readingAbort.current.controller.abort();
        waiting.current = waiting.current.filter((item) => item.id !== id);
        setReadings((items) => items.filter((item) => item.id !== id));
      } else {
        current.current.cancelQueue(id);
      }
    });
    // The scanner outlives this screen. While we are mounted it hands scans to
    // us; once we are gone it opens the app with the picture instead. Announced
    // last: a scan the phone assistant queued while the app was closed is
    // delivered the moment this is true, so the listener above must exist.
    setOverlayUiReady(true);
    return () => {
      mounted.current = false;
      waiting.current = [];
      readingAbort.current?.controller.abort();
      offScan(); offSession(); offAction();
      // Closing Kriko's screen must not end the scanner: only the reader's Stop does.
      setOverlayUiReady(false);
    };
  }, [drain]);

  // The scanner floats over the reader's own page, so it stands down while Kriko
  // itself is showing. Resent when the session becomes active: the native side
  // ignores a report that arrives before there is a session to receive it.
  useEffect(() => {
    setOverlayAppForeground(AppState.currentState === 'active');
    const subscription = AppState.addEventListener('change', (state) => {
      setOverlayAppForeground(state === 'active');
    });
    return () => subscription.remove();
  }, [active]);

  // Palette and words go first: the native side applies them to a live bubble
  // and keeps the last payload so the next session opens already themed.
  useEffect(() => {
    updateOverlayUi({ theme, labels, puckOpacity });
  }, [theme, labels, puckOpacity]);

  useEffect(() => {
    // Reading rows and queue titles are English keys at rest; translating them
    // on the way out means a language switch also reaches rows already queued.
    updateOverlayJobs([
      ...readings.map((item) => ({
        ...item,
        title: tr(item.title, language),
        text: item.text ? tr(item.text, language) : item.text,
        error: item.error ? tr(item.error, language) : item.error,
      })),
      ...[...queueJobs].reverse().sort((a, b) =>
        Number(b.status === 'running' || b.status === 'queued') -
        Number(a.status === 'running' || a.status === 'queued')).map((job) => ({
        id: job.id,
        title: `${readingTitle(job.reading) || tr('Product scan', language)}${job.researchMode === 'site_reviews' ? ` · ${tr('site comments', language)}` : ''}`,
        status: job.status, text: job.text, error: job.error, sources: job.sources, steps: job.steps,
        image: job.imageUri,
      })),
    ]);
  }, [queueJobs, readings, active, language]);

  const start = useCallback(async () => {
    await startOverlaySession();
    setActive(true);
  }, []);
  const stop = useCallback(async () => {
    await stopOverlaySession();
    setActive(false);
  }, []);

  return <Context.Provider value={{ active, available: overlayAvailable(), start, stop }}>
    {children}
  </Context.Provider>;
}

export function useOverlaySession(): Session {
  const value = useContext(Context);
  if (!value) throw new Error('OverlaySessionProvider is missing');
  return value;
}
