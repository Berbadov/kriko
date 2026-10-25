/**
 * The runtime theme: one palette and one type scale, read through hooks.
 *
 * A build used to freeze its palette at bundle time, so choosing a light theme
 * meant building a second APK. Now `ThemeProvider` owns the choice, every
 * component reads it, and switching is a re-render.
 *
 * Styles are created per palette and cached, so `makeStyles` costs one
 * `StyleSheet.create` per theme for the life of the process — not one per
 * render. Components keep writing `color.ink` inside the factory; the palette
 * arrives as the factory's argument.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react';
import { Appearance, useColorScheme } from 'react-native';

import { palettes, type Colors } from './palettes';
import {
  resolvePalette,
  TEXT_SCALE,
  type Appearance as AppearanceChoice,
  type PaletteName,
  type TextSize,
} from './preferences';
import { type as baseType, type TypeScale } from './tokens';

export interface Theme {
  /** The palette in force. */
  name: PaletteName;
  /** True for the dark palette. */
  dark: boolean;
  color: Colors;
  /** The type scale, already scaled by the reader's text-size choice. */
  type: TypeScale;
}

const ThemeContext = createContext<Theme | null>(null);

function scaledType(scale: number): TypeScale {
  if (scale === 1) return baseType as TypeScale;
  const scaled = {} as Record<string, unknown>;
  for (const [key, value] of Object.entries(baseType)) {
    scaled[key] = {
      ...value,
      fontSize: Math.round(value.fontSize * scale * 100) / 100,
      lineHeight: Math.round(value.lineHeight * scale * 100) / 100,
    };
  }
  return scaled as TypeScale;
}

export function ThemeProvider({
  appearance,
  textSize,
  children,
}: {
  appearance: AppearanceChoice;
  textSize: TextSize;
  children: ReactNode;
}) {
  const scheme = useColorScheme();
  const name = resolvePalette(appearance, scheme);

  // Native dialogs, keyboards and the status bar follow the same choice. A
  // system choice gives control back to Android.
  useEffect(() => {
    try {
      Appearance.setColorScheme(
        appearance === 'system' ? 'auto' : name === 'dark' ? 'dark' : 'light',
      );
    } catch {
      // Older native runtimes may not expose it; the in-app colours still work.
    }
  }, [appearance, name]);

  const theme = useMemo<Theme>(
    () => ({
      name,
      dark: name === 'dark',
      color: palettes[name],
      type: scaledType(TEXT_SCALE[textSize]),
    }),
    [name, textSize],
  );

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const theme = useContext(ThemeContext);
  if (!theme) throw new Error('useTheme must be used inside ThemeProvider');
  return theme;
}

/** The palette alone, for components that only need colours. */
export function useColors(): Colors {
  return useTheme().color;
}

/** The reader's text scale applied to the type tokens. */
export function useType(): TypeScale {
  return useTheme().type;
}

/**
 * Turn `StyleSheet.create({...})` into a hook that rebuilds it when the palette
 * changes. The factory receives the palette as `color`, so existing style
 * bodies keep reading exactly as they did.
 *
 *   const useStyles = makeStyles((color) => StyleSheet.create({
 *     row: { backgroundColor: color.surface },
 *   }));
 *   const styles = useStyles();
 */
export function makeStyles<T>(factory: (color: Colors) => T): () => T {
  const cache = new WeakMap<Colors, T>();
  return function useStyles(): T {
    const { color } = useTheme();
    const hit = cache.get(color);
    if (hit) return hit;
    const created = factory(color);
    cache.set(color, created);
    return created;
  };
}
