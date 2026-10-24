/**
 * Entry: a stored conversation, or the one door that opens the agent.
 *
 * The store hydrates keys from secure storage and chats from AsyncStorage
 * before this decides, so the screen does not flash the welcome door at
 * somebody who has already walked through it.
 */

import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { useStore } from '../engine/store';
import { ChatScreen } from '../screens/ChatScreen';
import { WelcomeScreen } from '../screens/WelcomeScreen';
import { color } from '../theme/tokens';
import { Logo } from '../components/Logo';

export default function Index() {
  const { hydrated, access } = useStore();

  if (!hydrated) {
    return (
      <View style={styles.splash}>
        <Logo />
        <ActivityIndicator color={color.ink3} />
      </View>
    );
  }

  if (access.kind === 'none') return <WelcomeScreen />;
  return <ChatScreen />;
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    backgroundColor: color.ground,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 20,
  },
});
