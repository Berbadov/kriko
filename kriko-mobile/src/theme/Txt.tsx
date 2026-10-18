import { Text, type TextProps, type TextStyle } from 'react-native';

import { color, type TypeToken, type as typeScale } from './tokens';

type Props = TextProps & {
  /** A token from the type scale. Defaults to body copy. */
  variant?: TypeToken;
  /** Any token from the colour palette, or a raw colour string. */
  tone?: keyof typeof color | (string & {});
  /** Uppercase the run without changing the string in the tree. */
  caps?: boolean;
  style?: TextStyle | TextStyle[];
};

/**
 * All text goes through here so a token decides the family, size, line height
 * and tracking, and the tone decides the colour.
 */
export function Txt({ variant = 'body', tone = 'ink', caps, style, ...rest }: Props) {
  const palette = color as Record<string, string>;
  const tint = palette[tone as string] ?? (tone as string);
  return (
    <Text
      {...rest}
      style={[
        typeScale[variant] as TextStyle,
        { color: tint },
        caps ? { textTransform: 'uppercase' } : null,
        style,
      ]}
    />
  );
}
