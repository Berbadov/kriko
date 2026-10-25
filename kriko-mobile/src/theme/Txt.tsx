import { Text, type TextProps, type TextStyle } from 'react-native';

import { tr, useLanguage } from '../i18n';
import type { Colors } from './palettes';
import type { TypeToken } from './tokens';
import { useTheme } from './theme';

type Props = TextProps & {
  /** A token from the type scale. Defaults to body copy. */
  variant?: TypeToken;
  /** Any token from the current palette, or a raw colour string. */
  tone?: keyof Colors | (string & {});
  /** Uppercase the run without changing the string in the tree. */
  caps?: boolean;
  /**
   * Translate the run through `src/i18n.ts` when the language is Turkish.
   * True by default; pass false for a string that is already translated, a
   * name, or copy that must read exactly as written.
   */
  translate?: boolean;
  style?: TextStyle | TextStyle[];
};

/**
 * All text goes through here so a token decides the family, size, line height
 * and tracking, and the tone decides the colour. Both come from the runtime
 * theme, so a palette or text-size change re-renders every run in place.
 */
export function Txt({
  variant = 'body',
  tone = 'ink',
  caps,
  translate = true,
  style,
  children,
  ...rest
}: Props) {
  const language = useLanguage();
  const theme = useTheme();
  const palette = theme.color as Record<string, string>;
  const tint = palette[tone as string] ?? (tone as string);
  // Only one string can be swapped. An array or an element is a composed run —
  // a value interpolated into a sentence — and its owner translates that, not
  // this component.
  const text =
    translate && language === 'tr' && typeof children === 'string'
      ? tr(children, language)
      : children;
  return (
    <Text
      {...rest}
      style={[
        theme.type[variant] as TextStyle,
        { color: tint },
        caps ? { textTransform: 'uppercase' } : null,
        style,
      ]}
    >
      {text}
    </Text>
  );
}
