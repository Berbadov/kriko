/**
 * The root layout: load the faces, mount the store, then the runtime theme.
 *
 * Fonts are loaded at runtime rather than embedded, so the app runs in Expo Go
 * without a development build. The splash holds until they are in.
 */

import { AtkinsonHyperlegible_400Regular } from '@expo-google-fonts/atkinson-hyperlegible/400Regular';
import { AtkinsonHyperlegible_700Bold } from '@expo-google-fonts/atkinson-hyperlegible/700Bold';
import { AtkinsonHyperlegibleMono_400Regular } from '@expo-google-fonts/atkinson-hyperlegible-mono/400Regular';
import { AtkinsonHyperlegibleMono_500Medium } from '@expo-google-fonts/atkinson-hyperlegible-mono/500Medium';
import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { StoreProvider, useStore } from '../engine/store';
import { useUpdateLifecycle } from '../engine/updater';
import { OverlaySessionProvider } from '../components/OverlaySession';
import { MotionProvider, useReducedMotion } from '../components/Motion';
import { BottomNav } from '../components/Chrome';
import { DockProvider } from '../components/dock';
import { motion } from '../theme/motion';
import { ThemeProvider, useTheme } from '../theme/theme';

SplashScreen.preventAutoHideAsync().catch(() => {});

export default function RootLayout() {
  const [loaded, error] = useFonts({
    'Atkinson-Regular': AtkinsonHyperlegible_400Regular,
    'Atkinson-Bold': AtkinsonHyperlegible_700Bold,
    'AtkinsonMono-Regular': AtkinsonHyperlegibleMono_400Regular,
    'AtkinsonMono-Medium': AtkinsonHyperlegibleMono_500Medium,
    'KrikoDisplay-Bold': require('../../assets/fonts/KrikoDisplay-Bold.ttf'),
    'KrikoDisplay-SemiBold': require('../../assets/fonts/KrikoDisplay-SemiBold.ttf'),
  });

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync().catch(() => {});
  }, [loaded, error]);

  if (!loaded && !error) return null;

  return (
    <SafeAreaProvider>
      <StoreProvider>
        <ThemedApp />
      </StoreProvider>
    </SafeAreaProvider>
  );
}

function ThemedApp() {
  const { appearance, textSize, motion } = useStore();
  return (
    <ThemeProvider appearance={appearance} textSize={textSize}>
      <MotionProvider preference={motion}>
        <OverlaySessionProvider>
          <AppStack />
        </OverlaySessionProvider>
      </MotionProvider>
    </ThemeProvider>
  );
}

function AppStack() {
  const reduced = useReducedMotion();
  const { dark, color } = useTheme();
  const { access } = useStore();
  useUpdateLifecycle();
  return (
    <DockProvider>
      <View style={[styles.root, { backgroundColor: color.ground }]}>
        <StatusBar style={dark ? 'light' : 'dark'} />
        <View style={styles.stack}>
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: color.ground },
              // One native transition per push: the stack fades the screen in on
              // top of the page, so no screen draws a second arrival of its own.
              // Reduced motion removes it entirely. `animationDuration` is iOS
              // only; Android uses the platform's own short fade.
              animation: reduced === false ? 'fade' : 'none',
              animationDuration: motion.duration.screen,
            }}
          >
            <Stack.Screen name="index" />
            <Stack.Screen name="assist" />
            <Stack.Screen name="history" />
            <Stack.Screen name="shortlist" />
            <Stack.Screen name="queue" />
            <Stack.Screen name="sources/[id]" />
            <Stack.Screen name="settings" />
            <Stack.Screen name="about" />
          </Stack>
        </View>
        {access.kind === 'none' ? null : <BottomNav />}
      </View>
    </DockProvider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  stack: { flex: 1 },
});
