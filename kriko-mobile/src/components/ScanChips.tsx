/**
 * Recent screen reads as a row of chips above the composer: tap one to jump
 * back to its result. Each carries the glyph of the kind of product it was.
 */

import { ScrollView, StyleSheet } from 'react-native';

import type { QueueJob } from '../engine/types';
import { tr } from '../i18n';
import { radius } from '../theme/tokens';
import { makeStyles } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { ago, scanTitle } from './HistoryLists';
import { MotionPressable } from './Motion';
import { ProductTile, readingIcon } from './ProductIcon';

export function ScanChips({ jobs, activeThreadId, onOpen }: {
  jobs: QueueJob[];
  activeThreadId?: string;
  onOpen: (id: string) => void;
}) {
  const styles = useStyles();
  if (!jobs.length) return null;
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.row}
      style={styles.scroll}
    >
      {jobs.map((job) => {
        const active = job.threadId === activeThreadId;
        return (
          <MotionPressable
            key={job.id}
            onPress={() => onOpen(job.id)}
            accessibilityRole="button"
            accessibilityLabel={tr(`Open scan result for ${scanTitle(job)}`)}
            style={[styles.chip, active && styles.chipOn]}
          >
            <ProductTile icon={readingIcon(job.reading)} size={30} active={active} />
            <Txt variant="actionSmall" tone="ink" numberOfLines={1} style={styles.title}>{scanTitle(job)}</Txt>
            <Txt variant="monoSm" tone="ink3" numberOfLines={1}>{ago(job.updatedAt)}</Txt>
          </MotionPressable>
        );
      })}
    </ScrollView>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  scroll: { flexGrow: 0, marginHorizontal: -10 },
  row: { paddingHorizontal: 10, gap: 8 },
  chip: {
    height: 44,
    maxWidth: 270,
    paddingLeft: 7,
    paddingRight: 14,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: color.edgeStrong,
    backgroundColor: color.glass,
  },
  chipOn: { borderColor: color.accent },
  title: { flexShrink: 1, maxWidth: 140 },
}));
