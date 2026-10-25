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
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { motion } from '../theme/motion';
import { PAGE_X, radius } from '../theme/tokens';
import { makeStyles } from '../theme/theme';
import { tr } from '../i18n';
import { useReducedMotion } from './Motion';

type AnimatedSheetProps = {
  visible: boolean;
  onClose: () => void;
  children: ReactNode | ((dismiss: () => void) => ReactNode);
  style?: StyleProp<ViewStyle>;
};

/** Native bottom sheet with interruptible transitions, back and scrim dismissal. */
export function AnimatedSheet({ visible, onClose, children, style }: AnimatedSheetProps) {
  const insets = useSafeAreaInsets();
  const reduced = useReducedMotion();
  const [mounted, setMounted] = useState(visible);
  const [closing, setClosing] = useState(false);
  const [previousVisible, setPreviousVisible] = useState(visible);
  const [scrimProgress] = useState(() => new Animated.Value(0));
  const [panelY] = useState(() => new Animated.Value(38));
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
      panelY.setValue(targetOpen ? 0 : 38);
      scrimProgress.setValue(targetOpen ? 1 : 0);
      if (targetOpen) return;
      const frame = requestAnimationFrame(complete);
      return () => cancelAnimationFrame(frame);
    }
    const animation = Animated.parallel([
      targetOpen
        ? Animated.spring(panelY, { toValue: 0, ...motion.spring.smooth })
        : Animated.timing(panelY, {
            toValue: 38, duration: motion.duration.exit,
            easing: Easing.bezier(...motion.easing.exit), useNativeDriver: true,
          }),
      Animated.timing(scrimProgress, {
        toValue: targetOpen ? 1 : 0,
        duration: targetOpen ? motion.duration.standard : motion.duration.exit,
        easing: targetOpen ? Easing.bezier(...motion.easing.enter) : Easing.bezier(...motion.easing.exit),
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
        <Animated.View
          pointerEvents="none"
          style={[styles.scrim, { opacity: scrimProgress.interpolate({ inputRange: [0, 1], outputRange: [0, 0.58] }) }]}
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
