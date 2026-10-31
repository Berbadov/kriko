/**
 * The in-app update, as the reader meets it: a card in Settings that says what
 * is installed, whether something newer is on GitHub, and carries them through
 * download and install; and a slim notice on the home screen when a new version
 * is waiting. What each state means is decided in `engine/updatecore.ts`.
 */

import { StyleSheet, View } from 'react-native';

import { formatSize } from '../engine/appupdate';
import type { UpdateFailure, UpdateSnapshot } from '../engine/updatecore';
import { updater, updatesSupported, useAppUpdate } from '../engine/updater';
import { tr } from '../i18n';
import { gap, PAGE_X } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';
import { DownloadIcon, XIcon } from './Icon';
import { ActivityDots, MotionPressable } from './Motion';
import { Button, ProgressBar } from './Primitives';

const FAILURES: Record<UpdateFailure, string> = {
  offline: 'Could not reach GitHub. Check your connection and try again.',
  rate: 'GitHub is limiting requests for now. Try again in a few minutes.',
  server: 'GitHub answered with something Kriko could not read.',
  checksum: 'The download did not match its checksum, so Kriko threw it away. Try again.',
  size: 'The download stopped early. Try again.',
  storage: 'There is not enough room on this phone for the update.',
  signature: 'This build was signed with a different key, so Android will not let it replace this app.',
  blocked: 'Android blocked the install. Allow Kriko to install apps, then try again.',
  older: 'That download is older than the version on this phone.',
  invalid: 'That download is not a Kriko update.',
  missing: 'The download is gone. Try again.',
  failed: 'The update did not install. Try again.',
};

export function UpdateCard() {
  const snapshot = useAppUpdate();
  const color = useColors();
  const styles = useStyles();
  if (!updatesSupported()) return null;
  const { state, installed } = snapshot;

  const title = state.phase === 'available' || state.phase === 'downloading' || state.phase === 'permission' || state.phase === 'installing'
    ? `Kriko ${state.update.version} is ready`
    : state.phase === 'error' && state.update ? `Kriko ${state.update.version} is ready`
      : installed ? `Kriko Agent ${installed}` : 'Kriko Agent';

  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <View style={styles.mark}><DownloadIcon size={19} color={color.accent} /></View>
        <View style={styles.headText}>
          <Txt variant="rowTitle" tone="ink" translate={false}>{tr(title)}</Txt>
          <Txt variant="bodyTight" tone="ink3">{summary(snapshot)}</Txt>
        </View>
      </View>

      {state.phase === 'available' || (state.phase === 'error' && state.update) ? (
        <Notes lines={(state.phase === 'available' || state.phase === 'error') && state.update ? state.update.notes : []} />
      ) : null}

      {state.phase === 'downloading' ? (
        <View style={styles.progress}>
          <ProgressBar value={state.total > 0 ? state.received / state.total : 0} />
          <View style={styles.progressRow}>
            <Txt variant="monoSm" tone="ink3" translate={false}>
              {`${formatSize(state.received)} / ${formatSize(state.total)}`}
            </Txt>
            <MotionPressable onPress={() => updater.cancel()} accessibilityRole="button" accessibilityLabel={tr('Cancel')} style={styles.textAction}>
              <Txt variant="actionSmall" tone="ink2">Cancel</Txt>
            </MotionPressable>
          </View>
        </View>
      ) : null}

      {state.phase === 'checking' || (state.phase === 'installing' && !state.confirming) ? (
        <View style={styles.working}><ActivityDots color={color.accent} /></View>
      ) : null}

      {actions(snapshot, styles)}
    </View>
  );
}

