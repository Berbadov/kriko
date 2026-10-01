import type { AgentInfo, Product, TagState } from './types';

/** Sample data only. Replace with reads from the local store (packs, subjects, claims, evidence, sources). */
export const products: Product[] = [
  { name: 'Product A', verdict: 'rec', confidence: 82, attributes: [
    { label: 'Noise cancelling', value: '38 dB, measured', sources: 5, best: true },
    { label: 'Battery, earbuds only', value: '6 h', sources: 4 },
    { label: 'Water resistance', value: 'IPX7', sources: 3, best: true },
    { label: 'Price', value: 'Mid', sources: 6 } ] },
  { name: 'Product B', verdict: 'weigh', confidence: 61, attributes: [
    { label: 'Noise cancelling', value: '33 dB, claimed', sources: 2 },
    { label: 'Battery, earbuds only', value: '8 h, sources disagree', sources: 4 },
    { label: 'Water resistance', value: 'IPX4', sources: 3 },
    { label: 'Price', value: 'Low', sources: 5, best: true } ] },
  { name: 'Product C', verdict: 'avoid', confidence: 74, attributes: [
    { label: 'Noise cancelling', value: 'None', sources: 3 },
    { label: 'Battery, earbuds only', value: '5 h', sources: 2 },
    { label: 'Water resistance', value: 'IPX2', sources: 2 },
    { label: 'Price', value: 'Low', sources: 4, best: true } ] },
];

export const agents: AgentInfo[] = [
  { id: 'claude-code', name: 'Claude Code', kind: 'CLI', state: 'live', stateLabel: 'Connected', latency: '42 ms', allowed: true },
  { id: 'opencode', name: 'opencode', kind: 'CLI', state: 'live', stateLabel: 'Connected', latency: '58 ms', allowed: true },
  { id: 'antigravity', name: 'Antigravity CLI', kind: 'CLI', state: 'need', stateLabel: 'Needs you', latency: 'sign in', allowed: false },
  { id: 'mistral-vibe', name: 'Mistral Vibe', kind: 'CLI', state: 'queue', stateLabel: 'Not found', latency: 'n/a', allowed: false },
  { id: 'github-copilot', name: 'GitHub Copilot CLI', kind: 'CLI', state: 'live', stateLabel: 'Connected', latency: '71 ms', allowed: true },
  { id: 'claude-desktop', name: 'Claude Desktop', kind: 'Desktop app', state: 'live', stateLabel: 'Connected', latency: '36 ms', allowed: true },
  { id: 'cursor', name: 'Cursor', kind: 'Desktop app', state: 'done', stateLabel: 'Idle', latency: '64 ms', allowed: true },
];

export interface KnowledgeRow { subject: string; attribute: string; value: string; claims: number; sources: number; trust: TagState; trustLabel: string }
export const knowledge: KnowledgeRow[] = [
  { subject: 'Product A earbuds', attribute: 'Noise cancelling', value: '38 dB', claims: 2, sources: 5, trust: 'done', trustLabel: 'Backed' },
  { subject: 'Product B earbuds', attribute: 'Battery, earbuds only', value: '6 h or 8 h', claims: 2, sources: 4, trust: 'need', trustLabel: 'Disputed' },
  { subject: 'Product C earbuds', attribute: 'Codec support', value: 'Not stated', claims: 0, sources: 0, trust: 'queue', trustLabel: 'No evidence' },
];
