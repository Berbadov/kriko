import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { HeaderAction, Hero, Page } from '../components/Chrome';
import { HistoryLists } from '../components/HistoryLists';
import { BackIcon, PlusIcon } from '../components/Icon';
import { MotionView } from '../components/Motion';
import { Button } from '../components/Primitives';
import { useStore } from '../engine/store';
import { PAGE_X, gap } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';

export default function History() {
  const { newChat } = useStore();
  const color = useColors();
  const styles = useStyles();

  const start = () => { newChat(); router.replace('/'); };

  return (
    <Page artHeight={0} actions={<HeaderAction label="Back" onPress={() => router.back()}><BackIcon size={21} color={color.ink} /></HeaderAction>}>
      <Hero crumb="kriko / your shelf" title="History" subtitle="Chats and screen reads, kept apart." />
      <View style={styles.body}>
        <MotionView delay={0} style={styles.start}>
          <Button label="New conversation" icon={<PlusIcon size={17} color={color.onAccent} />} onPress={start} />
        </MotionView>
        <HistoryLists onOpen={() => router.replace('/')} />
      </View>
    </Page>
  );
}

const useStyles = makeStyles(() => StyleSheet.create({
  body: { paddingHorizontal: PAGE_X, gap: gap[4] },
  start: { alignSelf: 'flex-start' },
}));