function summary(snapshot: UpdateSnapshot): string {
  const { state } = snapshot;
  switch (state.phase) {
    case 'checking': return tr('Looking for a newer version…');
    case 'available': return tr(`${formatSize(state.update.bytes)} · from GitHub, checked on this phone`);
    case 'downloading': return tr('Downloading. Keep Kriko open.');
    case 'permission': return tr('Android asks once. Turn on “Allow from this source”, then come back here.');
    case 'installing': return state.confirming
      ? tr('Confirm on the screen Android shows. Kriko restarts when it is done.')
      : tr('Handing it to Android…');
    case 'error': return tr(FAILURES[state.reason]);
    case 'current': return tr('You have the newest version.');
    default: return tr('Updates come from Kriko’s releases on GitHub. Nothing installs without your press.');
  }
}

function actions(snapshot: UpdateSnapshot, styles: ReturnType<typeof useStyles>) {
  const { state } = snapshot;
  switch (state.phase) {
    case 'available':
      return <Button label="Update now" onPress={() => { void updater.start(); }} />;
    case 'permission':
      return <Button label="Open the setting" onPress={() => { void updater.start(); }} />;
    case 'error':
      return state.update
        ? <Button label="Try again" onPress={() => { void updater.start(); }} />
        : <Button label="Check again" variant="ghost" onPress={() => { void updater.check(true); }} />;
    case 'idle':
    case 'current':
      return <Button label="Check for updates" variant="ghost" onPress={() => { void updater.check(true); }} />;
    default:
      return <View style={styles.none} />;
  }
}

function Notes({ lines }: { lines: string[] }) {
  const styles = useStyles();
  if (!lines.length) return null;
  return (
    <View style={styles.notes}>
      {lines.slice(0, 4).map((line, index) => (
        <View key={index} style={styles.noteRow}>
          <View style={styles.noteDot} />
          <Txt variant="bodyTight" tone="ink2" translate={false} style={styles.noteText}>{line}</Txt>
        </View>
      ))}
    </View>
  );
}

/**
 * One slim line on the home screen while a new version waits: where to go, and
 * a way to send it away for this version. It never downloads by itself.
 */
export function UpdateNotice({ onOpen }: { onOpen: () => void }) {
  const snapshot = useAppUpdate();
  const color = useColors();
  const styles = useStyles();
  const { state, dismissed } = snapshot;
  if (!updatesSupported() || state.phase !== 'available' || dismissed === state.update.version) return null;
  const version = state.update.version;
  return (
    <View style={styles.notice}>
      <MotionPressable
        onPress={onOpen}
        accessibilityRole="button"
        accessibilityLabel={tr(`Open the update to ${version}`)}
        style={styles.noticeMain}
      >
        <View style={styles.noticeDot} />
        <Txt variant="rowText" tone="ink" translate={false} style={styles.noticeText} numberOfLines={1}>
          {tr(`Kriko ${version} is ready`)}
        </Txt>
        <Txt variant="monoSm" tone="accent" caps>Update</Txt>
      </MotionPressable>
      <MotionPressable
        onPress={() => { void updater.dismiss(version); }}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel={tr('Not now')}
        style={styles.noticeClose}
      >
        <XIcon size={16} color={color.ink3} />
      </MotionPressable>
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  card: { gap: gap[3] },
  head: { flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  mark: { width: 40, height: 40, borderRadius: 20, backgroundColor: color.accentSoft, alignItems: 'center', justifyContent: 'center' },
  headText: { flex: 1, gap: 3 },
  notes: { gap: 6, paddingLeft: 2 },
  noteRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 9 },
  noteDot: { width: 4, height: 4, borderRadius: 2, backgroundColor: color.ink3, marginTop: 9 },
  noteText: { flex: 1 },
  progress: { gap: 8 },
  progressRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  textAction: { minHeight: 36, justifyContent: 'center', paddingHorizontal: 4 },
  working: { minHeight: 24, justifyContent: 'center' },
  none: { height: 0 },
  notice: {
    marginHorizontal: PAGE_X,
    marginBottom: 6,
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: color.edge,
    backgroundColor: color.accentWash,
  },
  noticeMain: { flex: 1, minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 10, paddingLeft: 14 },
  noticeDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: color.accent },
  noticeText: { flex: 1 },
  noticeClose: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
}));
