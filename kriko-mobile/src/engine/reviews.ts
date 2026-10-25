/** Host parsing and boundary checks for an explicitly requested site's reviews. */

export function normalizeReviewSite(value: unknown): string {
  if (typeof value !== 'string') return '';
  const input = value.trim();
  if (!input || input.length > 2048) return '';
  const candidate = /^[a-z][a-z\d+.-]*:\/\//i.test(input) ? input : `https://${input}`;
  try {
    const url = new URL(candidate);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return '';
    const hostname = url.hostname.toLowerCase().replace(/^www\./, '').replace(/\.$/, '');
    if (!hostname.includes('.') || hostname.includes('..') || hostname.length > 100) return '';
    return hostname;
  } catch {
    return '';
  }
}

export function scopeReviewQuery(query: string, site: string, maxLength = 128): string {
  const suffix = `site:${site}`;
  const room = maxLength - suffix.length - 1;
  if (room <= 0) return '';
  const words = query.replace(/\s+/g, ' ').trim();
  let prefix = words;
  if (prefix.length > room) {
    const cut = prefix.slice(0, room);
    prefix = cut.slice(0, cut.lastIndexOf(' ') > 0 ? cut.lastIndexOf(' ') : cut.length).trim();
  }
  return `${prefix ? `${prefix} ` : ''}${suffix}`;
}

/** Exact product page URL supplied by the reader, if it belongs to the site. */
export function resolveReviewUrl(explicit: unknown, reading: { url?: string } | null | undefined, question: string, site: string): string {
  const direct = visibleReviewUrl(explicit) || visibleReviewUrl(reading?.url);
  if (direct && isReviewSiteUrl(direct, site)) {
    const url = new URL(direct);
    if (url.pathname !== '/' || url.search) return url.toString();
  }
  const urls = question.match(/https:\/\/[^\s]+/gi) ?? [];
  const matches = [...new Set(urls
    .map((value) => visibleReviewUrl(value.replace(/[),.;]+$/, '')))
    .filter((value) => value && isReviewSiteUrl(value, site))
    .filter((value) => new URL(value).pathname !== '/' || new URL(value).search))];
  return matches.length === 1 ? matches[0] : '';
}

/** Accept only an explicitly supplied site, URL, or one unambiguous domain in the question. */
export function resolveReviewSite(
  explicit: unknown,
  reading: { site?: string; url?: string } | null | undefined,
  question: string,
): string {
  const provided = normalizeReviewSite(explicit);
  if (provided) return provided;
  const imageSite = normalizeReviewSite(reading?.url) || normalizeReviewSite(reading?.site);
  if (imageSite) return imageSite;
  const matches = question.match(/(?:https?:\/\/)?(?:www\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+(?:\/[^\s]*)?/gi) ?? [];
  const hosts = [...new Set(matches.map(normalizeReviewSite).filter(Boolean))];
  return hosts.length === 1 ? hosts[0] : '';
}

export function isReviewSiteUrl(value: unknown, site: string): boolean {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return false;
    const host = url.hostname.toLowerCase().replace(/^www\./, '').replace(/\.$/, '');
    return host === site || host.endsWith(`.${site}`);
  } catch {
    return false;
  }
}

/** Keep a visible product URL only when it is legible, credential-free HTTPS. */
export function visibleReviewUrl(value: unknown): string {
  if (typeof value !== 'string' || value.trim().length > 2048) return '';
  try {
    const url = new URL(value.trim());
    if (url.protocol !== 'https:' || url.username || url.password || !url.hostname.includes('.')) return '';
    return url.toString();
  } catch {
    return '';
  }
}
