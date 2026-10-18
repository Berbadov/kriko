/**
 * Image helpers.
 *
 * A screenshot the user shares is a file URI. The sample that ships with the app
 * is a bundled asset module, and only the module number survives a round trip
 * through the store, so both shapes are handled here.
 */

import type { ImageSource } from 'expo-image';

export const SAMPLE_SHOT: number = require('./sample-listing.png');

export type ShotRef = string | number | undefined;

/** An expo-image source for a stored shot reference. */
export function shotSource(ref: ShotRef): ImageSource | number {
  if (ref === undefined) return SAMPLE_SHOT;
  return typeof ref === 'number' ? ref : { uri: ref };
}
