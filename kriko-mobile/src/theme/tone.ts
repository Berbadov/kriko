/**
 * The colour a text tone names: a token from the current palette, or a raw
 * colour string. A name that is neither reads as plain ink. Handing React Native
 * an invalid colour draws the text in the platform default (black), which the
 * dark theme hides, so a misspelt tone must fail visibly rather than vanish.
 */
export function toneColor(palette: Record<string, string>, tone: string): string {
  const token = palette[tone];
  if (token) return token;
  return /^(#|rgb|hsl|transparent$)/i.test(tone) ? tone : palette.ink;
}
