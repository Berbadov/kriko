/**
 * A warm paper conversation view, with the scanner and queue always close by.
 *
 * The agent's work is visible while it happens — searches, pages read — and the
 * answer arrives under it with its sources. A screenshot or the phone's own
 * screen enters through the same composer.
 */

import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import { router, type Href } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
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
import { Composer } from '../components/Composer';
import { useDock } from '../components/dock';
import { PlusIcon } from '../components/Icon';
import { MessageRow } from '../components/Message';
import { MotionPressable, MotionView, useReducedMotion } from '../components/Motion';
import { Landing } from './Landing';
import { ScreenShareSheet } from '../components/ScreenShareSheet';
import { useOverlaySession } from '../components/OverlaySession';
import { ScreenshotSheet, type Shot } from '../components/ScreenshotSheet';
import { ScrollScrubber, type ScrubberHandle } from '../components/ScrollScrubber';
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
    trialLeft,
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
  const [shot, setShot] = useState<Shot | null>(null);
  const [picking, setPicking] = useState(false);
  const [notice, setNotice] = useState('');
  const color = useColors();
  const styles = useStyles();

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

  const startNewChat = () => {
    if (streaming) {
      Alert.alert(tr('Kriko is still working'), tr('Stop the answer first, then start a new chat.'));
      return;
    }
    newChat();
    setDraft('');
    setShot(null);
  };

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
      <AppHeader
        title={!empty ? activeThread?.title || 'Conversation' : undefined}
        actions={
          !empty ? (
            <HeaderAction label="New chat" onPress={startNewChat}>
              <PlusIcon size={20} color={color.ink} />
            </HeaderAction>
          ) : null
        }
      />

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
                scanning={working && item.role === 'user' && index === messages.length - 2}
                onAction={openAction}
                onOpenSources={
                  activeThread ? () => router.push(`/sources/${activeThread.id}` as Href) : undefined
                }
              />
            )}
            ListEmptyComponent={(
              <Landing
                onScan={readScreen}
                onPick={() => { void pick(); }}
                recentScans={recentScans}
                onOpenScan={openScanResult}
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

        <View style={styles.footer}>
          {notice ? (
            <Txt variant="monoSm" tone="warn" style={styles.notice}>
              {notice}
            </Txt>
          ) : null}
          {exhausted ? (
            <MotionPressable onPress={openAccess} style={styles.trialBanner} accessibilityRole="button">
              <Txt variant="body" tone="ink2" style={styles.trialText}>
                The free questions on this phone are used up.
              </Txt>
              <Txt variant="monoSm" tone="fill" caps style={styles.trialAction}>
                Paste an access code
              </Txt>
            </MotionPressable>
          ) : null}
          <Composer
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
    marginBottom: 4,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.m,
    borderWidth: 1,
    borderColor: color.edgeStrong,
    backgroundColor: color.surface,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: gap[2],
  },
  shareStatus: { flexDirection: 'row', alignItems: 'center', gap: 9, flex: 1 },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: color.ok },
  shareCopy: { flex: 1, gap: 2 },
  stopShare: { paddingHorizontal: 11, paddingVertical: 5, backgroundColor: color.riskWash, borderRadius: radius.s },
  landingBody: { paddingHorizontal: 0 },
  listBody: { paddingHorizontal: PAGE_X, paddingBottom: gap[4], flexGrow: 1 },
  footer: {
    paddingHorizontal: PAGE_X - 8,
    paddingTop: 4,
    backgroundColor: 'transparent',
    gap: 6,
  },
  notice: { paddingHorizontal: 4 },
  trialBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: gap[2],
    backgroundColor: color.riskWash,
    borderWidth: 1,
    borderColor: color.riskWash,
    borderRadius: radius.m,
    paddingHorizontal: 11,
    paddingVertical: 8,
  },
  // The message gives way (it wraps) so the call to action is never pushed off the edge.
  trialText: { flex: 1 },
  trialAction: { flexShrink: 0 },
}));
