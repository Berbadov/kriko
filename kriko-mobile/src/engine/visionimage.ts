/**
 * A second, tighter look at a tall photo.
 *
 * Product and label text on a phone screenshot or a tall product photo is
 * small once the whole frame is scaled down for the reader. When the image is
 * clearly taller than it is wide, we cut the band where a label or model plate
 * usually sits and send that crop beside the original. Nothing here may fail a
 * scan: any error, unsupported source or unreadable result returns the image
 * the caller already had.
 *
 * The native module is deliberately kept out of `providers.ts`, so the vision
 * request stays usable where image manipulation is not available.
 */

import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';

export interface VisionImage {
  base64: string;
  mime: string;
}

/** Tall enough that label text is likely lost when the whole frame is scaled. */
const TALL_RATIO = 1.6;
const CROP_TOP = 0.06;
const CROP_BOTTOM = 0.64;
/** The width sent to the vision model for a cropped label band. */
const DETAIL_WIDTH = 1100;
/** Decode no wider than this; the crop never needs more than the detail width. */
const LOAD_MAX_WIDTH = 1600;

/**
 * Crop a tall image's label band and return it as JPEG base64. Returns the
 * caller's own image untouched when the image is not tall, when it already fits,
 * or when anything goes wrong.
 */
export async function prepareVisionImage(uri: string, base64: string, mime: string): Promise<VisionImage> {
  const original: VisionImage = { base64, mime };
  if (!uri || !base64) return original;
  try {
    // Loading with a width cap keeps a modern camera photo from being decoded
    // at full size just to decide whether it is tall.
    const loaded = await ImageManipulator.manipulate(uri, { maxWidth: LOAD_MAX_WIDTH }).renderAsync();
    const width = loaded.width;
    const height = loaded.height;
    if (!width || !height || height <= TALL_RATIO * width) return original;

    const originY = Math.round(height * CROP_TOP);
    const band = Math.max(1, Math.round(height * (CROP_BOTTOM - CROP_TOP)));
    const bandHeight = Math.max(1, Math.min(band, height - originY));
    const context = ImageManipulator.manipulate(loaded);
    context.crop({ originX: 0, originY, width, height: bandHeight });
    if (width > DETAIL_WIDTH) context.resize({ width: DETAIL_WIDTH });
    const rendered = await context.renderAsync();
    const saved = await rendered.saveAsync({
      format: SaveFormat.JPEG,
      compress: 0.9,
      base64: true,
    });
    if (!saved.base64) return original;
    return { base64: saved.base64, mime: 'image/jpeg' };
  } catch {
    return original;
  }
}
