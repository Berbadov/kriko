/**
 * The in-app update, end to end with the phone replaced by a script: a look at
 * GitHub, the reader's press, the download, the one-time "allow installing"
 * trip, the installer's answers, and each way any of it can go wrong. The reader
 * must always be able to try again, and nothing may start without their press.
 */

import assert from 'node:assert/strict';

import { DEFAULT_ASSET_PREFIX, type AppUpdate } from '../src/engine/appupdate';
import {
  createUpdater,
  failureFrom,
  updateNeedsAttention,
  UpdateError,
  type UpdateDeps,
  type UpdateMemory,
} from '../src/engine/updatecore';

const HASH = 'c'.repeat(64);
const NOW = 1_800_000_000_000;

function releaseList(version: string, extra: Record<string, unknown> = {}): unknown[] {
  const tag = `mobile-v${version}`;
  return [{
    tag_name: tag, draft: false, prerelease: false, body: '- Faster',
    html_url: `https://github.com/Berbadov/kriko/releases/tag/${tag}`,
    assets: [{
      name: `kriko-agent-${version}.apk`, size: 1000, state: 'uploaded',
      browser_download_url: `${DEFAULT_ASSET_PREFIX}${tag}/kriko-agent-${version}.apk`,
      ...extra,
    }],
  }];
}

type Script = {
  installed?: string | null;
  releases?: unknown | (() => Promise<unknown>);
  canInstall?: boolean[];
  download?: (update: AppUpdate, sha: string) => Promise<void>;
  install?: (version: string) => Promise<void>;
  text?: (url: string) => Promise<string>;
  memory?: UpdateMemory;
};

function rig(script: Script = {}) {
  const calls: string[] = [];
  const saved: UpdateMemory[] = [];
  const progress = new Set<(p: { received: number; total: number }) => void>();
  const install = new Set<(e: { state: string; message: string }) => void>();
  const permissions = [...(script.canInstall ?? [true])];
  let clock = NOW;
  const deps: UpdateDeps = {
    releases: async () => {
      calls.push('releases');
      const value = script.releases ?? releaseList('0.13.0', { digest: `sha256:${HASH}` });
      return typeof value === 'function' ? (value as () => Promise<unknown>)() : value;
    },
    text: script.text ?? (async () => { throw new UpdateError('offline'); }),
    installed: async () => (script.installed === undefined ? '0.12.1' : script.installed),
    canInstall: async () => { calls.push('canInstall'); return permissions.length > 1 ? permissions.shift()! : permissions[0]; },
    openInstallSettings: async () => { calls.push('openSettings'); return true; },
    download: async (update, sha) => { calls.push(`download:${update.version}:${sha}`); await script.download?.(update, sha); },
    cancelDownload: () => { calls.push('cancel'); },
    install: async (version) => { calls.push(`install:${version}`); await script.install?.(version); },
    onProgress: (cb) => { progress.add(cb); return () => { progress.delete(cb); }; },
    onInstall: (cb) => { install.add(cb); return () => { install.delete(cb); }; },
    load: async () => script.memory ?? { checkedAt: 0, dismissed: '' },
    save: async (memory) => { saved.push(memory); },
    now: () => clock,
  };
  const updater = createUpdater(deps);
  return {
    updater, calls, saved,
    emitProgress: (received: number, total: number) => progress.forEach((cb) => cb({ received, total })),
    emitInstall: (state: string, message = '') => install.forEach((cb) => cb({ state, message })),
    tick: (ms: number) => { clock += ms; },
    phase: () => updater.getSnapshot().state.phase,
  };
}

async function aLookFindsTheNewerBuildAndRemembersWhenItLooked(): Promise<void> {
  const t = rig();
  await t.updater.check(true);
  const snap = t.updater.getSnapshot();
  assert.equal(snap.installed, '0.12.1');
  assert.equal(snap.state.phase, 'available');
  assert.equal(snap.state.phase === 'available' && snap.state.update.version, '0.13.0');
  assert.equal(t.saved.at(-1)?.checkedAt, NOW);
  assert.equal(t.saved.at(-1)?.dismissed, '');
  assert.ok(!t.calls.some((call) => call.startsWith('download')), 'nothing downloads without a press');
}

async function nothingNewerIsSaidPlainly(): Promise<void> {
  const t = rig({ releases: releaseList('0.12.1') });
  await t.updater.check(true);
  assert.equal(t.phase(), 'current');
}

