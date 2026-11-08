/**
 * A field of dust for the phone: the engine in ./engine.ts drawn with Skia.
 *
 * The grains step on the JS thread, at most once a frame, and each frame is
 * recorded into one Skia picture handed to the canvas through a Reanimated
 * shared value, so React never re-renders for a frame. Grains are sorted into
 * brightness bins and each bin is one `drawPoints` call.
 *
 * It holds still (one frame, then nothing) under reduced motion, while the
 * app is in the background, when `paused` is set, and while it is off screen
 * for its caller (pass `paused` from a focus hook).
 */

import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, StyleSheet, View, type LayoutChangeEvent, type StyleProp, type ViewStyle } from 'react-native';
import {
  BlendMode,
  Canvas,
  Picture,
  PointMode,
  Skia,
  StrokeCap,
  createPicture,
  type SkPaint,
  type SkPicture,
} from '@shopify/react-native-skia';
import { useSharedValue } from 'react-native-reanimated';

import { useReducedMotion } from '../components/Motion';
import { useColors } from '../theme/theme';
import { Dust, grainsFor, type Motion, type Scene } from './engine';

const BINS = 8;

/** Whether a hex colour is light enough that grains should add light, not ink. */
function glows(hex: string): boolean {
  const h = hex.replace('#', '');
  if (h.length < 6) return false;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140;
}

export type DustCanvasProps = {
  scene: Scene;
  /** A band of light passes down through the cloud, as while a page is read. */
  reading?: boolean;
  /** The grains' colour; the palette's ink by default. */
  color?: string;
  /** How bright the field is, 0 to 1: a background behind text wants about a third. */
  strength?: number;
  /** Square points of field per grain. */
  per?: number;
  /** The most grains, whatever the size. The phone's JS thread sets the ceiling. */
  cap?: number;
  /** Stop moving without unmounting: an unfocused screen, a folded sheet. */
  paused?: boolean;
  /** Calm drifts slowly and does not shimmer. */
  calm?: boolean;
  /** Change this to throw the grains out from `burst.x, burst.y`. */
  burst?: { key: number; x: number; y: number };
  style?: StyleProp<ViewStyle>;
};

export const DustCanvas = memo(function DustCanvas({
  scene,
  reading = false,
  color,
  strength = 1,
  per = 14,
  cap = 6000,
  paused = false,
  calm = false,
  burst,
  style,
}: DustCanvasProps) {
  const palette = useColors();
  const reduced = useReducedMotion();
  // An unknown preference counts as reduced, the same rule as the rest of the app.
  const motion: Motion = reduced !== false ? 'still' : calm ? 'calm' : 'full';
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [awake, setAwake] = useState(AppState.currentState === 'active');
  const blank = useMemo(() => createPicture(() => {}), []);
  const picture = useSharedValue<SkPicture>(blank);
  const dust = useRef<Dust | null>(null);
  const ink = color ?? palette.ink;

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => setAwake(state === 'active'));
    return () => sub.remove();
  }, []);

  // One paint per brightness bin; light grains add light on a dark ground.
  const paints = useMemo(() => {
    const light = glows(ink);
    return Array.from({ length: BINS }, (_, b): SkPaint => {
      const paint = Skia.Paint();
      paint.setColor(Skia.Color(ink));
      paint.setAlphaf(Math.min(1, ((b + 0.5) / BINS) * (light ? 0.6 : 0.5) * strength));
      paint.setStrokeWidth(1.3);
      paint.setStrokeCap(StrokeCap.Square);
      if (light) paint.setBlendMode(BlendMode.Plus);
      return paint;
    });
  }, [ink, strength]);

  // A field of a new size gets a new cloud, settled on the current scene.
  useEffect(() => {
    if (!size.w || !size.h) return;
    const count = grainsFor(size.w, size.h, per, cap);
    if (!dust.current || dust.current.count !== count) {
      dust.current = new Dust({ count, seed: 7 });
      dust.current.resize(size.w, size.h);
      dust.current.show(scene, { settle: true });
    } else dust.current.resize(size.w, size.h);
    // `scene` is applied by its own effect below; this one is only about size.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size.w, size.h, per, cap]);

  // A new scene: the grains fly to it, or land on it when nothing may move.
  useEffect(() => {
    dust.current?.show(scene, { scatter: motion === 'full' ? 1 : 0.4, settle: motion === 'still' });
  }, [scene, motion]);

  useEffect(() => {
    if (burst && motion !== 'still') dust.current?.burst(burst.x, burst.y);
    // Only the key says a new burst happened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [burst?.key]);

  useEffect(() => {
    const d = dust.current;
    if (!d || !size.w) return;
    const out = d.buffers(BINS);
    // A pool of point objects per bin, reused every frame, so drawing allocates nothing.
    const pool = Array.from({ length: BINS }, () => Array.from({ length: d.count }, () => ({ x: 0, y: 0 })));
    const views: { x: number; y: number }[][] = Array.from({ length: BINS }, () => []);
    const draw = (t: number) => {
      const band = reading ? { y: ((t % 2.6) / 2.6) * (d.h + 120) - 60, width: 22 } : undefined;
      d.sort(out, { shimmer: motion === 'full', band });
      for (let b = 0; b < BINS; b++) {
        const n = out.counts[b];
        const p = out.points[b];
        const view = views[b];
        view.length = 0;
        for (let i = 0; i < n; i++) {
          const pt = pool[b][i];
          pt.x = p[i * 2];
          pt.y = p[i * 2 + 1];
          view.push(pt);
        }
      }
      picture.value = createPicture((canvas) => {
        for (let b = 0; b < BINS; b++) if (views[b].length) canvas.drawPoints(PointMode.Points, views[b], paints[b]);
      });
    };
    const still = motion === 'still' || paused || !awake;
    draw(0);
    if (still) return;
    let frame = 0;
    let last = 0;
    const tick = (now: number) => {
      const dt = last ? Math.min(3, ((now - last) / 1000) * 60) : 1;
      last = now;
      d.step(dt, now / 1000, motion);
      draw(now / 1000);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // `scene` restarts the loop so a still field redraws on its new picture.
  }, [size.w, size.h, per, cap, motion, paused, awake, reading, paints, picture, scene]);

  const onLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    if (Math.round(width) !== size.w || Math.round(height) !== size.h) setSize({ w: Math.round(width), h: Math.round(height) });
  };

  return (
    <View pointerEvents="none" style={[styles.fill, style]} onLayout={onLayout}>
      {size.w ? (
        <Canvas style={StyleSheet.absoluteFill}>
          <Picture picture={picture} />
        </Canvas>
      ) : null}
    </View>
  );
});

const styles = StyleSheet.create({
  fill: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0 },
});
