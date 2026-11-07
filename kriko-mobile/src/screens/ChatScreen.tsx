/**
 * A warm paper conversation view, with the scanner and queue always close by.
 *
 * The agent's work is visible while it happens — searches, pages read — and the
 * answer arrives under it with its sources. A screenshot or the phone's own
 * screen enters through the same composer.
 */

import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { router, useFocusEffect, type Href } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  BackHandler,
  Keyboard,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';

import { AccessSheet } from '../components/AccessSheet';
import { AppHeader, HeaderAction } from '../components/Chrome';
import { ChatBackground } from '../components/ChatBackground';
import { UpdateNotice } from '../components/UpdateCard';
import { Composer } from '../components/Composer';
import { useDock } from '../components/dock';
import { BackIcon, ChevronRightIcon, KeyIcon } from '../components/Icon';
import { MessageRow } from '../components/Message';
import { MotionPressable, MotionView, useReducedMotion } from '../components/Motion';
import { PastSearchRow, PastSearchesSheet, pastSearchText } from '../components/PastSearchesSheet';
import { Landing } from './Landing';
import { ScreenShareSheet } from '../components/ScreenShareSheet';
import { useOverlaySession } from '../components/OverlaySession';
import { ScreenshotSheet, type Shot } from '../components/ScreenshotSheet';
import { ScrollScrubber, type ScrubberHandle } from '../components/ScrollScrubber';
import { buildCatalog, type CatalogEntry } from '../engine/memory';
import { moveAppToBack } from '../engine/overlay';
import { AccessError, useStore } from '../engine/store';
import { keepThumbnail } from '../engine/thumbs';
import { tr } from '../i18n';
import type { AppAction, Message, Reading } from '../engine/types';
import { gap, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

/** A growing answer is followed to the bottom at most this often. */
const FOLLOW_EVERY_MS = 110;
/** Within this of the end counts as reading the end. */
const NEAR_END = 90;

interface Place {
  offset: number;
  viewport: number;
  content: number;
}

const nearEnd = (place: Place) => place.offset + place.viewport >= place.content - NEAR_END;

export function ChatScreen() {
  const overlay = useOverlaySession();
  const insets = useSafeAreaInsets();
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  useEffect(() => {
    const shown = Keyboard.addListener('keyboardDidShow', () => setKeyboardVisible(true));
    const hidden = Keyboard.addListener('keyboardDidHide', () => setKeyboardVisible(false));
    return () => { shown.remove(); hidden.remove(); };
  }, []);
  const {
    access,
    activeThread,
    canAsk,
    newChat,
    queueJobs,
    openScanResult,
    send,
    stop,
    streaming,
    threads,
    trialLeft,
    showDiagnostics,
  } = useStore();
  const list = useRef<FlatList<Message>>(null);
  const scrubber = useRef<ScrubberHandle>(null);
  const reduced = useReducedMotion();
  const dock = useDock();
  /**
   * Where the list is and who is moving it. Kept out of state: a scroll must
   * not re-render the conversation.
   */
  const flow = useRef({
    place: { offset: 0, viewport: 0, content: 0 } as Place,
    /** At the end, so a growing answer is followed; scrolling away lets go. */
    stick: true,
    /** A finger is moving the list, as opposed to the app following the answer. */
    touching: false,
    scrubbing: false,
    empty: true,
    glide: false,
    followedAt: 0,
    lift: null as ReturnType<typeof setTimeout> | null,
    follow: null as ReturnType<typeof setTimeout> | null,
  });

  const [draft, setDraft] = useState('');
  const [accessOpen, setAccessOpen] = useState(false);
  const [screenOpen, setScreenOpen] = useState(false);
  const [pastOpen, setPastOpen] = useState(false);
  /** A press on the scan button throws the dust out from where it was pressed. */
  const [burst, setBurst] = useState<{ key: number; x: number; y: number } | undefined>(undefined);
  const [shot, setShot] = useState<Shot | null>(null);
  const [picking, setPicking] = useState(false);
  const [notice, setNotice] = useState('');
  const color = useColors();
  const styles = useStyles();

  /** What the phone already remembers: one row per product, newest first. */
  const catalog = useMemo(() => buildCatalog(threads, queueJobs), [threads, queueJobs]);

  const messages = activeThread?.messages ?? [];
  const last = messages[messages.length - 1];
  const working = Boolean(last?.pending);
  const empty = messages.length === 0;
  const recentScans = queueJobs.filter(
    (job) => job.threadId && (job.status === 'done' || job.status === 'error'),
  );

  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(''), 6000);
    return () => clearTimeout(id);
  }, [notice]);

  useEffect(() => {
    flow.current.empty = empty;
    flow.current.glide = reduced === false;
  }, [empty, reduced]);

  useEffect(() => {
    flow.current.stick = true;
    requestAnimationFrame(() => {
      if (empty) list.current?.scrollToOffset({ offset: 0, animated: false });
      else list.current?.scrollToEnd({ animated: false });
    });
  }, [activeThread?.id, empty]);

  // A growing answer is followed to the bottom with a glide, a few times a
  // second, and only for a reader who is still at the end. Scrolling up lets go.
  const followEnd = useCallback(() => {
    const state = flow.current;
    if (!state.stick || state.scrubbing || state.empty) return;
    const wait = FOLLOW_EVERY_MS - (Date.now() - state.followedAt);
    if (wait > 0) {
      if (!state.follow) {
        state.follow = setTimeout(() => {
          state.follow = null;
          if (!state.stick || state.scrubbing) return;
          state.followedAt = Date.now();
          list.current?.scrollToEnd({ animated: state.glide });
        }, wait);
      }
      return;
    }
    state.followedAt = Date.now();
    list.current?.scrollToEnd({ animated: state.glide });
  }, []);

  useEffect(() => {
    if (working) followEnd();
  }, [working, last?.steps?.length, followEnd]);

  useEffect(() => {
    const state = flow.current;
    return () => {
      if (state.lift) clearTimeout(state.lift);
      if (state.follow) clearTimeout(state.follow);
    };
  }, []);

  /** The list moved: remember where, tell the rail, and let the bar decide. */
  const onScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { layoutMeasurement, contentOffset, contentSize } = event.nativeEvent;
    const state = flow.current;
    state.place = { offset: contentOffset.y, viewport: layoutMeasurement.height, content: contentSize.height };
    if (state.touching) state.stick = nearEnd(state.place);
    scrubber.current?.update(state.place, state.touching);
    // The rail's own scrolling is not the reader asking for room.
    if (!state.scrubbing) dock.report(state.place, state.touching);
  };

  const letGo = () => {
    const state = flow.current;
    if (state.lift) clearTimeout(state.lift);
    state.lift = null;
    state.touching = false;
    state.stick = nearEnd(state.place);
  };

  const touchBegan = () => {
    const state = flow.current;
    if (state.lift) clearTimeout(state.lift);
    state.lift = null;
    state.touching = true;
  };

  const openAccess = () => setAccessOpen(true);

  // A new chat is started from the bottom bar's plus button, which opens compose
  // mode. Whatever was half-written or staged for the last chat goes with it.
  const composing = dock.composing;
  const [wasComposing, setWasComposing] = useState(composing);
  if (composing !== wasComposing) {
    setWasComposing(composing);
    if (composing) {
      setDraft('');
      setShot(null);
    }
  }

  const ask = async (text: string, reading?: Reading, imageUri?: string) => {
    if (!canAsk) {
      openAccess();
      return;
    }
    // A new question is read where it lands, wherever the reader had scrolled to.
    flow.current.stick = true;
    try {
      await send(text, { reading, imageUri });
    } catch (error) {
      if (error instanceof AccessError) {
        openAccess();
        return;
      }
      setNotice(error instanceof Error ? error.message : 'The turn did not start.');
    }
  };

  const onSend = () => {
    const text = draft.trim();
    if (!text || streaming || working) return;
    setDraft('');
    void ask(text);
  };

  /** A remembered search fills the composer; it never sends itself. */
  const fillFromPast = (entry: CatalogEntry) => {
    setDraft(pastSearchText(entry));
  };

  const pick = async () => {
    if (picking || streaming) return;
    if (!canAsk) {
      openAccess();
      return;
    }
    setPicking(true);
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert(
          tr('Photo access is off'),
          tr('Kriko needs to see the screenshot you choose. Turn on Photos access in Android settings, then try again.'),
        );
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        quality: 1,
        base64: true,
      });
      if (result.canceled || !result.assets?.[0]) return;
      const asset = result.assets[0];
      let uri = asset.uri;
      let base64 = asset.base64 ?? '';
      let mime = asset.mimeType ?? 'image/jpeg';
      try {
        const rendered = await ImageManipulator.manipulateAsync(
          asset.uri,
          // Preserve fine model codes; never enlarge an already-small capture.
          asset.width > 1600 ? [{ resize: { width: 1600 } }] : [],
          {
            compress: 0.92,
            format: ImageManipulator.SaveFormat.JPEG,
            base64: true,
          },
        );
        if (rendered.base64) {
          base64 = rendered.base64;
          uri = rendered.uri;
          mime = 'image/jpeg';
        }
      } catch {
        // The picker's own base64 is still a usable image.
      }
      if (!base64) {
        Alert.alert(tr('That image could not be opened'), tr('Try another screenshot from Photos.'));
        return;
      }
      setShot({ uri, base64, mime });
    } catch {
      Alert.alert(tr('The photo picker did not open'), tr('Try again, or type the product instead.'));
    } finally {
      setPicking(false);
    }
  };

  const readScreen = () => {
    if (!canAsk) {
      openAccess();
      return;
    }
    // With the scanner already on, "Scan a product" means "take me to the page":
    // step aside so the K floats over it, instead of explaining the setup again.
    if (overlay.active) {
      void moveAppToBack();
      return;
    }
    setScreenOpen(true);
  };

  const onAskShot = (reading: Reading, question: string) => {
    const uri = shot?.uri;
    setShot(null);
    // The chat keeps a small copy in the app's own storage, not the picker's cache.
    void (async () => {
      const kept = uri ? await keepThumbnail(uri) : undefined;
      await ask(question, reading, kept ?? uri);
    })();
  };

  const goHome = useCallback(() => {
    Keyboard.dismiss();
    newChat();
    dock.endCompose();
  }, [newChat, dock]);
  useFocusEffect(useCallback(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (!empty || dock.composing) { goHome(); return true; }
      return false;
    });
    return () => subscription.remove();
  }, [empty, dock.composing, goHome]));
  const inChat = !empty || dock.composing;
  const exhausted = access.kind === 'trial' && trialLeft <= 0;
  /** A navigation the agent proposed. The phone performs it on the press. */
  const openAction = (action: AppAction) => {
    const screen = String(action.params?.screen || '');
    if (screen === 'settings') router.push('/settings' as Href);
    else if (screen === 'history') router.push('/history' as Href);
    else if (screen === 'about') router.push('/about' as Href);
    else if (screen === 'chat') router.push('/' as Href);
  };

  return (
    <View style={styles.page}>
      <ChatBackground lively={empty && !dock.composing} reading={working} burst={burst} />
      <AppHeader
        title={!empty ? activeThread?.title || 'Conversation' : dock.composing ? tr('New chat') : undefined}
        actions={
          <>
            {inChat ? <HeaderAction label="Home" onPress={goHome}><BackIcon size={20} color={color.ink} /></HeaderAction> : null}
          </>
        }
      />

      {empty ? <UpdateNotice onOpen={() => router.push('/settings' as Href)} /> : null}

      {overlay.active ? (
        <MotionView delay={80} style={styles.shareBanner}>
          <View style={styles.shareStatus}>
            <View style={styles.liveDot} />
            <View style={styles.shareCopy}>
              <Txt variant="monoSm" tone="ink" caps>{tr('Screen sharing is on')}</Txt>
              {/* The reassurance line is for the home screen; an open chat keeps its room. */}
              {empty ? <Txt variant="stepMeta" tone="ink3">{tr('Floating scanner ready · requested scans only')}</Txt> : null}
            </View>
          </View>
          <MotionPressable
            onPress={() => { void overlay.stop().catch((error) => setNotice(error instanceof Error ? error.message : tr('Could not stop screen sharing.'))); }}
            hitSlop={4}
            style={styles.stopShare}
            accessibilityRole="button"
            accessibilityLabel={tr('Stop screen sharing')}
          >
            <Txt variant="monoSm" tone="risk" caps>{tr('Stop')}</Txt>
          </MotionPressable>
        </MotionView>
      ) : null}

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <View style={styles.flex}>
          <FlatList
            ref={list}
            data={messages}
            keyExtractor={(message) => message.id}
            renderItem={({ item, index }) => (
              <MessageRow
                message={item}
                showDiagnostics={showDiagnostics}
                onCheckMerchant={streaming ? undefined : (source) => {
                  void ask(`Investigate the credibility of the merchant at ${source.host}, for this exact listing: ${source.url}. Verify its identity, independent complaints, consumer protection notices, returns and payment protections. Distinguish verified evidence from unproven claims.`);
                }}
                scanning={working && item.role === 'user' && index === messages.length - 2}
                onAction={openAction}
                onOpenSources={
                  activeThread ? () => router.push(`/sources/${activeThread.id}` as Href) : undefined
                }
              />
            )}
            ListEmptyComponent={dock.composing ? (
              <View style={{ paddingHorizontal: PAGE_X, paddingTop: 30 }}><Txt variant="rowTitle" tone="ink3">Ask a question</Txt></View>
            ) : (
              <Landing
                onScan={readScreen}
                onPick={() => { void pick(); }}
                recentScans={recentScans}
                onOpenScan={openScanResult}
                onBurst={(x, y) => setBurst({ key: Date.now(), x, y })}
              />
            )}
            contentContainerStyle={[styles.listBody, empty && styles.landingBody]}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
            showsVerticalScrollIndicator={false}
            scrollEventThrottle={16}
            onScroll={onScroll}
            onScrollBeginDrag={touchBegan}
            onScrollEndDrag={() => {
              // A lift with a fling goes straight into momentum; give it a moment.
              const state = flow.current;
              if (state.lift) clearTimeout(state.lift);
              state.lift = setTimeout(letGo, 250);
            }}
            onMomentumScrollBegin={touchBegan}
            onMomentumScrollEnd={letGo}
            onLayout={(event) => {
              const state = flow.current;
              state.place = { ...state.place, viewport: event.nativeEvent.layout.height };
              scrubber.current?.update(state.place, false);
              // The list changed size (the bar left, the keyboard came): not a scroll.
              dock.report(state.place, false);
            }}
            onContentSizeChange={(_width, height) => {
              const state = flow.current;
              state.place = { ...state.place, content: height };
              scrubber.current?.update(state.place, false);
              // A page that has become too short to scroll gets its bar back.
              dock.report(state.place, false);
              followEnd();
            }}
          />
          <ScrollScrubber
            ref={scrubber}
            onScrub={(offset) => list.current?.scrollToOffset({ offset, animated: false })}
            onScrubStart={() => {
              const state = flow.current;
              if (state.lift) clearTimeout(state.lift);
              state.lift = null;
              state.scrubbing = true;
              state.touching = true;
            }}
            onScrubEnd={() => {
              flow.current.scrubbing = false;
              letGo();
            }}
            onNudge={(direction) => {
              const { offset, viewport } = flow.current.place;
              list.current?.scrollToOffset({ offset: Math.max(0, offset + direction * viewport * 0.8), animated: true });
            }}
          />
        </View>

        <View style={[styles.footer, { paddingBottom: !keyboardVisible && access.kind === 'none' ? Math.max(insets.bottom, gap[3]) : gap[2] }]}>
          {notice ? (
            <Txt variant="monoSm" tone="warn" style={styles.notice}>
              {notice}
            </Txt>
          ) : null}
          {exhausted ? (
            <MotionPressable onPress={openAccess} style={styles.trialBanner} accessibilityRole="button" accessibilityLabel={tr('Trial complete. Add access to continue.')}>
              <KeyIcon size={17} color={color.ink3} />
              <Txt variant="bodyTight" tone="ink2" style={styles.trialText}>Trial complete</Txt>
              <Txt variant="bodyTight" tone="fill">Add access</Txt>
              <ChevronRightIcon size={15} color={color.ink3} />
            </MotionPressable>
          ) : null}
          {!empty && !streaming && catalog.length ? (
            <PastSearchRow
              entries={catalog.slice(0, 3)}
              onPick={fillFromPast}
              onSeeAll={() => setPastOpen(true)}
            />
          ) : null}
          <Composer
            autoFocus={empty && dock.composing}
            key={activeThread?.id ?? 'new-chat'}
            value={draft}
            onChangeText={setDraft}
            onSend={onSend}
            onStop={stop}
            onPick={pick}
            onScan={readScreen}
            streaming={streaming}
            placeholder={working ? 'Read the answer, or stop it…' : 'Ask about a product'}
          />
        </View>
      </KeyboardAvoidingView>

      {accessOpen ? <AccessSheet visible onClose={() => setAccessOpen(false)} /> : null}
      {pastOpen ? (
        <PastSearchesSheet
          visible
          entries={catalog}
          onClose={() => setPastOpen(false)}
          onPick={fillFromPast}
        />
      ) : null}
      {screenOpen ? (
        <ScreenShareSheet
          onClose={() => setScreenOpen(false)}
          onFallback={() => {
            setScreenOpen(false);
            void pick();
          }}
        />
      ) : null}
      {shot ? (
        <ScreenshotSheet
          key={shot.uri}
          shot={shot}
          onClose={() => setShot(null)}
          onAsk={onAskShot}
        />
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  page: { flex: 1, backgroundColor: color.ground },
  flex: { flex: 1 },
  shareBanner: {
    marginHorizontal: PAGE_X,
    marginBottom: gap[2],
    paddingHorizontal: gap[3],
    paddingVertical: gap[2],
    minHeight: 48,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.edgeStrong,
    backgroundColor: color.surface,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: gap[2],
  },
  shareStatus: { flexDirection: 'row', alignItems: 'center', gap: gap[2], flex: 1 },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: color.ok },
  shareCopy: { flex: 1, gap: 2 },
  stopShare: {
    minHeight: 36,
    paddingHorizontal: gap[3],
    backgroundColor: color.riskWash,
    borderRadius: radius.s,
    alignItems: 'center',
    justifyContent: 'center',
  },
  landingBody: { paddingHorizontal: 0 },
  listBody: { paddingHorizontal: PAGE_X, paddingBottom: gap[4], flexGrow: 1 },
  footer: {
    paddingHorizontal: gap[3],
    paddingTop: gap[3],
    backgroundColor: 'transparent',
    gap: gap[2],
  },
  notice: { paddingHorizontal: gap[1] },
  trialBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: gap[2],
    minHeight: 44,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.edge,
    borderRadius: radius.m,
    paddingHorizontal: gap[3],
    paddingVertical: gap[2],
  },
  // The message gives way (it wraps) so the call to action is never pushed off the edge.
  trialText: { flex: 1 },
  trialAction: { flexShrink: 0 },
}));
