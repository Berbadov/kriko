/**
 * Finding a newer build of this app among GitHub's releases. Pure: the caller
 * fetches the list, this decides which release (if any) the phone should offer.
 *
 * The repository's releases belong mostly to the desktop app, and its "Latest"
 * is the desktop installer, so the phone keeps its own family of tags,
 * `mobile-v<major>.<minor>.<patch>`, each carrying one `kriko-agent-<version>.apk`.
 * Everything in the list is untrusted text: a release is offered only when its
 * tag, its file name and the address of the file all have the expected shape.
 */

import { plainPreview } from './preview';

export const DEFAULT_RELEASES_URL = 'https://api.github.com/repos/Berbadov/kriko/releases?per_page=30';
/** Every file of a release is served from here; anything else is not ours. */
export const DEFAULT_ASSET_PREFIX = 'https://github.com/Berbadov/kriko/releases/download/';

const TAG = /^mobile-v(\d{1,4}\.\d{1,4}\.\d{1,4})$/;
const MAX_APK_BYTES = 400 * 1024 * 1024;

export type AppUpdate = {
  version: string;
  tag: string;
  /** What changed, as a few plain lines. */
  notes: string[];
  apkUrl: string;
  bytes: number;
  /** Lowercase hex SHA-256 of the file when GitHub states it; empty when it does not. */
  sha256: string;
  /** A `.sha256` file beside the APK, used when GitHub states no digest itself. */
  checksumUrl: string;
  publishedAt: string;
  pageUrl: string;
};

type Triple = [number, number, number];

export function parseVersion(text: unknown): Triple | null {
  const match = /^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$/.exec(String(text ?? '').trim());
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

/** -1, 0 or 1. A version that does not parse counts as 0.0.0, so it is never "newer". */
export function compareVersions(a: string, b: string): number {
  const left = parseVersion(a) ?? [0, 0, 0];
  const right = parseVersion(b) ?? [0, 0, 0];
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) return left[index] < right[index] ? -1 : 1;
  }
  return 0;
}

/** "58 MB", or "4.5 MB" under ten: how big a download is, in words a phone reader knows. */
export function formatSize(bytes: number): string {
  if (!(bytes > 0)) return '0 MB';
  const megabytes = bytes / (1024 * 1024);
  return megabytes >= 10 ? `${Math.round(megabytes)} MB` : `${megabytes.toFixed(1)} MB`;
}

/** The first 64-digit hexadecimal word in a checksum file (`<hash>  <name>` or just `<hash>`). */
export function parseChecksum(text: string): string {
  const match = /\b([0-9a-f]{64})\b/i.exec(text);
  return match ? match[1].toLowerCase() : '';
}

