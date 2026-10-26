/**
 * Which GitHub release the phone offers as an update. The list is untrusted
 * text, so every rejection matters as much as the one acceptance: a desktop
 * release, a draft, a pre-release, a file from another place, an odd size.
 */

import assert from 'node:assert/strict';

import {
  CHECK_EVERY_MS,
  checkIsDue,
  compareVersions,
  DEFAULT_ASSET_PREFIX,
  parseChecksum,
  parseVersion,
  pickUpdate,
  releaseNotes,
  restoreUpdate,
} from '../src/engine/appupdate';

const HASH = 'a'.repeat(63) + 'B';

function release(version: string, extra: Record<string, unknown> = {}, assets?: Record<string, unknown>[]) {
  const tag = `mobile-v${version}`;
  return {
    tag_name: tag,
    draft: false,
    prerelease: false,
    published_at: '2026-10-26T10:00:00Z',
    html_url: `https://github.com/Berbadov/kriko/releases/tag/${tag}`,
    body: '## What is new\n- The chat has more room.\n- **Updates** arrive in the app.',
    assets: assets ?? [{
      name: `kriko-agent-${version}.apk`,
      size: 60_000_000,
      state: 'uploaded',
      digest: `sha256:${HASH}`,
      browser_download_url: `${DEFAULT_ASSET_PREFIX}${tag}/kriko-agent-${version}.apk`,
    }],
    ...extra,
  };
}

function versionsCompareByNumberNotByText(): void {
  assert.equal(compareVersions('0.12.10', '0.12.9'), 1);
  assert.equal(compareVersions('0.12.1', '0.12.1'), 0);
  assert.equal(compareVersions('0.9.9', '0.12.0'), -1);
  assert.equal(compareVersions('1.0.0', '0.99.99'), 1);
  assert.deepEqual(parseVersion('v0.12.1'), [0, 12, 1]);
  assert.equal(parseVersion('0.12'), null);
  assert.equal(parseVersion('0.12.1-beta'), null);
  // A version that does not parse is never newer than anything.
  assert.equal(compareVersions('latest', '0.0.1'), -1);
}

function theNewestMobileReleaseIsOffered(): void {
  const offered = pickUpdate([release('0.12.2'), release('0.13.0'), release('0.12.9')], '0.12.1');
  assert.ok(offered);
  assert.equal(offered.version, '0.13.0');
  assert.equal(offered.tag, 'mobile-v0.13.0');
  assert.equal(offered.apkUrl, `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk`);
  assert.equal(offered.bytes, 60_000_000);
  assert.equal(offered.sha256, HASH.toLowerCase(), 'the digest is kept lowercase');
  assert.deepEqual(offered.notes, ['The chat has more room.', 'Updates arrive in the app.'], 'a heading is not one of the lines');
  assert.equal(offered.pageUrl, 'https://github.com/Berbadov/kriko/releases/tag/mobile-v0.13.0');
}

function nothingNewerMeansNoOffer(): void {
  assert.equal(pickUpdate([release('0.12.1')], '0.12.1'), null);
  assert.equal(pickUpdate([release('0.12.0')], '0.12.1'), null);
  assert.equal(pickUpdate([], '0.12.1'), null);
}

function theDesktopAppsReleasesAreNotOurs(): void {
  const desktop = release('0.3.7', { tag_name: 'v0.3.7' });
  assert.equal(pickUpdate([desktop], '0.1.0'), null);
  assert.equal(pickUpdate([release('0.13.0', { tag_name: 'mobile-0.13.0' })], '0.12.1'), null);
  assert.equal(pickUpdate([release('0.13.0', { tag_name: 'mobile-v0.13.0-rc1' })], '0.12.1'), null);
}

function draftsAndPreReleasesAreNeverOffered(): void {
  assert.equal(pickUpdate([release('0.13.0', { draft: true })], '0.12.1'), null);
  assert.equal(pickUpdate([release('0.13.0', { prerelease: true })], '0.12.1'), null);
  // A lower, finished release is still not an update, and a higher draft does not hide it.
  const offered = pickUpdate([release('0.13.0', { draft: true }), release('0.12.2')], '0.12.1');
  assert.equal(offered?.version, '0.12.2');
}

