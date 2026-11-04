import AsyncStorage from '@react-native-async-storage/async-storage';
import type { Reading } from './types';
import { createAuditTransactions } from './screenAuditCore';

const STORAGE_KEY = 'kriko.agent.screen-audit.v1';
export const SCREEN_AUDIT_LIMIT = 50;
export type ScreenAuditStatus = 'reading' | 'success' | 'error';
export interface ScreenAuditEntry {
  id: string;
  at: number;
  imageUri?: string;
  status: ScreenAuditStatus;
  reading?: Reading;
}

function safeUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined;
    url.username = '';
    url.password = '';
    url.search = '';
    url.hash = '';
    return url.toString().slice(0, 2048);
  } catch { return undefined; }
}

const auditStore = createAuditTransactions<ScreenAuditEntry>(AsyncStorage, STORAGE_KEY, SCREEN_AUDIT_LIMIT);

function safeReading(value: unknown): Reading | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const source = value as Partial<Reading>;
  const text = (item: unknown) => typeof item === 'string'
    ? item.slice(0, 12000)
      .replace(/\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{16,})\b/g, '[redacted credential]')
      .replace(/\b(api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*[^\s,;]+/gi, '$1: [redacted credential]')
    : '';
  return {
    brand: text(source.brand), product: text(source.product), model: text(source.model),
    price: text(source.price), condition: text(source.condition), detail: text(source.detail), note: text(source.note),
    ...(typeof source.site === 'string' ? { site: source.site.slice(0, 500) } : {}),
    ...(safeUrl(source.url) ? { url: safeUrl(source.url) } : {}),
    ...(typeof source.visualDescription === 'string' ? { visualDescription: source.visualDescription.slice(0, 4000) } : {}),
    ...(source.identityBasis === 'text' || source.identityBasis === 'appearance' || source.identityBasis === 'mixed' || source.identityBasis === 'unknown' ? { identityBasis: source.identityBasis } : {}),
    ...(Array.isArray(source.visualCandidates) ? { visualCandidates: source.visualCandidates.slice(0, 8).map((candidate) => ({
      name: text(candidate.name).slice(0, 300),
      confidence: candidate.confidence === 'high' || candidate.confidence === 'medium' ? candidate.confidence : 'low',
      reason: text(candidate.reason).slice(0, 1000),
    })) } : {}),
  };
}

function normalize(value: unknown): ScreenAuditEntry[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is ScreenAuditEntry => Boolean(item && typeof item === 'object' && typeof item.id === 'string'))
    .slice(-SCREEN_AUDIT_LIMIT).map((entry) => ({
      id: entry.id,
      at: Number.isFinite(entry.at) ? entry.at : Date.now(),
      ...(typeof entry.imageUri === 'string' ? { imageUri: entry.imageUri } : {}),
      status: entry.status === 'success' || entry.status === 'error' ? entry.status : 'reading',
      ...(safeReading(entry.reading) ? { reading: safeReading(entry.reading) } : {}),
    }));
}

export async function loadScreenAudit(): Promise<ScreenAuditEntry[]> {
  try { return normalize(await auditStore.load()); }
  catch { return []; }
}

export function beginScreenAudit(entry: ScreenAuditEntry): Promise<number | null> {
  return auditStore.begin({ ...entry, status: 'reading', reading: undefined });
}

export function finishScreenAudit(id: string, result: { reading?: Reading; failed?: boolean }, epoch: number): Promise<boolean> {
  const patch: Partial<ScreenAuditEntry> = {
    status: result.failed ? 'error' : 'success',
    ...(result.reading ? { reading: safeReading(result.reading) } : {}),
  };
  return auditStore.finish(id, patch, epoch);
}

export async function clearScreenAudit(): Promise<ScreenAuditEntry[]> {
  return normalize(await auditStore.clear());
}
