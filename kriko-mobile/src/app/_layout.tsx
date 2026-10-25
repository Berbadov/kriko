/**
 * The root layout: load the faces, mount the store, then the runtime theme.
 *
 * Fonts are loaded at runtime rather than embedded, so the app runs in Expo Go
 * without a development build. The splash holds until they are in.
 */

import { Geist_400Regular } from '@expo-google-fonts/geist/400Regular';
import { Geist_500Medium } from '@expo-google-fonts/geist/500Medium';
import { Geist_600SemiBold } from '@expo-google-fonts/geist/600SemiBold';
import { Geist_700Bold } from '@expo-google-fonts/geist/700Bold';
import { GeistMono_400Regular } from '@expo-google-fonts/geist-mono/400Regular';
import { GeistMono_500Medium } from '@expo-google-fonts/geist-mono/500Medium';
import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { StoreProvider, useStore } from '../engine/store';
import { OverlaySessionProvider } from '../components/OverlaySession';
import { MotionProvider, useReducedMotion } from '../components/Motion';
import { BottomNav } from '../components/Chrome';
import { ThemeProvider, useTheme } from '../theme/theme';

SplashScreen.preventAutoHideAsync().catch(() => {});

export default function RootLayout() {
  const [loaded, error] = useFonts({
    'Geist-Regular': Geist_400Regular,
    'Geist-Medium': Geist_500Medium,
    'Geist-SemiBold': Geist_600SemiBold,
    'Geist-Bold': Geist_700Bold,
    'GeistMono-Regular': GeistMono_400Regular,
    'GeistMono-Medium': GeistMono_500Medium,
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
  return (
    <View style={[styles.root, { backgroundColor: color.ground }]}>
      <StatusBar style={dark ? 'light' : 'dark'} />
      <View style={styles.stack}>
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: color.ground },
            animation: reduced === false ? 'fade_from_bottom' : 'none',
          }}
        >
          <Stack.Screen name="index" />
          <Stack.Screen name="assist" />
          <Stack.Screen name="history" />
          <Stack.Screen name="queue" />
          <Stack.Screen name="sources/[id]" />
          <Stack.Screen name="settings" />
          <Stack.Screen name="about" />
        </Stack>
      </View>
      {access.kind === 'none' ? null : <BottomNav />}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  stack: { flex: 1 },
});
