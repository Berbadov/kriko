import { StyleSheet } from 'react-native';

import { Hero, Page } from '../components/Chrome';
import { MotionView } from '../components/Motion';
import { QueueList } from '../components/QueueSheet';
import { useStore } from '../engine/store';
import { gap, PAGE_X } from '../theme/tokens';
import { makeStyles } from '../theme/theme';
import { Txt } from '../theme/Txt';

export default function Queue() {
  const { queueJobs, cancelQueue } = useStore();
  const styles = useStyles();
  const active = queueJobs.filter((job) => job.status === 'queued' || job.status === 'running').length;

  return (
    <Page artHeight={0}>
      <Hero
        crumb="kriko / your scans"
        title="Queue"
        subtitle={active ? `${active} ${active === 1 ? 'product is' : 'products are'} being researched.` : 'Each product and its sources, together.'}
      />
      {queueJobs.length ? (
        <MotionView delay={60} style={styles.count}>
          <Txt variant="monoSm" tone="ink3" caps>{`${queueJobs.length} saved scan${queueJobs.length === 1 ? '' : 's'}`}</Txt>
        </MotionView>
      ) : null}
      <MotionView delay={90} style={styles.list}>
        <QueueList jobs={queueJobs} onCancel={cancelQueue} />
      </MotionView>
    </Page>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  count: { paddingHorizontal: PAGE_X, marginTop: -gap[2], marginBottom: gap[1] },
  list: { paddingHorizontal: PAGE_X, paddingBottom: 32 },
}));
