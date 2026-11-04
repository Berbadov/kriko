/**
 * A small glyph for the kind of thing a scan is about, so a row of products can
 * be told apart before any title is read.
 *
 * The kind comes from the words the listing itself used. An unknown product
 * gets a neutral box; this never claims a category the text did not say.
 */

import {
  Armchair,
  Bike,
  Camera,
  Car,
  Cpu,
  Drill,
  Gamepad2,
  Headphones,
  Keyboard,
  Laptop,
  Monitor,
  Mouse,
  Package,
  Printer,
  Refrigerator,
  Shirt,
  Smartphone,
  Speaker,
  Tablet,
  Tv,
  Watch,
  WashingMachine,
  type LucideIcon,
} from 'lucide-react-native';
import { StyleSheet, View } from 'react-native';

import type { Reading } from '../engine/types';
import { useColors } from '../theme/theme';

const KINDS: { icon: LucideIcon; words: RegExp }[] = [
  { icon: Keyboard, words: /keyboard|keycap|klavye/i },
  { icon: Mouse, words: /\bmouse\b|trackball|fare\b/i },
  { icon: Headphones, words: /headphone|headset|earbud|earphone|buds|airpods|kulaklık/i },
  { icon: Speaker, words: /speaker|soundbar|hoparlör/i },
  { icon: Gamepad2, words: /gamepad|controller|console|joystick|gaming pad|oyun/i },
  { icon: Laptop, words: /laptop|notebook|macbook|thinkpad|dizüstü/i },
  { icon: Monitor, words: /monitor|display|ekran/i },
  { icon: Tv, words: /\btv\b|television|televizyon/i },
  { icon: Smartphone, words: /phone|iphone|galaxy s|pixel|telefon/i },
  { icon: Tablet, words: /tablet|ipad/i },
  { icon: Watch, words: /watch|band\b|saat/i },
  { icon: Camera, words: /camera|lens|gopro|kamera/i },
  { icon: Printer, words: /printer|yazıcı/i },
  { icon: Cpu, words: /\bcpu\b|\bgpu\b|graphics card|processor|motherboard|\bram\b|\bssd\b|ekran kartı/i },
  { icon: Drill, words: /\bdrill\b|saw\b|sander|grinder|screwdriver|matkap/i },
  { icon: Refrigerator, words: /fridge|refrigerator|freezer|buzdolabı/i },
  { icon: WashingMachine, words: /washer|washing machine|dryer|çamaşır/i },
  { icon: Armchair, words: /chair|sofa|desk|sandalye|koltuk/i },
  { icon: Bike, words: /\bbike\b|bicycle|scooter|bisiklet/i },
  { icon: Car, words: /\bcar\b|vehicle|tyre|tire|araba/i },
  { icon: Shirt, words: /shirt|jacket|shoe|sneaker|boot|coat|ayakkabı/i },
];

export function productIconFor(...parts: (string | undefined)[]): LucideIcon {
  const text = parts.filter(Boolean).join(' ');
  return KINDS.find((kind) => kind.words.test(text))?.icon ?? Package;
}

export function readingIcon(reading: Reading): LucideIcon {
  return productIconFor(reading.product, reading.brand, reading.model, reading.detail);
}

/** The glyph on a soft rounded tile. */
export function ProductTile({ icon: Icon, size = 36, active }: {
  icon: LucideIcon; size?: number; active?: boolean;
}) {
  const color = useColors();
  return (
    <View
      style={[
        styles.tile,
        {
          width: size,
          height: size,
          borderRadius: size / 2.6,
          backgroundColor: active ? color.accentSoft : color.raise,
        },
      ]}
    >
      <Icon size={size * 0.5} color={active ? color.accent : color.ink2} strokeWidth={1.7} />
    </View>
  );
}

const styles = StyleSheet.create({
  tile: { alignItems: 'center', justifyContent: 'center' },
});