async function aFailedManualLookSaysWhyAndAnAutomaticOneStaysQuiet(): Promise<void> {
  const failing = async () => { throw new UpdateError('rate'); };
  const manual = rig({ releases: failing });
  await manual.updater.check(true);
  const state = manual.updater.getSnapshot().state;
  assert.equal(state.phase, 'error');
  assert.equal(state.phase === 'error' && state.reason, 'rate');
  assert.equal(state.phase === 'error' && state.step, 'check');
  assert.equal(manual.saved.length, 0, 'a failed look is not remembered as a look');

  const quiet = rig({ releases: failing });
  await quiet.updater.autoCheck();
  assert.equal(quiet.phase(), 'idle');
}

async function anAutomaticLookHappensOnlyWhenOneIsDue(): Promise<void> {
  const recent = rig({ memory: { checkedAt: NOW - 60_000, dismissed: '' } });
  await recent.updater.autoCheck();
  assert.ok(!recent.calls.includes('releases'), 'looked again a minute after the last look');
  assert.equal(recent.updater.getSnapshot().installed, '0.12.1', 'the screen still learns what is installed');
  assert.equal(recent.phase(), 'idle');

  const stale = rig({ memory: { checkedAt: NOW - 13 * 60 * 60 * 1000, dismissed: '' } });
  await stale.updater.autoCheck();
  assert.equal(stale.phase(), 'available');
}

async function aBuildWithoutAnInstallerOffersNothing(): Promise<void> {
  const t = rig({ installed: null });
  await t.updater.check(true);
  assert.equal(t.phase(), 'idle');
  assert.ok(!t.calls.includes('releases'));
}

async function twoLooksAtOnceAreOne(): Promise<void> {
  const t = rig();
  await Promise.all([t.updater.check(true), t.updater.check(true)]);
  assert.equal(t.calls.filter((call) => call === 'releases').length, 1);
}

async function thePressDownloadsThenInstallsAndTheSystemConfirms(): Promise<void> {
  let release: () => void = () => undefined;
  const t = rig({
    download: () => new Promise<void>((resolve) => { release = resolve; }),
    install: async () => undefined,
  });
  await t.updater.check(true);
  const run = t.updater.start();
  await Promise.resolve();
  assert.equal(t.phase(), 'downloading');
  t.emitProgress(250, 1000);
  const mid = t.updater.getSnapshot().state;
  assert.equal(mid.phase === 'downloading' && mid.received, 250);
  release();
  await run;
  assert.equal(t.phase(), 'installing');
  assert.deepEqual(t.calls.filter((call) => /^(download|install)/.test(call)), [`download:0.13.0:${HASH}`, 'install:0.13.0']);
  t.emitInstall('confirm');
  const state = t.updater.getSnapshot().state;
  assert.equal(state.phase === 'installing' && state.confirming, true);
  t.emitInstall('installed');
  assert.equal(t.phase(), 'current');
}

async function theFirstTimeTheReaderIsSentToAllowInstalling(): Promise<void> {
  const t = rig({ canInstall: [false, true] });
  await t.updater.check(true);
  await t.updater.start();
  assert.equal(t.phase(), 'permission');
  assert.ok(t.calls.includes('openSettings'));
  assert.ok(!t.calls.some((call) => call.startsWith('install')), 'no install before the phone allows it');
  // Back from the phone's page, with the permission now on: it carries on by itself.
  await t.updater.resume();
  assert.equal(t.phase(), 'installing');
  assert.ok(t.calls.includes('install:0.13.0'));
}

async function comingBackWithoutAllowingChangesNothing(): Promise<void> {
  const t = rig({ canInstall: [false] });
  await t.updater.check(true);
  await t.updater.start();
  await t.updater.resume();
  assert.equal(t.phase(), 'permission');
  assert.equal(t.calls.filter((call) => call === 'openSettings').length, 1, 'the settings page is not reopened on its own');
}

async function theChecksumFileIsUsedWhenGithubStatesNoDigest(): Promise<void> {
  const t = rig({
    releases: [{
      ...(releaseList('0.13.0')[0] as object),
      assets: [
        { name: 'kriko-agent-0.13.0.apk', size: 1000, browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk` },
        { name: 'kriko-agent-0.13.0.apk.sha256', size: 90, browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk.sha256` },
      ],
    }],
    text: async () => `${HASH.toUpperCase()}  kriko-agent-0.13.0.apk\n`,
  });
  await t.updater.check(true);
  await t.updater.start();
  assert.ok(t.calls.includes(`download:0.13.0:${HASH}`));
}

