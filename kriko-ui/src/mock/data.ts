export interface Recent {
  id: string
  name: string
  note: string
  risks: number
  when: string
}

export const RECENTS: Recent[] = [
  { id: 'r1', name: 'Alpha Unit 200', note: 'Overheats under long load', risks: 1, when: '5 min ago' },
  { id: 'r2', name: 'Beta Unit 300', note: 'Short cable', risks: 1, when: '5 min ago' },
  { id: 'r3', name: 'Kingston A400 480 GB', note: 'Controller change after launch', risks: 3, when: 'Yesterday' },
  { id: 'r4', name: 'Condensing combi boiler', note: 'Heat exchanger wear', risks: 4, when: 'Yesterday' },
]

export const AGENTS = ['Default agent', 'Coding agent', 'Local model'] as const

export interface CompareProduct {
  id: string
  name: string
  maker: string
  risks: Record<string, 'none' | 'low' | 'high'>
}

export const COMPARE_ROWS = ['Heat', 'Cable', 'Noise', 'Battery', 'Support'] as const

export const COMPARE: CompareProduct[] = [
  { id: 'c1', name: 'Alpha Unit 200', maker: 'maker.example.test', risks: { Heat: 'high', Cable: 'none', Noise: 'low', Battery: 'none', Support: 'low' } },
  { id: 'c2', name: 'Beta Unit 300', maker: 'maker.example.test', risks: { Heat: 'none', Cable: 'high', Noise: 'none', Battery: 'low', Support: 'none' } },
]

export interface Drawer {
  id: string
  icon: 'cpu' | 'clock' | 'globe' | 'book' | 'gear' | 'spark' | 'check'
  title: string
  note: string
}

export const DRAWER: Drawer[] = [
  { id: 'foryou', icon: 'check', title: 'For you', note: 'What you need, what you bought' },
  { id: 'chat', icon: 'spark', title: 'Chat', note: 'What it remembers, product-only answers' },
  { id: 'setup', icon: 'spark', title: 'Set up Kriko', note: 'Verify an agent and connect your browser' },
  { id: 'backups', icon: 'clock', title: 'Backup and restore', note: 'Keep a copy of your saved work' },
  { id: 'agents', icon: 'spark', title: 'Agents', note: 'Choose who answers' },
  { id: 'local', icon: 'cpu', title: 'Local model', note: 'Run on this computer' },
  { id: 'history', icon: 'clock', title: 'History', note: 'Past research' },
  { id: 'browse', icon: 'book', title: 'Catalogs', note: 'Browse what is known' },
  { id: 'sites', icon: 'globe', title: 'Sites', note: 'Pages Kriko can read' },
  { id: 'settings', icon: 'gear', title: 'Settings', note: 'Look, motion, keys' },
]
