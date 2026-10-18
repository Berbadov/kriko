/**
 * Entry: send the user to setup until the reader is installed on this phone.
 */

import { Redirect } from 'expo-router';
import { View } from 'react-native';

import { useStore } from '../engine/store';
import { color } from '../theme/tokens';

export default function Index() {
  const { hydrated, readerReady } = useStore();
  if (!hydrated) return <View style={{ flex: 1, backgroundColor: color.ground }} />;
  return <Redirect href={readerReady ? '/chat' : '/setup'} />;
}
