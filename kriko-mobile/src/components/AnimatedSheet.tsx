import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Animated,
  Easing,
  KeyboardAvoidingView,
  Modal,
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
import { useReducedMotion } from './Motion';
import { useReducedTransparency } from './Glass';

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

/**
 * Native bottom sheet with interruptible transitions, back and scrim dismissal.
 *
 * Reversing mid-flight is the point: a drag, a back press or a state change
 * stops the current animation and springs from wherever the panel is, so the
 * sheet never snaps or restarts from the bottom. Reduced motion mounts and
 * unmounts instantly.
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
  const { dark } = useTheme();
  const [mounted, setMounted] = useState(visible);
  const [closing, setClosing] = useState(false);
  const [previousVisible, setPreviousVisible] = useState(visible);
  const [scrimProgress] = useState(() => new Animated.Value(0));
  const [panelY] = useState(() => new Animated.Value(PANEL_TRAVEL));
  const closeCallback = useRef(onClose);
  useEffect(() => { closeCallback.current = onClose; }, [onClose]);

  // Synchronize controlled reopen before committing a frame. Keeping presence
  // separate from visibility lets the closing sheet finish its own animation.
  if (visible !== previousVisible) {
    setPreviousVisible(visible);
    if (visible) { setMounted(true); setClosing(false); }
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
      panelY.setValue(targetOpen ? 0 : PANEL_TRAVEL);
      scrimProgress.setValue(targetOpen ? 1 : 0);
      if (targetOpen) return;
      const frame = requestAnimationFrame(complete);
      return () => cancelAnimationFrame(frame);
    }
    const animation = Animated.parallel([
      targetOpen
        ? Animated.spring(panelY, { toValue: 0, ...motion.spring.sheet })
        : Animated.timing(panelY, {
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
  }, [closing, mounted, panelY, reduced, scrimProgress, targetOpen]);

  const styles = useStyles();

  if (!mounted) return null;
  const content = typeof children === 'function' ? children(dismiss) : children;
  // A veil only earns its cost when the platform actually blurs; otherwise the
  // scrim alone carries the dimming.
  const veiled = blurBackdrop && reduced === false && !reducedTransparency;
  const scrimTop = veiled ? SCRIM_OPACITY_VEILED : SCRIM_OPACITY;

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
          style={[styles.scrim, { opacity: scrimProgress.interpolate({ inputRange: [0, 1], outputRange: [0, scrimTop] }) }]}
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
            { paddingBottom: Math.max(insets.bottom, 14), opacity: scrimProgress, transform: [{ translateY: panelY }] },
            style,
          ]}
        >
          <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={styles.grabArea}>
            <View style={styles.grab} />
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
  grabArea: { height: 20, alignItems: 'center', justifyContent: 'flex-start' },
  grab: { width: 36, height: 4, borderRadius: 2, backgroundColor: color.edgeStrong },
}));
