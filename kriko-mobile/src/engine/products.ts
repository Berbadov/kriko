/** Source-bound product metadata. Image URLs are accepted only from the exact
 * merchant page (JSON-LD/OpenGraph) and must be absolute HTTPS URLs. */
export interface ProductMetadata { imageUrl: string; price?: string; }

export function validHttpsUrl(value: unknown): string {
  if (typeof value !== 'string' || value.length > 2048) return '';
  try {
    const url = new URL(value.trim());
    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '');
    if (url.protocol !== 'https:' || !host || url.username || url.password ||
        host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') ||
        host === '::' || host === '::1' || (host.includes(':') && (host.startsWith('fc') || host.startsWith('fd') || host.startsWith('fe80:'))) ||
        /^127\./.test(host) || /^10\./.test(host) || /^192\.168\./.test(host) ||
        /^169\.254\./.test(host) || /^0\./.test(host) ||
        /^172\.(?:1[6-9]|2\d|3[01])\./.test(host)) return '';
    return url.toString();
  } catch { return ''; }
}

function unescapeHtml(value: string): string {
  const safePoint = (n: number) => n > 0 && n <= 0x10ffff && !(n >= 0xd800 && n <= 0xdfff) ? String.fromCodePoint(n) : '\uFFFD';
  return value.replace(/&amp;/gi, '&').replace(/&#x([\da-f]+);/gi, (_, hex: string) => safePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, decimal: string) => safePoint(Number(decimal)))
    .replace(/&quot;/gi, '"').replace(/&#39;|&apos;/gi, "'").replace(/&lt;/gi, '<').replace(/&gt;/gi, '>');
}

function attr(html: string, name: string): string {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = html.match(new RegExp(`\\b${escaped}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'));
  return unescapeHtml(match?.[1] ?? match?.[2] ?? match?.[3] ?? '');
}

function productJsonLd(html: string): Record<string, unknown>[] {
  const products: Record<string, unknown>[] = [];
  for (const match of html.matchAll(/<script\b[^>]*type\s*=\s*["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script\s*>/gi)) {
    try {
      const collect = (value: unknown) => {
        if (Array.isArray(value)) value.forEach(collect);
        else if (value && typeof value === 'object') {
          const row = value as Record<string, unknown>;
          if (String(row['@type'] ?? '').toLowerCase() === 'product') products.push(row);
          if (row['@graph']) collect(row['@graph']);
        }
      };
      collect(JSON.parse(match[1]));
    } catch { /* malformed or untrusted page metadata */ }
  }
  return products;
}

export function parseProductMetadata(html: string, pageUrl?: string): ProductMetadata | null {
  const bounded = html.slice(0, 1_000_000);
  let image = '';
  let amount = '';
  let currency = '';
  const imageUrl = (value: unknown) => {
    if (typeof value !== 'string' || value.includes('\uFFFD')) return '';
    const absolute = validHttpsUrl(value);
    if (absolute) return absolute;
    if (!pageUrl) return '';
    try {
      const resolved = new URL(value.trim(), pageUrl);
      return validHttpsUrl(resolved.toString());
    } catch { return ''; }
  };
  for (const tag of bounded.match(/<meta\b[^>]*>/gi) ?? []) {
    const key = (attr(tag, 'property') || attr(tag, 'name')).toLowerCase();
    if (!image && ['og:image', 'og:image:url', 'twitter:image'].includes(key)) image = imageUrl(attr(tag, 'content'));
    if (!amount && ['product:price:amount', 'og:price:amount'].includes(key)) amount = attr(tag, 'content').slice(0, 40);
    if (!currency && ['product:price:currency', 'og:price:currency'].includes(key)) currency = attr(tag, 'content').slice(0, 8);
  }
  for (const row of productJsonLd(bounded)) {
    if (!image) {
      const candidate = row.image;
      const raw = typeof candidate === 'string' ? candidate
        : Array.isArray(candidate) ? candidate.find((item) => typeof item === 'string')
          : candidate && typeof candidate === 'object' ? (candidate as Record<string, unknown>).url : '';
      image = imageUrl(raw);
    }
    const offers = Array.isArray(row.offers) ? row.offers[0] : row.offers;
    if (offers && typeof offers === 'object') {
      const offer = offers as Record<string, unknown>;
      if (!amount && (typeof offer.price === 'string' || typeof offer.price === 'number')) amount = String(offer.price).slice(0, 40);
      if (!currency && typeof offer.priceCurrency === 'string') currency = offer.priceCurrency.slice(0, 8);
    }
  }
  const price = amount && /^[A-Za-z]{3}$/.test(currency) ? `${currency.toUpperCase()} ${amount}` : '';
  return image ? { imageUrl: image, ...(price ? { price } : {}) } : null;
}

/** Fetch HTML only from the exact HTTPS search-result URL. Never follow a
 * cross-host redirect, cap bytes/time, and treat every returned field as untrusted. */
export async function fetchProductMetadata(pageUrl: string, signal?: AbortSignal): Promise<ProductMetadata | null> {
  const safe = validHttpsUrl(pageUrl);
  if (!safe || signal?.aborted || typeof XMLHttpRequest === 'undefined') return null;
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    let settled = false;
    let timer: ReturnType<typeof setTimeout>;
    const finish = (value: ProductMetadata | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      resolve(value);
    };
    const abort = () => { try { xhr.abort(); } catch { /* already complete */ } finish(null); };
    timer = setTimeout(abort, 4500);
    signal?.addEventListener('abort', abort, { once: true });
    try {
      xhr.open('GET', safe, true);
      xhr.timeout = 4500;
      xhr.setRequestHeader('Accept', 'text/html,application/xhtml+xml');
      xhr.onprogress = () => {
        try { if (xhr.responseText.length > 1_000_000) abort(); } catch { abort(); }
      };
      xhr.onerror = () => finish(null);
      xhr.ontimeout = () => finish(null);
      xhr.onabort = () => finish(null);
      xhr.onreadystatechange = () => {
        if (xhr.readyState !== 4 || settled) return;
        try {
          const finalUrl = validHttpsUrl(xhr.responseURL);
          const finalPage = finalUrl ? new URL(finalUrl) : null;
          const requestedPage = new URL(safe);
          const samePage = Boolean(finalPage && finalPage.hostname.toLowerCase() === requestedPage.hostname.toLowerCase() &&
            finalPage.pathname === requestedPage.pathname && finalPage.search === requestedPage.search);
          const contentType = xhr.getResponseHeader('content-type') ?? '';
          if (xhr.status < 200 || xhr.status >= 300 || !samePage ||
              !/^text\/html\b|^application\/xhtml\+xml\b/i.test(contentType) || xhr.responseText.length > 1_000_000) {
            finish(null);
            return;
          }
          finish(parseProductMetadata(xhr.responseText, safe));
        } catch { finish(null); }
      };
      xhr.send();
    } catch { finish(null); }
  });
}

