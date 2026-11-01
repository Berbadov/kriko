import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Animated,
  Easing,
  KeyboardAvoidingView,
  Modal,
  PanResponder,
  Platform,
  Pressable,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { BlurView } from 'expo-blur';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { motion } from '../theme/motion';
import { PAGE_X, radius } from '../theme/tokens';
import { makeStyles, useTheme } from '../theme/theme';
import { tr } from '../i18n';
import { Txt } from '../theme/Txt';
import { useReducedMotion } from './Motion';
import { useReducedTransparency } from './Glass';
import { ChevronRightIcon } from './Icon';

type AnimatedSheetProps = {
  visible: boolean;
  onClose: () => void;
  children: ReactNode | ((dismiss: () => void) => ReactNode);
  style?: StyleProp<ViewStyle>;
  /** Veil the page behind the sheet (default). A still scrim when it cannot. */
  blurBackdrop?: boolean;
};

/** How far the panel travels as it arrives; it springs the rest of the way. */
const PANEL_TRAVEL = 44;

/** Darkest the scrim goes; a little lighter when the blur veil also dims. */
const SCRIM_OPACITY = 0.58;
const SCRIM_OPACITY_VEILED = 0.44;

/** Drag distance past which a release closes the sheet. */
const CLOSE_DISTANCE = 96;
/** Downward velocity (points per ms) that closes regardless of distance. */
const CLOSE_VELOCITY = 1.1;
/** How far a drag-close carries the panel; it also fades out on the scrim. */
const PANEL_EXIT = 560;
/** How far the scrim lightens across the drag. */
const SCRIM_DRAG_FADE = 260;

/**
 * Native bottom sheet with interruptible transitions, back and scrim dismissal,
 * and a swipe-down close.
 *
 * Reversing mid-flight is the point: a drag, a back press or a state change
 * stops the current animation and springs from wherever the panel is, so the
 * sheet never snaps or restarts from the bottom. Reduced motion mounts and
 * unmounts instantly, and the drag becomes a still handle.
 *
 * The close indicator is the strip at the top: a grabber, a small chevron-down
 * and "Swipe down to close". It is the drag handle, so a vertical scroll inside
 * the sheet keeps its gesture; pulling the handle down moves the panel with the
 * finger and lightens the scrim, and letting go past 96 points (or with
 * downward velocity) closes it. Otherwise it springs back.
 *
 * The handle claims the touch on DOWN (`onStartShouldSetPanResponder`, plus the
 * capture phase). It has no press action of its own — the X and the scrim are
 * separate — so claiming at once is what makes the gesture reliable: a handle
 * that only claims on move can miss the gesture entirely, and then no move ever
 * reaches the panel.
 *
 * The backdrop: a sheet rendered in an RN `Modal` lives in a window of its own,
 * so a `BlurView` there cannot sample the app underneath (Android's
 * `BlurTargetView` cannot cross windows, iOS blur is window-local). The veil is
 * therefore the platform's own blur layer over the transparent stage — a real
 * frost on iOS, the SDK's tinted fallback on Android — plus a lighter scrim, so
 * the page behind still reads as dimmed and out of focus.
 */