async function anUnreadableChecksumFileDoesNotStopTheUpdate(): Promise<void> {
  const t = rig({
    releases: [{
      ...(releaseList('0.13.0')[0] as object),
      assets: [
        { name: 'kriko-agent-0.13.0.apk', size: 1000, browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk` },
        { name: 'kriko-agent-0.13.0.apk.sha256', size: 90, browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk.sha256` },
      ],
    }],
  });
  await t.updater.check(true);
  await t.updater.start();
  assert.ok(t.calls.includes('download:0.13.0:'), 'goes on without a checksum; the installer still checks the signing key');
}

async function everyDownloadFailureLeavesATryAgain(): Promise<void> {
  for (const [code, reason] of [['network', 'offline'], ['checksum', 'checksum'], ['size', 'size'], ['storage', 'storage'], ['weird', 'failed']] as const) {
    let fail = true;
    const t = rig({ download: async () => { if (fail) throw Object.assign(new Error('x'), { code }); } });
    await t.updater.check(true);
    await t.updater.start();
    const state = t.updater.getSnapshot().state;
    assert.equal(state.phase, 'error', code);
    assert.equal(state.phase === 'error' && state.reason, reason, code);
    assert.equal(state.phase === 'error' && state.step, 'download', code);
    assert.equal(state.phase === 'error' && state.update?.version, '0.13.0', 'the update is kept for the retry');
    fail = false;
    await t.updater.start();
    assert.equal(t.phase(), 'installing', `${code}: pressing again works`);
  }
}

async function cancellingADownloadGoesBackToAvailable(): Promise<void> {
  const t = rig({ download: async () => { throw Object.assign(new Error('x'), { code: 'cancelled' }); } });
  await t.updater.check(true);
  await t.updater.start();
  assert.equal(t.phase(), 'available');
  t.updater.cancel();
  assert.ok(!t.calls.includes('cancel'), 'cancel only acts on a running download');
}

async function aBuildSignedWithAnotherKeyIsSaidPlainly(): Promise<void> {
  const t = rig({ install: async () => { throw Object.assign(new Error('x'), { code: 'signature' }); } });
  await t.updater.check(true);
  await t.updater.start();
  const state = t.updater.getSnapshot().state;
  assert.equal(state.phase === 'error' && state.reason, 'signature');
  assert.equal(state.phase === 'error' && state.step, 'install');
}

async function theReaderDecliningTheSystemScreenGoesBackToAvailable(): Promise<void> {
  const t = rig();
  await t.updater.check(true);
  await t.updater.start();
  t.emitInstall('cancelled');
  assert.equal(t.phase(), 'available');
  await t.updater.start();
  assert.equal(t.phase(), 'installing', 'and the next press goes again');
}

async function theInstallersOwnFailuresAreWords(): Promise<void> {
  for (const [state, reason] of [['blocked', 'blocked'], ['storage', 'storage'], ['signature', 'signature'], ['failed', 'failed']] as const) {
    const t = rig();
    await t.updater.check(true);
    await t.updater.start();
    t.emitInstall(state, 'INSTALL_FAILED_something');
    const now = t.updater.getSnapshot().state;
    assert.equal(now.phase === 'error' && now.reason, reason, state);
  }
}

async function aLateInstallerMessageWhenNothingIsInstallingIsIgnored(): Promise<void> {
  const t = rig();
  t.emitInstall('installed');
  assert.equal(t.phase(), 'idle');
  await t.updater.check(true);
  t.emitInstall('failed');
  assert.equal(t.phase(), 'available');
}

async function sendingTheBannerAwayIsRemembered(): Promise<void> {
  const t = rig();
  await t.updater.check(true);
  await t.updater.dismiss('0.13.0');
  assert.equal(t.updater.getSnapshot().dismissed, '0.13.0');
  assert.equal(t.saved.at(-1)?.dismissed, '0.13.0');
  assert.equal(t.updater.getSnapshot().state.phase, 'available', 'dismissing hides a banner, not the update');
  const next = rig({ memory: { checkedAt: 0, dismissed: '0.13.0' } });
  await next.updater.autoCheck();
  assert.equal(next.updater.getSnapshot().dismissed, '0.13.0', 'and it survives a restart');
}