/** A few plain lines from a release's Markdown body. */
export function releaseNotes(body: unknown): string[] {
  if (typeof body !== 'string') return [];
  return body
    .split(/\r?\n/)
    // A heading is a title for the list, not one of its lines.
    .filter((line) => !/^\s*#{1,6}\s/.test(line))
    .map((line) => plainPreview(line))
    .filter(Boolean)
    .slice(0, 6)
    .map((line) => (line.length > 160 ? `${line.slice(0, 157)}…` : line));
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function readRelease(row: unknown, prefix: string): AppUpdate | null {
  const release = asRecord(row);
  if (!release || release.draft === true || release.prerelease === true) return null;
  const tag = typeof release.tag_name === 'string' ? release.tag_name : '';
  const match = TAG.exec(tag);
  if (!match) return null;
  const version = match[1];
  const assets = Array.isArray(release.assets) ? release.assets.map(asRecord) : [];
  const file = assets.find((asset) => asset?.name === `kriko-agent-${version}.apk`);
  if (!file) return null;
  const apkUrl = typeof file.browser_download_url === 'string' ? file.browser_download_url : '';
  const bytes = typeof file.size === 'number' ? file.size : 0;
  if (!apkUrl.startsWith(prefix) || !(bytes > 0 && bytes <= MAX_APK_BYTES)) return null;
  if (file.state !== undefined && file.state !== 'uploaded') return null;

  const digest = typeof file.digest === 'string' ? /^sha256:([0-9a-f]{64})$/i.exec(file.digest) : null;
  const sidecar = assets.find((asset) => asset?.name === `kriko-agent-${version}.apk.sha256`);
  const sidecarUrl = typeof sidecar?.browser_download_url === 'string' ? sidecar.browser_download_url : '';
  const page = typeof release.html_url === 'string' ? release.html_url : '';
  return {
    version,
    tag,
    notes: releaseNotes(release.body),
    apkUrl,
    bytes,
    sha256: digest ? digest[1].toLowerCase() : '',
    checksumUrl: sidecarUrl.startsWith(prefix) ? sidecarUrl : '',
    publishedAt: typeof release.published_at === 'string' ? release.published_at : '',
    pageUrl: page.startsWith('https://github.com/') ? page : '',
  };
}

/**
 * The newest release that is newer than `installed`, or null. Drafts and
 * pre-releases are never offered; the highest version wins, not the first listed.
 */
export function pickUpdate(releases: unknown, installed: string, options: { assetPrefix?: string } = {}): AppUpdate | null {
  if (!Array.isArray(releases)) return null;
  const prefix = options.assetPrefix ?? DEFAULT_ASSET_PREFIX;
  let best: AppUpdate | null = null;
  for (const row of releases) {
    const candidate = readRelease(row, prefix);
    if (!candidate || compareVersions(candidate.version, installed) <= 0) continue;
    if (!best || compareVersions(candidate.version, best.version) > 0) best = candidate;
  }
  return best;
}

/**
 * An update an earlier look found and the phone kept, if it is still newer than
 * what is installed and still has the shape `pickUpdate` gives it. What comes
 * back from storage is checked like anything else: a stored address that is not
 * one of this repository's release files is dropped.
 */
export function restoreUpdate(value: unknown, installed: string, options: { assetPrefix?: string } = {}): AppUpdate | null {
  const row = asRecord(value);
  if (!row) return null;
  const prefix = options.assetPrefix ?? DEFAULT_ASSET_PREFIX;
  const version = typeof row.version === 'string' ? row.version : '';
  if (!parseVersion(version) || compareVersions(version, installed) <= 0) return null;
  const apkUrl = typeof row.apkUrl === 'string' ? row.apkUrl : '';
  const bytes = typeof row.bytes === 'number' ? row.bytes : 0;
  if (!apkUrl.startsWith(prefix) || !(bytes > 0 && bytes <= MAX_APK_BYTES)) return null;
  const checksumUrl = typeof row.checksumUrl === 'string' && row.checksumUrl.startsWith(prefix) ? row.checksumUrl : '';
  const page = typeof row.pageUrl === 'string' && row.pageUrl.startsWith('https://github.com/') ? row.pageUrl : '';
  const notes = Array.isArray(row.notes)
    ? row.notes.filter((line): line is string => typeof line === 'string').slice(0, 6).map((line) => line.slice(0, 160))
    : [];
  return {
    version,
    tag: `mobile-v${version}`,
    notes,
    apkUrl,
    bytes,
    sha256: typeof row.sha256 === 'string' && /^[0-9a-f]{64}$/.test(row.sha256) ? row.sha256 : '',
    checksumUrl,
    publishedAt: typeof row.publishedAt === 'string' ? row.publishedAt : '',
    pageUrl: page,
  };
}

/** Hours between automatic looks. A manual check always goes ahead. */
export const CHECK_EVERY_MS = 12 * 60 * 60 * 1000;

/** Whether an automatic look is due. A clock that went backwards counts as due. */
export function checkIsDue(lastCheckedAt: number, now: number, every = CHECK_EVERY_MS): boolean {
  if (!Number.isFinite(lastCheckedAt) || lastCheckedAt <= 0) return true;
  return now < lastCheckedAt || now - lastCheckedAt >= every;
}
