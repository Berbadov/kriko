export type TagState = 'live' | 'need' | 'queue' | 'done' | 'block';
export type VerdictKind = 'rec' | 'weigh' | 'avoid';
export type ButtonVariant = 'key' | 'plate' | 'glass' | 'ghost' | 'danger';
export type GlyphName = 'bang5' | 'check5' | 'x5' | 'queue5' | 'scan5' | 'cols' | 'list' | 'grid' | 'wide' | 'play';

/** One entry in the side navigation. `icon` is an SVG path `d` on a 24x24 grid, drawn at 1.5px stroke. */
export interface NavItem {
  key: string;
  label: string;
  href: string;
  icon: string;
  count?: number | string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export interface SegmentOption<T extends string = string> {
  value: T;
  label: string;
  glyph: GlyphName;
}

export interface AgentInfo {
  id: string;
  name: string;
  kind: 'CLI' | 'Desktop app';
  /** Official vendor icon, url of a file from assets/Agents. Leave undefined to show the LED monogram. */
  icon?: string;
  state: TagState;
  stateLabel: string;
  latency: string;
  allowed: boolean;
}

export interface Product {
  name: string;
  verdict: VerdictKind;
  confidence: number;
  attributes: { label: string; value: string; sources: number; best?: boolean }[];
}
