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
  resolvePalette,
  TEXT_SCALE,
} from '../src/theme/preferences';

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

process.stdout.write('theme checks passed.\n');
