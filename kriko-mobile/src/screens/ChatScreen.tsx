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
import {
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type RefObject,
} from 'react';
import { Alert, Animated, FlatList, StyleSheet, View } from 'react-native';

import { AccessSheet } from '../components/AccessSheet';
import { Frame, HeaderAction, useFrameInsets } from '../components/Chrome';
import { Glass } from '../components/Glass';
import { HistoryDrawer, settleDrawer } from '../components/HistoryDrawer';
import { ScanChips } from '../components/ScanChips';
import { useDrawerSwipe } from '../components/useDrawerSwipe';
import { Composer } from '../components/Composer';
import { PlusIcon } from '../components/Icon';
import { MessageRow } from '../components/Message';
import { MotionPressable, MotionView, useReducedMotion } from '../components/Motion';
import { Landing } from './Landing';
import { ScreenShareSheet } from '../components/ScreenShareSheet';
import { useOverlaySession } from '../components/OverlaySession';
import { ScreenshotSheet, type Shot } from '../components/ScreenshotSheet';
import { moveAppToBack } from '../engine/overlay';
import { AccessError, useStore } from '../engine/store';
import { tr } from '../i18n';
import type { AppAction, Message, Reading } from '../engine/types';
import { gap, PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

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
  const atBottom = useRef(true);

  const [draft, setDraft] = useState('');
  const [accessOpen, setAccessOpen] = useState(false);
  const [screenOpen, setScreenOpen] = useState(false);
  const [shot, setShot] = useState<Shot | null>(null);
  const [picking, setPicking] = useState(false);
  const [notice, setNotice] = useState('');
  const color = useColors();
  const styles = useStyles();
  const reduced = useReducedMotion();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [progress] = useState(() => new Animated.Value(0));

  const messages = activeThread?.messages ?? [];
  const last = messages[messages.length - 1];
  const working = Boolean(last?.pending);
  const empty = messages.length === 0;

  const chipJobs = queueJobs.filter((job) => job.threadId).slice(-8).reverse();

  const setDrawer = (open: boolean) => {
    setDrawerOpen(open);
    settleDrawer(progress, open, reduced);
  };

  const { swipe, claimTouch, resetTouch } = useDrawerSwipe(progress, setDrawer);

  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(''), 6000);
    return () => clearTimeout(id);
  }, [notice]);

  useEffect(() => {
    atBottom.current = true;
    requestAnimationFrame(() => {
      if (empty) list.current?.scrollToOffset({ offset: 0, animated: false });
      else list.current?.scrollToEnd({ animated: false });
    });
  }, [activeThread?.id, empty]);

  useEffect(() => {
    if (working && atBottom.current) {
      requestAnimationFrame(() => list.current?.scrollToEnd({ animated: false }));
    }
  }, [working, last?.text, last?.steps?.length]);

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
    void ask(question, reading, uri);
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

  const banner = overlay.active ? (
    <MotionView delay={80}>
      <Glass radius={radius.xl} style={styles.shareBanner}>
        <View style={styles.shareStatus}>
          <View style={styles.liveDot} />
          <View style={styles.shareCopy}>
            <Txt variant="monoSm" tone="ink" caps>{tr('Screen sharing is on')}</Txt>
            <Txt variant="stepMeta" tone="ink3">{tr('Floating scanner ready · requested scans only')}</Txt>
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
      </Glass>
    </MotionView>
  ) : null;

  const floating = (
    <>
      <View onTouchStart={claimTouch}>
        <ScanChips jobs={chipJobs} activeThreadId={activeThread?.id} onOpen={openScanResult} />
      </View>
      {notice ? (
        <Txt variant="monoSm" tone="warn" style={styles.notice}>
          {notice}
        </Txt>
      ) : null}
      {exhausted ? (
        <MotionPressable onPress={openAccess} style={styles.trialBanner} accessibilityRole="button">
          <Txt variant="body" tone="ink2">
            The free questions on this phone are used up.
          </Txt>
          <Txt variant="monoSm" tone="fill" caps>
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
    </>
  );

  return (
    <View style={styles.flex} onTouchStartCapture={resetTouch} {...swipe.panHandlers}>
      <Frame
        title={empty ? undefined : activeThread?.title || 'Conversation'}
        actions={
          !empty ? (
            <HeaderAction label="New chat" onPress={startNewChat}>
              <PlusIcon size={20} color={color.ink} />
            </HeaderAction>
          ) : null
        }
        banner={banner}
        floating={floating}
        overlay={(
          <HistoryDrawer
            progress={progress}
            open={drawerOpen}
            onClose={() => setDrawerOpen(false)}
            onNewChat={() => { startNewChat(); setDrawer(false); }}
          />
        )}
      >
        <Thread
          list={list}
          isAtBottom={() => atBottom.current}
          setAtBottom={(value) => { atBottom.current = value; }}
          messages={messages}
          empty={empty}
          openAction={openAction}
          threadId={activeThread?.id}
          landing={(
            <Landing
              onSuggestion={ask}
              onScan={readScreen}
              onPick={() => { void pick(); }}
            />
          )}
        />
      </Frame>

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

/** The scrolling conversation, padded to run under the floating bars. */
function Thread({ list, isAtBottom, setAtBottom, messages, empty, openAction, threadId, landing }: {
  list: RefObject<FlatList<Message> | null>;
  isAtBottom: () => boolean;
  setAtBottom: (value: boolean) => void;
  messages: Message[];
  empty: boolean;
  openAction: (action: AppAction) => void;
  threadId?: string;
  landing: ReactElement;
}) {
  const styles = useStyles();
  const { top, bottom } = useFrameInsets();
  return (
    <FlatList
      ref={list}
      data={messages}
      keyExtractor={(message) => message.id}
      renderItem={({ item }) => (
        <MessageRow
          message={item}
          onAction={openAction}
          onOpenSources={threadId ? () => router.push(`/sources/${threadId}` as Href) : undefined}
        />
      )}
      ListEmptyComponent={landing}
      contentContainerStyle={[
        styles.listBody,
        empty && styles.landingBody,
        { paddingTop: top + 6, paddingBottom: bottom + gap[3] },
      ]}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="interactive"
      showsVerticalScrollIndicator={false}
      scrollEventThrottle={16}
      onScroll={(event) => {
        const { layoutMeasurement, contentOffset, contentSize } = event.nativeEvent;
        setAtBottom(contentOffset.y + layoutMeasurement.height >= contentSize.height - 90);
      }}
      onContentSizeChange={() => {
        if (!empty && isAtBottom()) list.current?.scrollToEnd({ animated: false });
      }}
    />
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  flex: { flex: 1 },
  shareBanner: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: gap[2],
  },
  shareStatus: { flexDirection: 'row', alignItems: 'center', gap: 9, flex: 1 },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: color.ok },
  shareCopy: { flex: 1, gap: 2 },
  stopShare: { paddingHorizontal: 13, paddingVertical: 8, backgroundColor: color.riskWash, borderRadius: radius.pill },
  landingBody: { paddingHorizontal: 0 },
  listBody: { paddingHorizontal: PAGE_X, flexGrow: 1 },
  notice: { paddingHorizontal: 8 },
  trialBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: gap[2],
    backgroundColor: color.riskWash,
    borderRadius: radius.xl,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
}));
