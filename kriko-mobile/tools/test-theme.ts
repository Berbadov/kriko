/**
 * The theme contract: four palettes with one vocabulary, and a resolver that
 * treats `system` as the phone's choice and an explicit choice as final.
 *
 * A missing key in one palette is a component that turns the wrong colour the
 * moment the reader picks that theme, so this is checked rather than assumed.
 */

import assert from 'node:assert/strict';

import { darkColors, grayColors, paperColors, palettes, whiteColors } from '../src/theme/palettes';
import {
  isAppearance,
  isDarkPalette,
  isMotionPreference,
  isTextSize,
  nearestPuckOpacityStep,
  normalizePuckOpacity,
  PUCK_OPACITY_DEFAULT,
  PUCK_OPACITY_STEPS,
  resolvePalette,
  TEXT_SCALE,
} from '../src/theme/preferences';
import { toneColor } from '../src/theme/tone';
import { type as typeScale } from '../src/theme/tokens';

const darkKeys = Object.keys(darkColors).sort();
assert.deepEqual(Object.keys(paperColors).sort(), darkKeys, 'paper must carry every dark token');
assert.deepEqual(Object.keys(grayColors).sort(), darkKeys, 'gray must carry every dark token');
assert.deepEqual(Object.keys(whiteColors).sort(), darkKeys, 'white must carry every dark token');
assert.deepEqual(Object.keys(palettes).sort(), ['dark', 'gray', 'paper', 'white']);
assert.notEqual(grayColors.ground, darkColors.ground, 'gray must not resolve to the black background');
assert.notEqual(grayColors.surface, darkColors.surface, 'gray cards must have their own surface');

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((offset) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
// Every palette, light or dark: body, secondary and tertiary text reach WCAG AA
// (4.5:1) on both the page and a card, so no theme is a readability trade-off.
for (const palette of [darkColors, grayColors, paperColors, whiteColors]) {
  for (const ink of [palette.ink, palette.ink2, palette.ink3]) {
    for (const ground of [palette.surface, palette.ground]) {
      const values = [luminance(ink), luminance(ground)].sort((a, b) => a - b);
      assert.ok((values[1] + 0.05) / (values[0] + 0.05) >= 4.5, `${ink} must remain readable on ${ground}`);
    }
  }
}

// The reading floor: nothing in the type scale is drawn below 13 pt, running
// text is at least 16 pt, and tracking is never negative (it closes the gaps
// the typeface was drawn to keep open).
for (const [name, style] of Object.entries(typeScale)) {
  assert.ok(style.fontSize >= 13, `${name} is drawn at ${style.fontSize} pt, below the 13 pt floor`);
  assert.ok(style.letterSpacing >= 0, `${name} has negative tracking`);
  // Display sizes may close up to 1.1; anything under 28 pt keeps a 1.25 line.
  const leading = style.fontSize >= 28 ? 1.1 : 1.25;
  assert.ok(style.lineHeight >= style.fontSize * leading, `${name} is set too tight to read`);
}
assert.ok(typeScale.body.fontSize >= 16 && typeScale.rowText.fontSize >= 16 && typeScale.input.fontSize >= 16);
assert.equal(typeScale.body.fontFamily, 'Atkinson-Regular');

assert.equal(resolvePalette('system', 'light'), 'paper');
assert.equal(resolvePalette('system', 'dark'), 'dark');
assert.equal(resolvePalette('system', null), 'dark');
assert.equal(resolvePalette('white', 'dark'), 'white');
assert.equal(resolvePalette('gray', 'light'), 'gray');
assert.equal(resolvePalette('paper', 'light'), 'paper');
assert.equal(resolvePalette('dark', 'light'), 'dark');

assert.equal(isAppearance('white'), true);
assert.equal(isAppearance('gray'), true);
assert.equal(isAppearance('blue'), false);
assert.equal(isDarkPalette('gray'), true);
assert.equal(isDarkPalette('paper'), false);
assert.equal(isTextSize('large'), true);
assert.equal(isTextSize(14), false);
assert.equal(isMotionPreference('reduced'), true);
assert.equal(isMotionPreference('none'), false);
assert.equal(TEXT_SCALE.default, 1);
assert.ok(TEXT_SCALE.small < 1 && TEXT_SCALE.large > 1);
assert.ok(TEXT_SCALE.large < TEXT_SCALE.xlarge, 'extra large is larger than large');
assert.equal(isTextSize('xlarge'), true);
for (const palette of [darkColors, grayColors, paperColors, whiteColors]) {
  assert.ok(palette.plate && palette.rim, 'every palette names a reading plate and a glass rim');
}

// The floating K's opacity: every offered step survives a round trip, a stored
// value outside the range is pulled back into it, and junk is the default, so a
// damaged preferences file can never make the scanner invisible.
for (const step of PUCK_OPACITY_STEPS) assert.equal(normalizePuckOpacity(step), step);
assert.ok(PUCK_OPACITY_STEPS.includes(PUCK_OPACITY_DEFAULT), 'the default is one of the offered steps');
assert.equal(normalizePuckOpacity(0), 20, 'fully invisible is not a choice');
assert.equal(normalizePuckOpacity(-40), 20);
assert.equal(normalizePuckOpacity(250), 100);
assert.equal(normalizePuckOpacity('75'), 75);
assert.equal(normalizePuckOpacity(Number.NaN), PUCK_OPACITY_DEFAULT);
assert.equal(normalizePuckOpacity(undefined), PUCK_OPACITY_DEFAULT);
assert.equal(normalizePuckOpacity(null), PUCK_OPACITY_DEFAULT);
assert.equal(normalizePuckOpacity(''), PUCK_OPACITY_DEFAULT);
assert.equal(normalizePuckOpacity(true), PUCK_OPACITY_DEFAULT);
assert.equal(normalizePuckOpacity('very'), PUCK_OPACITY_DEFAULT);
assert.equal(nearestPuckOpacityStep(60), 55);
assert.equal(nearestPuckOpacityStep(90), 100);
assert.equal(nearestPuckOpacityStep(20), 35);
for (const step of PUCK_OPACITY_STEPS) assert.equal(nearestPuckOpacityStep(step), step);

// A text tone is a palette token or a raw colour. A name that is neither must not
// reach React Native as a colour (drawn black, invisible on the dark theme): it
// reads as ink, so a misspelt tone is seen and fixed rather than lost.
for (const [name, palette] of Object.entries(palettes)) {
  assert.equal(toneColor(palette, 'ink3'), palette.ink3, `${name}: a token resolves to its colour`);
  assert.equal(toneColor(palette, '#abcdef'), '#abcdef');
  assert.equal(toneColor(palette, 'rgba(255,255,255,0.78)'), 'rgba(255,255,255,0.78)');
  assert.equal(toneColor(palette, 'transparent'), 'transparent');
  assert.equal(toneColor(palette, 'muted'), palette.ink, `${name}: an unknown tone reads as ink`);
}

process.stdout.write('theme checks passed.\n');
