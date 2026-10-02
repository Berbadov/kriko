export type TagState = 'live' | 'need' | 'queue' | 'done' | 'block';
export type ButtonVariant = 'key' | 'plate' | 'glass' | 'ghost' | 'danger';
export type GlyphName =
  | 'bang5'
  | 'check5'
  | 'x5'
  | 'queue5'
  | 'scan5'
  | 'cols'
  | 'list'
  | 'grid'
  | 'wide'
  | 'play';

export interface SegmentOption<T extends string = string> {
  value: T;
  label: string;
  glyph: GlyphName;
}
