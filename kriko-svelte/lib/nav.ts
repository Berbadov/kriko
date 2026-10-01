import type { NavGroup } from './types';

// Icon paths: 24x24 grid, 1.5px stroke, rounded joins. Swap for Lucide equivalents if you prefer.
export const icons: Record<string, string> = {
  home: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  run: 'M8 5.5v13l10.5-6.5z',
  history: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7.5V12l3 2',
  compare: 'M4 4h7v16H4zM13 4h7v16h-7z',
  extension: 'M10 4a2 2 0 1 1 4 0v2h4v4h-2a2 2 0 1 0 0 4h2v4h-4v-2a2 2 0 1 0-4 0v2H6v-4h2a2 2 0 1 0 0-4H6V6h4z',
  overview: 'M4 18a8 8 0 1 1 16 0M12 18l4-6',
  browse: 'M4 6h16M4 12h16M4 18h10',
  sites: 'M3 12a9 9 0 1 0 18 0 9 9 0 1 0-18 0M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  agents: 'M5 8h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1zM12 8V4M9 13.5h.01M15 13.5h.01',
  benchmark: 'M4 13a8 8 0 1 0 16 0 8 8 0 1 0-16 0M12 9v4l2 2M9 2h6',
  settings: 'M4 7h9M17 7h3M4 17h3M11 17h9M13 7a2 2 0 1 0 4 0 2 2 0 1 0-4 0M7 17a2 2 0 1 0 4 0 2 2 0 1 0-4 0',
  about: 'M3 12a9 9 0 1 0 18 0 9 9 0 1 0-18 0M12 11v5M12 8h.01',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 1 0 0-14zM20 20l-4-4',
};

const item = (key: string, label: string, count?: number | string) => ({
  key,
  label,
  href: `/${key}`,
  icon: icons[key],
  ...(count !== undefined ? { count } : {}),
});

/**
 * The main navigation. To add the next tab, push an item into the right group,
 * add its path to `icons`, and nothing else changes: NavRail renders from this list.
 */
export const nav: NavGroup[] = [
  { label: 'Check', items: [item('home', 'Home'), item('run', 'Run'), item('history', 'History'), item('compare', 'Compare'), item('extension', 'Browser extension')] },
  { label: 'Knowledge', items: [item('overview', 'Overview'), item('browse', 'Browse', 760)] },
  { label: 'System', items: [item('sites', 'Sites'), item('activity', 'Activity'), item('agents', 'Agents'), item('benchmark', 'Benchmark')] },
  { label: 'This install', items: [item('settings', 'Settings'), item('about', 'About')] },
];