function theFileMustBeTheOneTheTagNames(): void {
  const wrongName = release('0.13.0', {}, [{
    name: 'kriko-agent-0.12.2.apk', size: 1000,
    browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.12.2.apk`,
  }]);
  assert.equal(pickUpdate([wrongName], '0.12.1'), null);
  assert.equal(pickUpdate([release('0.13.0', {}, [])], '0.12.1'), null);
  assert.equal(pickUpdate([release('0.13.0', { assets: 'nope' })], '0.12.1'), null);
}

function theFileMustComeFromTheReleasesOfThisRepository(): void {
  const elsewhere = release('0.13.0', {}, [{
    name: 'kriko-agent-0.13.0.apk', size: 1000,
    browser_download_url: 'https://example.com/releases/download/mobile-v0.13.0/kriko-agent-0.13.0.apk',
  }]);
  assert.equal(pickUpdate([elsewhere], '0.12.1'), null);
  const plain = release('0.13.0', {}, [{
    name: 'kriko-agent-0.13.0.apk', size: 1000,
    browser_download_url: DEFAULT_ASSET_PREFIX.replace('https', 'http') + 'mobile-v0.13.0/kriko-agent-0.13.0.apk',
  }]);
  assert.equal(pickUpdate([plain], '0.12.1'), null, 'an unencrypted address is not trusted');
  // A feed of the maker's own (a test) names its own prefix.
  const local = release('0.13.0', {}, [{
    name: 'kriko-agent-0.13.0.apk', size: 1000,
    browser_download_url: 'http://127.0.0.1:8099/kriko-agent-0.13.0.apk',
  }]);
  assert.equal(pickUpdate([local], '0.12.1', { assetPrefix: 'http://127.0.0.1:8099/' })?.version, '0.13.0');
}

function anImplausibleSizeIsRefused(): void {
  for (const size of [0, -5, 401 * 1024 * 1024, Number.NaN, '60' as unknown as number]) {
    const odd = release('0.13.0', {}, [{
      name: 'kriko-agent-0.13.0.apk', size,
      browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk`,
    }]);
    assert.equal(pickUpdate([odd], '0.12.1'), null, `size ${String(size)}`);
  }
  const notUploaded = release('0.13.0', {}, [{
    name: 'kriko-agent-0.13.0.apk', size: 1000, state: 'starter',
    browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk`,
  }]);
  assert.equal(pickUpdate([notUploaded], '0.12.1'), null, 'a file still uploading is not offered');
}

function theChecksumComesFromTheDigestOrASiblingFile(): void {
  const withoutDigest = release('0.13.0', {}, [
    { name: 'kriko-agent-0.13.0.apk', size: 1000, browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk` },
    { name: 'kriko-agent-0.13.0.apk.sha256', size: 90, browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk.sha256` },
  ]);
  const offered = pickUpdate([withoutDigest], '0.12.1');
  assert.equal(offered?.sha256, '');
  assert.equal(offered?.checksumUrl, `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk.sha256`);
  const badDigest = release('0.13.0', {}, [{
    name: 'kriko-agent-0.13.0.apk', size: 1000, digest: 'sha256:xyz',
    browser_download_url: `${DEFAULT_ASSET_PREFIX}mobile-v0.13.0/kriko-agent-0.13.0.apk`,
  }]);
  assert.equal(pickUpdate([badDigest], '0.12.1')?.sha256, '', 'a malformed digest is no digest');
  assert.equal(parseChecksum(`${HASH}  kriko-agent-0.13.0.apk\n`), HASH.toLowerCase());
  assert.equal(parseChecksum('not a hash'), '');
  assert.equal(parseChecksum('a'.repeat(65)), '', 'a word longer than a digest is not one');
}

function junkInTheListNeverThrows(): void {
  for (const junk of [null, undefined, 42, 'x', {}, [null, 7, 'a', [], { tag_name: 5 }]]) {
    assert.equal(pickUpdate(junk, '0.12.1'), null);
  }
  const mixed = [null, 7, release('0.13.0', { assets: [null, 3] }), release('0.12.2')];
  assert.equal(pickUpdate(mixed, '0.12.1')?.version, '0.12.2');
}

function notesAreAFewPlainLines(): void {
  assert.deepEqual(releaseNotes(undefined), []);
  assert.deepEqual(releaseNotes(''), []);
  const long = Array.from({ length: 12 }, (_, index) => `- line ${index + 1}`).join('\n');
  assert.equal(releaseNotes(long).length, 6);
  const wide = releaseNotes(`- ${'word '.repeat(80)}`);
  assert.ok(wide[0].length <= 160 && wide[0].endsWith('…'));
}

function aKeptUpdateComesBackOnlyIfItIsStillNewerAndStillOurs(): void {
  const found = pickUpdate([release('0.13.0', { digest: `sha256:${HASH}` })], '0.12.1');
  assert.ok(found);
  // Through storage and back, as JSON.
  const stored = JSON.parse(JSON.stringify(found)) as unknown;
  assert.deepEqual(restoreUpdate(stored, '0.12.1'), found);
  assert.equal(restoreUpdate(stored, '0.13.0'), null, 'installed since: nothing to offer');
  assert.equal(restoreUpdate(stored, '0.14.0'), null, 'a newer build is installed already');
  assert.equal(restoreUpdate(null, '0.12.1'), null);
  assert.equal(restoreUpdate('x', '0.12.1'), null);
  assert.equal(restoreUpdate({ ...found, apkUrl: 'https://example.com/a.apk' }, '0.12.1'), null, 'a stored foreign address is dropped');
  assert.equal(restoreUpdate({ ...found, bytes: 'big' }, '0.12.1'), null);
  assert.equal(restoreUpdate({ ...found, version: 'latest' }, '0.12.1'), null);
  assert.equal(restoreUpdate({ ...found, sha256: 'nothex' }, '0.12.1')?.sha256, '', 'a damaged checksum is no checksum');
  assert.equal(restoreUpdate({ ...found, notes: 'text' }, '0.12.1')?.notes.length, 0);
}

function aLookIsDueOnlyOncePerInterval(): void {
  const now = 1_800_000_000_000;
  assert.equal(checkIsDue(0, now), true, 'never checked');
  assert.equal(checkIsDue(Number.NaN, now), true);
  assert.equal(checkIsDue(now - 1000, now), false);
  assert.equal(checkIsDue(now - CHECK_EVERY_MS, now), true);
  assert.equal(checkIsDue(now + 60_000, now), true, 'a clock that went backwards');
}

versionsCompareByNumberNotByText();
theNewestMobileReleaseIsOffered();
nothingNewerMeansNoOffer();
theDesktopAppsReleasesAreNotOurs();
draftsAndPreReleasesAreNeverOffered();
theFileMustBeTheOneTheTagNames();
theFileMustComeFromTheReleasesOfThisRepository();
anImplausibleSizeIsRefused();
theChecksumComesFromTheDigestOrASiblingFile();
junkInTheListNeverThrows();
notesAreAFewPlainLines();
aKeptUpdateComesBackOnlyIfItIsStillNewerAndStillOurs();
aLookIsDueOnlyOncePerInterval();
process.stdout.write('App update checks passed.\n');
