/**
 * The phone's copy of the dust engine, run without a screen: grains settle
 * where a scene puts dust, still moves nothing, and a picture comes only from
 * generic product words. The same file ships in the desktop app, which has
 * the fuller set of these checks.
 */

import assert from 'node:assert/strict';

import { Dust, kindFor, product, reading } from '../src/dust/engine';

const dust = new Dust({ count: 2000 });
dust.resize(390, 300);
const scene = product('keyboard');
dust.show(scene, { settle: true });
let under = 0;
for (let i = 0; i < dust.count; i++) under += scene.density(dust.x[i], dust.y[i], dust.w, dust.h);
let field = 0;
for (let i = 0; i < 2000; i++) field += scene.density(((i * 37) % 390) + 0.5, ((i * 53) % 300) + 0.5, 390, 300);
assert.ok(under / dust.count > (field / 2000) * 2, 'grains settle where the keyboard is drawn');

dust.show(reading, { settle: true });
const before = Float32Array.from(dust.x);
for (let f = 0; f < 30; f++) dust.step(1, f / 60, 'still');
assert.deepEqual(Array.from(dust.x), Array.from(before), 'still moves nothing');

const out = dust.buffers(8);
dust.sort(out, { band: { y: 100, width: 20 } });
assert.equal(out.counts.reduce((a, b) => a + b, 0), dust.count, 'every grain is drawn once');

assert.equal(kindFor('Logitech Bluetooth keyboard'), 'keyboard');
assert.equal(kindFor('Çamaşır makinesi'), 'washer');
assert.equal(kindFor('A thing with no kind'), 'box');

console.log('dust engine ok');
