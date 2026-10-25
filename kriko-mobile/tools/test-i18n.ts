/**
 * Turkish coverage: every string a screen can render has a translation.
 *
 * The dictionary is keyed by the exact English, so a new label or error is easy
 * to forget. This walks the source's UI contexts (JSX text, labels, titles,
 * placeholders, accessibility labels, `tr(...)`, alerts and thrown messages)
 * and fails when one has no Turkish counterpart.
 *
 * Non-copy values — provider names, URLs, sample listing data, developer
 * invariants — are listed once below with the reason. Nothing else is exempt.
 */

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';

import { hasTranslation, tr, upper } from '../src/i18n';

const ROOT = process.env.KRIKO_MOBILE_ROOT ?? join(__dirname, '..');
const SRC = join(ROOT, 'src');

const UI_ATTRS = new Set([
  'label', 'title', 'subtitle', 'description', 'placeholder', 'accessibilityLabel',
  'crumb', 'note', 'body',
]);
const UI_PROPS = new Set(['label', 'title', 'subtitle', 'description', 'placeholder', 'crumb', 'note', 'body']);
const ERROR_NAMES = new Set(['Error', 'ProviderError', 'AccessError']);

/** Values that are not interface copy. */
const ALLOW_EXACT = new Set([
  // Product and provider names, kept as written.
  'Mercury 3',
  'DeepSeek Search & Fetch',
  'DeepSeek vision',
  'DeepSeek key',
  'Mercury key',
  'Türkçe',
  'Samsung',
  'Galaxy Buds2 Pro',
  'SM-R510',
  'github.com/Berbadov/kriko',
  'Kriko&apos;s read',
  'mercury_…',
  'sk-…',
  // The brand's letter, drawn on the floating K's preview.
  'K',
  // A format hint, not a sentence to translate.
  'The long line that starts with S1NB…',
  // Developer invariants; a reader never sees them.
  'useStore must be used inside StoreProvider',
  'useTheme must be used inside ThemeProvider',
  'OverlaySessionProvider is missing',
  // Internal error codes, never rendered.
  'not base64url',
  'exhausted',
]);

const ALLOW_PATTERNS: readonly RegExp[] = [
  /^kriko \/ /,
  /^https?:\/\//,
  /^[\d\s.,·%$€₺/+-]+$/,
  /^[a-z0-9_.-]+@[a-z0-9.-]+$/i,
];

function filesUnder(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...filesUnder(full));
    else if (/\.tsx?$/.test(entry.name) && !/i18n\.ts$|secrets\.ts$|licenses\.ts$/.test(entry.name)) out.push(full);
  }
  return out;
}

interface Candidate {
  text: string;
  where: string;
}

function collect(): Candidate[] {
  const found = new Map<string, Candidate>();
  for (const file of filesUnder(SRC)) {
    const source = readFileSync(file, 'utf8');
    const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
    const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, kind);
    const relativePath = relative(ROOT, file);
    const inEngine = relativePath.includes('engine');
    const add = (value: string, node: ts.Node) => {
      const text = value.replace(/\s+/g, ' ').trim();
      if (!text || !/[A-Za-z]/.test(text)) return;
      const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
      if (!found.has(text)) found.set(text, { text, where: `${relativePath}:${line}` });
    };
    const visit = (node: ts.Node) => {
      if (ts.isJsxText(node)) add(node.text, node);
      if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer)
        && UI_ATTRS.has(node.name.text)) {
        add(node.initializer.text, node.initializer);
      }
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'tr') {
        for (const arg of node.arguments) {
          if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) add(arg.text, arg);
        }
      }
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
        && node.expression.name.text === 'alert') {
        for (const arg of node.arguments) {
          if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) add(arg.text, arg);
        }
      }
      if (!inEngine && ts.isPropertyAssignment(node) && UI_PROPS.has(node.name.getText(sf))
        && ts.isStringLiteral(node.initializer)) {
        add(node.initializer.text, node.initializer);
      }
      if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && ERROR_NAMES.has(node.expression.text)) {
        const first = node.arguments?.[0];
        if (first && (ts.isStringLiteral(first) || ts.isNoSubstitutionTemplateLiteral(first))) add(first.text, first);
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return [...found.values()];
}

function exempt(text: string): boolean {
  if (ALLOW_EXACT.has(text)) return true;
  if (ALLOW_PATTERNS.some((pattern) => pattern.test(text))) return true;
  // A single all-caps run is a section eyebrow ("A MORE INFORMED PURCHASE") and
  // still needs a translation, so it is not exempt.
  return false;
}

/**
 * Capitals follow the app's language, not the phone's. A native
 * `textTransform: 'uppercase'` uses the device locale, so an English-locale
 * phone drew Turkish "geçmiş" as "GEÇMIŞ" (dotless I where İ belongs).
 */
function checkTurkishCapitals(): void {
  assert.equal(upper('geçmiş', 'tr'), 'GEÇMİŞ');
  assert.equal(upper('ışık ve iş', 'tr'), 'IŞIK VE İŞ');
  assert.equal(upper('ücretsiz', 'tr'), 'ÜCRETSİZ');
  assert.equal(upper('history', 'en'), 'HISTORY');
  assert.equal(tr('history', 'tr'), 'geçmiş');
  for (const file of filesUnder(SRC)) {
    const source = readFileSync(file, 'utf8');
    assert.ok(
      !/textTransform:\s*['"]uppercase['"]/.test(source),
      `${relative(ROOT, file)} sets textTransform: 'uppercase'; use <Txt caps> so Turkish capitals are right.`,
    );
  }
}

function main(): void {
  checkTurkishCapitals();
  const candidates = collect();
  const missing = candidates.filter((item) => !exempt(item.text) && !hasTranslation(item.text));
  if (missing.length) {
    const lines = missing.map((item) => `  ${item.where}  ${item.text}`).join('\n');
    assert.fail(
      `${missing.length} string(s) have no Turkish translation. Add them to src/i18n.ts (or exempt a non-copy value in this test):\n${lines}`,
    );
  }
  process.stdout.write(`i18n coverage checks passed (${candidates.length} strings).\n`);
}

main();
