import type { Reading, VisualCandidate } from './types';

/** Preserve bounded visual observations when a scan is restored from storage. */
export function normalizeReading(value: unknown): Reading | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const string = (key: string, max = 900) => typeof raw[key] === 'string' ? raw[key].slice(0, max) : '';
  const candidates: VisualCandidate[] = [];
  const seen = new Set<string>();
  for (const item of Array.isArray(raw.visualCandidates) ? raw.visualCandidates : []) {
    if (!item || typeof item !== 'object' || typeof item.name !== 'string') continue;
    const name = item.name.trim().slice(0, 160);
    if (!name || seen.has(name.toLowerCase())) continue;
    seen.add(name.toLowerCase());
    candidates.push({ name, confidence: item.confidence === 'high' || item.confidence === 'medium' ? item.confidence : 'low', reason: typeof item.reason === 'string' ? item.reason.slice(0, 240) : '' });
    if (candidates.length === 3) break;
  }
  const basis = string('identityBasis', 20);
  return {
    brand: string('brand', 80), product: string('product', 160), model: string('model', 80),
    price: string('price', 40), condition: string('condition', 20) || 'unknown',
    detail: string('detail'), note: string('note', 240),
    site: string('site', 120) || undefined, url: string('url', 2048) || undefined,
    visualDescription: string('visualDescription', 600) || undefined,
    identityBasis: basis === 'text' || basis === 'appearance' || basis === 'mixed' || basis === 'unknown' ? basis : undefined,
    visualCandidates: candidates.length ? candidates : undefined,
  };
}

/** A clearly visible unlabelled object is useful input, even without OCR text. */
export function hasProductReading(reading: Reading): boolean {
  return Boolean(reading.brand.trim() || reading.product.trim() || reading.model.trim() ||
    reading.price.trim() || reading.detail.trim() || reading.visualDescription?.trim() || reading.visualCandidates?.length);
}

/** Keep provisional visual names visibly provisional in every scan surface. */
export function productReadingTitle(reading: Reading, includeModel = false): string {
  const candidate = reading.visualCandidates?.[0];
  const visualOnly = reading.identityBasis === 'appearance' || reading.identityBasis === 'unknown';
  const named = [reading.brand, reading.product, includeModel ? reading.model : ''].filter(Boolean).join(' ').trim();
  if (visualOnly) {
    const proposed = candidate?.name || named || reading.model || reading.visualDescription?.slice(0, 80);
    return proposed ? `Possible: ${proposed}` : '';
  }
  if (named) return named;
  if (candidate) return `Possible: ${candidate.name}`;
  return reading.model || reading.visualDescription?.slice(0, 80) || '';
}