async function aWaitingUpdateSurvivesARestartWithoutAnotherLook(): Promise<void> {
  const first = rig();
  await first.updater.check(true);
  const kept = first.saved.at(-1);
  assert.ok(kept?.found, 'the update found is kept with the time of the look');

  // The app is opened again a few minutes later: no look is due, yet the update is still offered.
  const second = rig({ memory: { ...kept!, checkedAt: NOW - 5 * 60_000 } });
  await second.updater.autoCheck();
  assert.ok(!second.calls.includes('releases'));
  const state = second.updater.getSnapshot().state;
  assert.equal(state.phase === 'available' && state.update.version, '0.13.0');

  // Once it is installed (or a newer one is), the kept note offers nothing.
  const installedSince = rig({ installed: '0.13.0', memory: { ...kept!, checkedAt: NOW - 5 * 60_000 } });
  await installedSince.updater.autoCheck();
  assert.equal(installedSince.phase(), 'idle');

  // A look that finds nothing clears what was kept.
  const none = rig({ releases: releaseList('0.12.1') });
  await none.updater.check(true);
  assert.equal(none.saved.at(-1)?.found, null);
}

async function theReaderIsOnlyPulledInWhenThereIsSomethingToDo(): Promise<void> {
  const t = rig();
  assert.equal(updateNeedsAttention(t.updater.getSnapshot()), false, 'nothing yet');
  await t.updater.check(true);
  assert.equal(updateNeedsAttention(t.updater.getSnapshot()), true, 'a new version');
  const none = rig({ releases: releaseList('0.12.1') });
  await none.updater.check(true);
  assert.equal(updateNeedsAttention(none.updater.getSnapshot()), false, 'already current');
  const failed = rig({ releases: async () => { throw new UpdateError('offline'); } });
  await failed.updater.check(true);
  assert.equal(updateNeedsAttention(failed.updater.getSnapshot()), false, 'a failed look has nothing to act on');
  const stuck = rig({ install: async () => { throw Object.assign(new Error('x'), { code: 'storage' }); } });
  await stuck.updater.check(true);
  await stuck.updater.start();
  assert.equal(updateNeedsAttention(stuck.updater.getSnapshot()), true, 'a failed install can be retried');
}

function failureWordsAreStable(): void {
  assert.equal(failureFrom(new UpdateError('rate')), 'rate');
  assert.equal(failureFrom({ code: 'network' }), 'offline');
  assert.equal(failureFrom({ code: 'cancelled' }), 'cancelled');
  assert.equal(failureFrom({ code: 'permission' }), 'permission');
  assert.equal(failureFrom({ code: 'nonsense' }), 'failed');
  assert.equal(failureFrom(null), 'failed');
  assert.equal(failureFrom('text'), 'failed');
}

async function main(): Promise<void> {
  await aLookFindsTheNewerBuildAndRemembersWhenItLooked();
  await nothingNewerIsSaidPlainly();
  await aFailedManualLookSaysWhyAndAnAutomaticOneStaysQuiet();
  await anAutomaticLookHappensOnlyWhenOneIsDue();
  await aBuildWithoutAnInstallerOffersNothing();
  await twoLooksAtOnceAreOne();
  await thePressDownloadsThenInstallsAndTheSystemConfirms();
  await theFirstTimeTheReaderIsSentToAllowInstalling();
  await comingBackWithoutAllowingChangesNothing();
  await theChecksumFileIsUsedWhenGithubStatesNoDigest();
  await anUnreadableChecksumFileDoesNotStopTheUpdate();
  await everyDownloadFailureLeavesATryAgain();
  await cancellingADownloadGoesBackToAvailable();
  await aBuildSignedWithAnotherKeyIsSaidPlainly();
  await theReaderDecliningTheSystemScreenGoesBackToAvailable();
  await theInstallersOwnFailuresAreWords();
  await aLateInstallerMessageWhenNothingIsInstallingIsIgnored();
  await sendingTheBannerAwayIsRemembered();
  await aWaitingUpdateSurvivesARestartWithoutAnotherLook();
  await theReaderIsOnlyPulledInWhenThereIsSomethingToDo();
  failureWordsAreStable();
  process.stdout.write('Update flow checks passed.\n');
}

main().catch((error) => { console.error(error); process.exit(1); });