export function AnimatedSheet({ visible, onClose, children, style, blurBackdrop = true }: AnimatedSheetProps) {
  const insets = useSafeAreaInsets();
  const reduced = useReducedMotion();
  const reducedTransparency = useReducedTransparency();
  const { color, dark } = useTheme();
  const [mounted, setMounted] = useState(visible);
  const [closing, setClosing] = useState(false);
  const [previousVisible, setPreviousVisible] = useState(visible);
  const [scrimProgress] = useState(() => new Animated.Value(0));
  /**
   * The panel's own offset. 0 is fully open, PANEL_TRAVEL is the arrival's rest
   * offset, PANEL_EXIT is where a drag-close carries it. One value for one
   * transform: the finger and the arrival animation never share a node, so the
   * panel moves from a single source instead of a JS/native sum.
   */
  const [sheetY] = useState(() => new Animated.Value(PANEL_TRAVEL));
  /** How far the finger has pulled, for the hint fade and the scrim only. */
  const [dragY] = useState(() => new Animated.Value(0));
  const closeCallback = useRef(onClose);
  useEffect(() => { closeCallback.current = onClose; }, [onClose]);

  // Synchronize controlled reopen before committing a frame. Keeping presence
  // separate from visibility lets the closing sheet finish its own animation.
  if (visible !== previousVisible) {
    setPreviousVisible(visible);
    if (visible) {
      setMounted(true);
      setClosing(false);
      // A sheet closed by a drag leaves the panel far down; a reopen starts flat.
      sheetY.setValue(PANEL_TRAVEL);
      dragY.setValue(0);
    }
  }
  const dismiss = useCallback(() => setClosing(true), []);
  const targetOpen = visible && !closing;

  useEffect(() => {
    if (!mounted) return;
    const complete = () => {
      if (targetOpen) return;
      setMounted(false);
      if (closing) closeCallback.current();
    };
    if (reduced !== false) {
      sheetY.setValue(targetOpen ? 0 : PANEL_TRAVEL);
      scrimProgress.setValue(targetOpen ? 1 : 0);
      if (targetOpen) return;
      const frame = requestAnimationFrame(complete);
      return () => cancelAnimationFrame(frame);
    }
    const animation = Animated.parallel([
      targetOpen
        ? Animated.spring(sheetY, { toValue: 0, ...motion.spring.sheet })
        : Animated.timing(sheetY, {
            toValue: PANEL_TRAVEL, duration: motion.duration.sheet,
            easing: Easing.bezier(...motion.easing.exit), useNativeDriver: true,
          }),
      Animated.timing(scrimProgress, {
        toValue: targetOpen ? 1 : 0,
        duration: motion.duration.sheet,
        easing: targetOpen
          ? Easing.bezier(...motion.easing.enter)
          : Easing.bezier(...motion.easing.exit),
        useNativeDriver: true,
      }),
    ]);
    animation.start(({ finished }) => { if (finished) complete(); });
    // Stop only this effect's composite, never a newly requested animation.
    return () => animation.stop();
  }, [closing, mounted, reduced, scrimProgress, sheetY, targetOpen]);

  /** Let go short of the threshold: the panel returns to rest. */
  const springBack = useCallback(() => {
    sheetY.stopAnimation();
    dragY.stopAnimation();
    if (reduced !== false) {
      sheetY.setValue(0);
      dragY.setValue(0);
      return;
    }
    Animated.parallel([
      Animated.spring(sheetY, { toValue: 0, ...motion.spring.sheet }),
      Animated.spring(dragY, { toValue: 0, ...motion.spring.sheet }),
    ]).start();
  }, [dragY, reduced, sheetY]);

  /**
   * Let go past the threshold: the panel leaves from where the finger left it
   * and the scrim fades with it, then the sheet closes through its normal path.
   */
  const closeByDrag = useCallback(() => {
    sheetY.stopAnimation();
    if (reduced !== false) {
      setClosing(true);
      return;
    }
    Animated.parallel([
      Animated.timing(sheetY, {
        toValue: PANEL_EXIT,
        duration: motion.duration.exit,
        easing: Easing.bezier(...motion.easing.exit),
        useNativeDriver: true,
      }),
      Animated.timing(scrimProgress, {
        toValue: 0,
        duration: motion.duration.exit,
        easing: Easing.bezier(...motion.easing.exit),
        useNativeDriver: true,
      }),
    ]).start(({ finished }) => { if (finished) setClosing(true); });
  }, [reduced, scrimProgress, sheetY]);

  const pan = useMemo(
    () =>
      PanResponder.create({
        // The handle has no tap action, so it takes the touch at once; the
        // capture phase makes it win before any child could look at the touch.
        onStartShouldSetPanResponder: () => true,
        onStartShouldSetPanResponderCapture: () => true,
        onMoveShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponderCapture: () => true,
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: () => {
          sheetY.stopAnimation();
          dragY.stopAnimation();
        },
        onPanResponderMove: (_event, gesture) => {
          // Downward pull only; upward belongs to the sheet's own content.
          const pull = gesture.dy > 0 ? gesture.dy : 0;
          sheetY.setValue(pull);
          dragY.setValue(pull);
        },
        onPanResponderRelease: (_event, gesture) => {
          if (gesture.dy > CLOSE_DISTANCE || gesture.vy > CLOSE_VELOCITY) closeByDrag();
          else springBack();
        },
        onPanResponderTerminate: () => springBack(),
      }),
    [closeByDrag, dragY, sheetY, springBack],
  );

  const hintOpacity = useMemo(
    () => dragY.interpolate({ inputRange: [0, 56], outputRange: [1, 0], extrapolate: 'clamp' }),
    [dragY],
  );
  // A veil only earns its cost when the platform actually blurs; otherwise the
  // scrim alone carries the dimming.
  const veiled = blurBackdrop && reduced === false && !reducedTransparency;
  const scrimTop = veiled ? SCRIM_OPACITY_VEILED : SCRIM_OPACITY;
  // The page behind comes back as the panel is pulled away.
  const scrimOpacity = useMemo(
    () =>
      Animated.multiply(
        scrimProgress,
        dragY.interpolate({
          inputRange: [0, SCRIM_DRAG_FADE],
          outputRange: [scrimTop, scrimTop * 0.18],
          extrapolate: 'clamp',
        }),
      ),
    [dragY, scrimProgress, scrimTop],
  );

  const styles = useStyles();

  if (!mounted) return null;
  const content = typeof children === 'function' ? children(dismiss) : children;

  return (
    <Modal
      visible={mounted}
      transparent
      animationType="none"
      statusBarTranslucent
      onRequestClose={dismiss}
    >
      <KeyboardAvoidingView
        style={styles.stage}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        {veiled ? (
          <Animated.View
            pointerEvents="none"
            style={[StyleSheet.absoluteFill, { opacity: scrimProgress }]}
          >
            <BlurView
              intensity={24}
              tint={dark ? 'dark' : 'light'}
              style={StyleSheet.absoluteFill}
            />
          </Animated.View>
        ) : null}
        <Animated.View
          pointerEvents="none"
          style={[styles.scrim, { opacity: scrimOpacity }]}
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={tr('Close sheet')}
          style={StyleSheet.absoluteFill}
          onPress={dismiss}
        />
        <Animated.View
          accessibilityViewIsModal
          style={[
            styles.panel,
            {
              paddingBottom: Math.max(insets.bottom, 14),
              opacity: scrimProgress,
              transform: [{ translateY: sheetY }],
            },
            style,
          ]}
        >
          {/* A plain View, not an Animated one: the handlers live on the view
              that takes the touch, and nothing in this strip animates. */}
          <View
            {...pan.panHandlers}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            style={styles.dragArea}
          >
            <View style={styles.grab} />
            <View style={styles.hintRow}>
              <View style={styles.chevron}>
                <ChevronRightIcon size={13} color={color.ink4} />
              </View>
              <Animated.View style={{ opacity: hintOpacity }}>
                <Txt variant="monoSm" tone="ink4">Swipe down to close</Txt>
              </Animated.View>
            </View>
          </View>
          {content}
        </Animated.View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  stage: { flex: 1, justifyContent: 'flex-end' },
  scrim: { ...StyleSheet.absoluteFill, backgroundColor: color.scrim },
  panel: {
    width: '100%',
    maxHeight: '92%',
    paddingHorizontal: PAGE_X,
    paddingTop: 8,
    backgroundColor: color.surface,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    borderTopWidth: 1,
    borderColor: color.edge,
    shadowColor: color.shadow,
    shadowOpacity: 0.18,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: -8 },
    elevation: 18,
  },
  /* The close indicator doubles as the drag handle: 44 points of thumb room,
     full panel width, the panel's first child so nothing covers it. */
  dragArea: {
    minHeight: 44,
    alignSelf: 'stretch',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
    paddingBottom: 2,
  },
  grab: { width: 36, height: 4, borderRadius: 2, backgroundColor: color.edgeStrong },
  hintRow: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  /* The same chevron the app uses, turned to point at the bottom edge. */
  chevron: { transform: [{ rotate: '90deg' }] },
}));
