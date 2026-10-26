/**
 * The theme contract: three palettes with one vocabulary, and a resolver that
 * treats `system` as the phone's choice and an explicit choice as final.
 *
 * A missing key in one palette is a component that turns the wrong colour the
 * moment the reader picks that theme, so this is checked rather than assumed.
 */

import assert from 'node:assert/strict';

import { darkColors, paperColors, palettes, whiteColors } from '../src/theme/palettes';
import {
  isAppearance,
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

const darkKeys = Object.keys(darkColors).sort();
assert.deepEqual(Object.keys(paperColors).sort(), darkKeys, 'paper must carry every dark token');
assert.deepEqual(Object.keys(whiteColors).sort(), darkKeys, 'white must carry every dark token');
assert.deepEqual(Object.keys(palettes).sort(), ['dark', 'paper', 'white']);

assert.equal(resolvePalette('system', 'light'), 'paper');
assert.equal(resolvePalette('system', 'dark'), 'dark');
assert.equal(resolvePalette('system', null), 'dark');
assert.equal(resolvePalette('white', 'dark'), 'white');
assert.equal(resolvePalette('paper', 'light'), 'paper');
assert.equal(resolvePalette('dark', 'light'), 'dark');

assert.equal(isAppearance('white'), true);
assert.equal(isAppearance('blue'), false);
assert.equal(isTextSize('large'), true);
assert.equal(isTextSize(14), false);
assert.equal(isMotionPreference('reduced'), true);
assert.equal(isMotionPreference('none'), false);
assert.equal(TEXT_SCALE.default, 1);
assert.ok(TEXT_SCALE.small < 1 && TEXT_SCALE.large > 1);

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
